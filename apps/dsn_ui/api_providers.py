# apps/dsn_ui/api_providers.py
"""远程 API Provider 管理：多 provider、多协议、持久化与模型发现。

## 支持的请求协议

| protocol    | 端点                          | 客户端                    |
|-------------|-------------------------------|---------------------------|
| chat        | /v1/chat/completions          | OpenAICompatClient        |
| responses   | /v1/responses                 | OpenAICompatClient        |
| anthropic   | /v1/messages                  | AnthropicCompatClient     |

## 数据模型

一个 Provider 记录：

    {
      "id": "uuid",                    # 稳定标识（模型名会带上它做命名空间）
      "label": "我的 OpenAI",           # 展示名
      "protocol": "chat",              # chat | responses | anthropic
      "base_url": "https://.../v1",
      "api_key": "sk-...",
      "models": ["gpt-4o", ...],       # 探测到/手填的可用模型
      "enabled": true,
      "extra_headers": {},             # 可选自定义请求头
      "timeout": 300,
      "max_tokens": 4096,
      "created_at": 1234567890
    }

持久化到 apps/dsn_ui/data/api_providers.json（该目录已被 .gitignore 忽略）。

## 存储拆分：名单明文 + 请求配置/认证信息加密入库

「API 的请求方式与认证信息」绝不落盘为明文。存储被拆成两半：

  * **名单**（api_providers.json，明文）
      id / label / enabled / models / created_at / updated_at
      只含非敏感路由元数据，保证列表、筛选、排查都不依赖主密钥。
  * **请求配置 + 认证信息**（dsn_ui 独立 sqlite 库 dsn_ui_secrets.db，密文）
      protocol / base_url / api_key / extra_headers / timeout / max_tokens
      以及任何其它字段，整块 JSON 经 apps/dsn_ui/credentials.py 的 Fernet
      加密成一个 enc:v1:<token>，按 provider 一行存进 provider_secrets 表。

load() 把两者 join 起来，内存中仍是明文（引擎要明文才能调用远端 API）；
save() 再拆开分别落盘。旧安装里内联在 json 里的明文/半加密字段会在首次
load() 时被一次性迁移进加密库，名单随之被清理，磁盘上不再残留凭据。

## 模型命名

注册进 orchestrator 的名字形如 `<label> / <model>`，避免多个 provider
出现同名模型时互相覆盖；同时用 provider id 维护反向映射，便于卸载。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from apps.dsn_ui.credentials import CredentialCipher, is_encrypted

logger = logging.getLogger("DSNUIProviders")

#: 明文留在 api_providers.json 的「名单」字段 —— 不含任何请求配置或凭据。
_ROSTER_FIELDS = (
    "id", "label", "enabled", "models", "created_at", "updated_at",
    # 视觉能力声明属于「非敏感的路由元数据」：它是布尔开关，不是凭据，
    # 放进明文名单可以保证列表/排查不依赖主密钥。
    "vision",
)

#: 需要加密的字段（请求方式 + 认证信息）。仅用于**识别并迁移**旧版内联数据；
#: 新格式下这些字段一律只存在于加密数据库里，json 名单中不会出现。
_SENSITIVE_KEYS = (
    "api_key",
    "protocol",
    "base_url",
    "extra_headers",
    "timeout",
    "max_tokens",
)

#: 加密密文库文件名（dsn_ui 自有数据库，与明文名单文件分离）
SECRETS_DB_NAME = "dsn_ui_secrets.db"

VALID_PROTOCOLS = ("chat", "responses", "anthropic")

# 各协议的默认 base_url（用户可覆盖）
DEFAULT_BASE_URLS = {
    "chat": "https://api.openai.com/v1",
    "responses": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class APIProviderStore:
    """Provider 的增删改查与持久化。"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "api_providers.json"
        #: dsn_ui 自有的加密数据库（请求配置 + 认证信息）
        self.secrets_db_path = self.data_dir / SECRETS_DB_NAME
        #: 凭据加解密器（惰性创建）
        self._cipher: Optional[CredentialCipher] = None
        #: 密文库（惰性打开）
        self._secrets: Optional[Any] = None

    # ── 凭据加解密 / 密文库 ──

    def _get_cipher(self) -> CredentialCipher:
        if self._cipher is None:
            # 注意：CredentialCipher 的第一个参数是 key，不是 data_dir
            self._cipher = CredentialCipher(data_dir=self.data_dir)
        return self._cipher

    def _get_secrets(self) -> Any:
        """惰性打开 dsn_ui 自有 sqlite 密文库并建表。

        复用仓库既有的 infra.store.sqlite.SqliteStore 与 topic_manager 的建表风格。
        """
        if self._secrets is None:
            from infra.store.sqlite import SqliteStore

            store = SqliteStore(str(self.secrets_db_path))
            conn = store.get_connection()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_secrets (
                    provider_id TEXT PRIMARY KEY,
                    ciphertext TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.commit()
            self._secrets = store
        return self._secrets

    def _read_secret(self, provider_id: str) -> Optional[dict]:
        """读取并解密某 provider 的请求配置 + 认证信息。"""
        if not provider_id:
            return None
        rows = self._get_secrets().execute(
            "SELECT ciphertext FROM provider_secrets WHERE provider_id = ?",
            (provider_id,),
        )
        if not rows:
            return None
        plaintext = self._get_cipher().decrypt_str(rows[0]["ciphertext"])
        if not plaintext:
            return None
        try:
            data = json.loads(plaintext)
        except Exception:  # noqa: BLE001
            logger.error("密文库中 provider %s 的内容不是合法 JSON，已忽略", provider_id)
            return None
        return data if isinstance(data, dict) else None

    def _write_secret(self, provider_id: str, payload: dict, updated_at: float) -> None:
        """把整块请求配置加密成单个 enc:v1: 密文写入数据库。"""
        token = self._get_cipher().encrypt_str(
            json.dumps(payload, ensure_ascii=False)
        )
        self._get_secrets().execute(
            "INSERT INTO provider_secrets (provider_id, ciphertext, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(provider_id) DO UPDATE SET "
            "ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
            (provider_id, token, float(updated_at)),
        )

    def _prune_secrets(self, keep_ids: list) -> None:
        """删除名单里已不存在的密文行（避免删除 provider 后残留凭据）。"""
        if not keep_ids:
            self._get_secrets().execute("DELETE FROM provider_secrets")
            return
        placeholders = ",".join("?" for _ in keep_ids)
        self._get_secrets().execute(
            f"DELETE FROM provider_secrets WHERE provider_id NOT IN ({placeholders})",
            tuple(keep_ids),
        )

    def _decode_inline(self, inline: dict) -> dict:
        """把旧格式内联的敏感字段解回明文。

        task-17 的中间版本（v1）曾把 api_key 单字段加密后仍内联在 json 里，
        因此内联值本身可能就是 enc:v1: 密文 —— 迁移时必须先解开，否则会把
        "密文的密文"写进库，读出来仍是密文。
        """
        out: dict = {}
        cipher = None
        for key, value in inline.items():
            if isinstance(value, str) and is_encrypted(value):
                if cipher is None:
                    cipher = self._get_cipher()
                out[key] = cipher.decrypt_str(value)
            else:
                out[key] = value
        return out

    # ── 名单文件 ──

    def _read_roster(self) -> list[dict]:
        """读取 api_providers.json。

        新格式只含名单；旧格式可能内联敏感字段（明文或半加密），由 load() 迁移。
        """
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                records = None
                if isinstance(raw, list):
                    records = raw
                elif isinstance(raw, dict) and isinstance(raw.get("providers"), list):
                    records = raw["providers"]
                if records is not None:
                    return [r for r in records if isinstance(r, dict)]
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 api_providers.json 失败: %s", e)
        return []

    # ── 公开持久化 API（签名保持不变）──

    def load(self) -> list[dict]:
        """join 名单 + 密文库，返回明文记录；顺带一次性迁移历史数据。"""
        roster = self._read_roster()
        if not roster:
            return roster

        out: list[dict] = []
        needs_migration = False
        for record in roster:
            rec = dict(record)
            provider_id = str(rec.get("id") or "")
            inline = {k: rec[k] for k in _SENSITIVE_KEYS if k in rec}
            secret = self._read_secret(provider_id) if provider_id else None

            if secret is None:
                if inline:
                    # 旧版：请求配置/凭据直接内联在 json 名单里
                    needs_migration = True
                    secret = self._decode_inline(inline)
                else:
                    secret = {}
            elif inline:
                # 半迁移状态：库里已有，名单里还残留旧字段
                needs_migration = True
                for key, value in self._decode_inline(inline).items():
                    secret.setdefault(key, value)

            merged = {k: v for k, v in rec.items() if k not in _SENSITIVE_KEYS}
            merged.update(secret)
            out.append(merged)

        if needs_migration:
            logger.warning(
                "检测到 %s 中的请求配置/凭据尚未加密入库，正在迁移到 %s ...",
                self.path.name, self.secrets_db_path.name,
            )
            try:
                self.save(out)
                logger.warning("请求配置与认证信息已加密迁移完成，明文名单已清理")
            except Exception:  # noqa: BLE001 - 迁移失败不能阻断读取
                logger.exception("凭据加密迁移失败（数据仍可读，下次再试）")
        return out

    def save(self, providers: list[dict]) -> None:
        """写入明文名单 + 加密密文库。不修改调用方传入的对象。"""
        try:
            keep_ids: list[str] = []
            roster_disk: list[dict] = []
            pending: list = []

            for provider in providers:
                rec = dict(provider)
                provider_id = str(rec.get("id") or "")
                if not provider_id:
                    logger.warning("跳过缺少 id 的 provider 记录")
                    continue
                keep_ids.append(provider_id)
                roster_disk.append(
                    {k: v for k, v in rec.items() if k in _ROSTER_FIELDS}
                )
                payload = {k: v for k, v in rec.items() if k not in _ROSTER_FIELDS}
                pending.append(
                    (provider_id, payload, float(rec.get("updated_at") or time.time()))
                )

            # 明文名单（不含任何请求配置/凭据）
            self.path.write_text(
                json.dumps(roster_disk, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for provider_id, payload, updated_at in pending:
                self._write_secret(provider_id, payload, updated_at)
            self._prune_secrets(keep_ids)
        except Exception as e:  # noqa: BLE001
            logger.error("写入 provider 存储失败: %s", e)

    # ── CRUD ──

    def list(self) -> list[dict]:
        return self.load()

    def get(self, provider_id: str) -> Optional[dict]:
        for p in self.load():
            if p.get("id") == provider_id:
                return p
        return None

    def upsert(self, data: dict) -> dict:
        """新增或更新一个 provider（按 id 匹配；无 id 则新建）。"""
        providers = self.load()
        pid = data.get("id") or uuid.uuid4().hex[:12]
        protocol = str(data.get("protocol") or "chat")
        if protocol not in VALID_PROTOCOLS:
            raise ValueError(f"不支持的协议: {protocol}（可选 {VALID_PROTOCOLS}）")

        existing = next((p for p in providers if p.get("id") == pid), None)
        prev = existing or {}

        # 更新时**缺省字段沿用旧值**而不是打回默认值。
        #
        # 历史行为：timeout/max_tokens/extra_headers 一律 data.get(...) or 默认，
        # 于是只带 {id,label,protocol,base_url,models,enabled} 的部分更新
        # （前端「启用/停用」正是这么发的）会把用户配置的超时、输出上限和
        # 自定义请求头全部静默重置成 300 / 4096 / {}；x-dsn-vision 被清掉后
        # 多模态能力随之消失，而界面上没有任何提示。
        def _pick(key: str, default: Any) -> Any:
            if key in data and data[key] is not None:
                return data[key]
            return prev.get(key, default)

        record = {
            "id": pid,
            "label": str(data.get("label") or prev.get("label") or "Provider"),
            "protocol": protocol,
            "base_url": str(data.get("base_url") or prev.get("base_url") or DEFAULT_BASE_URLS[protocol]),
            # 空 api_key 表示「沿用已保存的 key」（前端不回显明文）
            "api_key": str(data.get("api_key") or prev.get("api_key") or ""),
            "models": list(
                data["models"] if isinstance(data.get("models"), list)
                else prev.get("models") or []
            ),
            "enabled": bool(data.get("enabled", prev.get("enabled", True))),
            "extra_headers": dict(_pick("extra_headers", {}) or {}),
            "timeout": int(_pick("timeout", 300) or 300),
            "max_tokens": int(_pick("max_tokens", 4096) or 4096),
            # 远端模型能否收图无法自动探测，由用户显式声明；engine 会把它
            # 转成 x-dsn-vision 请求头供 _configured_vision() 读取。
            "vision": bool(_pick("vision", False)),
            "created_at": prev.get("created_at") or time.time(),
            "updated_at": time.time(),
        }
        if existing:
            providers = [record if p.get("id") == pid else p for p in providers]
        else:
            providers.append(record)
        self.save(providers)
        logger.info("已保存 API Provider: %s (%s, %s)", record["label"], record["id"], protocol)
        return record

    def delete(self, provider_id: str) -> bool:
        providers = self.load()
        remaining = [p for p in providers if p.get("id") != provider_id]
        if len(remaining) == len(providers):
            return False
        self.save(remaining)
        logger.info("已删除 API Provider: %s", provider_id)
        return True


def mask_key(api_key: str) -> str:
    """API Key 脱敏展示（只暴露首尾少量字符）。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * 8}{api_key[-4:]}"


def public_view(provider: dict) -> dict:
    """对外返回的 provider 视图：**不包含明文 API Key**。"""
    return {
        "id": provider.get("id"),
        "label": provider.get("label"),
        "protocol": provider.get("protocol"),
        "base_url": provider.get("base_url"),
        "api_key_masked": mask_key(provider.get("api_key") or ""),
        "has_api_key": bool(provider.get("api_key")),
        "models": list(provider.get("models") or []),
        "enabled": bool(provider.get("enabled", True)),
        "timeout": provider.get("timeout", 300),
        "max_tokens": provider.get("max_tokens", 4096),
        "extra_headers": dict(provider.get("extra_headers") or {}),
        # 用户声明的视觉能力。此前 upsert 根本不保存该字段，导致 engine 里
        # provider.get("vision") 恒为 None、x-dsn-vision 永不注入 →
        # 远端多模态模型在 UI 上永远被判为纯文本。
        "vision": bool(provider.get("vision", False)),
        "created_at": provider.get("created_at"),
    }


def discovered_model_name(provider_label: str, model: str) -> str:
    """注册进 orchestrator 的模型名（带 provider 前缀避免冲突）。"""
    return f"{provider_label} / {model}"


# ────────────────────────── 远端模型发现 ──────────────────────────

#: 用户可能把整个端点粘进 base_url；发现前缀时必须先剥掉这些后缀。
_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/chatcompletions",
    "/completions",
    "/responses",
    "/messages",
    "/models",
)


def normalize_base_url(base_url: str) -> str:
    """把用户填的 base_url 归一成「服务根」，供拼接发现/请求路径。

    处理三类常见输入：
      * "https://host/v1/chat/completions" -> "https://host/v1"（粘了完整端点）
      * "https://host/v1/"                 -> "https://host/v1"（尾斜杠）
      * "https://host"                     -> "https://host"（裸 host）
    不做"是否带 /v1"的判断 —— 由 candidates 逐条尝试，避免猜错。
    """
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    lowered = base.lower()
    for suffix in _ENDPOINT_SUFFIXES:
        if lowered.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    return base


def _listing_candidates(base_url: str, protocol: str = "chat") -> list[str]:
    """按顺序返回候选的模型列表 URL（去重、保序）。

    OpenAI 标准是 /v1/models，但大量兼容网关只实现 /models、或不实现列表端点，
    因此这里多试几条，而不是假设只有一个正确形状。
    """
    base = normalize_base_url(base_url)
    if not base:
        return []

    urls: list[str] = []

    def _add(url: str) -> None:
        if url and url not in urls:
            urls.append(url)

    lowered = base.lower()
    if protocol == "anthropic":
        # Anthropic 官方：GET {base}/v1/models（base 通常已含 /v1 或不含）
        _add(base + "/models" if lowered.endswith("/v1") else base + "/v1/models")
        _add(base + "/models")
        return urls

    if lowered.endswith("/v1"):
        # 用户已带 /v1：优先 {base}/models，再退回其上一级的 {host}/models
        _add(base + "/models")
        _add(base[: -len("/v1")].rstrip("/") + "/models")
    else:
        _add(base + "/v1/models")
        _add(base + "/models")
    return urls


def _auth_schemes(api_key: str, extra_headers: Optional[dict] = None) -> list[dict]:
    """按顺序返回候选认证头组合。

    不同网关认不同的头：OpenAI 系用 Authorization: Bearer，Anthropic 系用
    x-api-key，Azure/部分自建网关用 api-key。先试用户显式提供的头，再逐个兜底。
    """
    base = dict(extra_headers or {})
    base.setdefault("Content-Type", "application/json")

    # 用户显式给了认证头 -> 只试它（尊重用户意图，不做猜测）
    if any(h.lower() in ("authorization", "x-api-key", "api-key") for h in base):
        return [base]

    schemes: list[dict] = []
    if api_key:
        schemes.append({**base, "Authorization": f"Bearer {api_key}"})
        schemes.append({**base, "x-api-key": api_key})
        schemes.append({**base, "api-key": api_key})
    else:
        schemes.append(base)
    return schemes


def _extract_model_ids(data: Any) -> list[str]:
    """从各种可能的响应形状里提取模型 id。

    覆盖：{"data":[...]} / {"models":[...]} / 裸 [...] / {"data":{"models":[...]}}
    / {"result":[...]} / {"data":{"data":[...]}}，元素可为 str 或 dict
    （id / name / model / display_name / model_name）。
    """
    items: Any = None

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("data", "models", "result", "items"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
            if isinstance(value, dict):
                # 形如 {"data": {"models": [...]}} 的嵌套
                for nested_key in ("models", "data", "items", "result"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        items = nested
                        break
            if items is not None:
                break

    if not isinstance(items, list):
        return []

    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            mid = (item.get("id") or item.get("name") or item.get("model")
                   or item.get("display_name") or item.get("model_name"))
            if mid:
                out.append(str(mid))
    return sorted({m.strip() for m in out if str(m).strip()})


def _discovery_ignores_proxy() -> bool:
    """探测是否应绕过代理环境变量。

    默认**遵守**用户的代理设置（企业网关常需走代理），但允许显式关闭：
        DSN_UI_DISCOVERY_NO_PROXY=1

    设为 1 后忽略 HTTP_PROXY / ALL_PROXY 等变量 —— 适用于「代理没起导致本地
    请求全失败」这种环境（与 infra/orchestrator/base.py 里本地引擎的处理同理）。
    """
    import os

    return str(os.getenv("DSN_UI_DISCOVERY_NO_PROXY") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


class ModelDiscoveryError(RuntimeError):
    """模型发现失败；message 已是可读的中文说明（含试过的 URL 与各自状态）。"""


def discover_models(
    *,
    protocol: str,
    base_url: str,
    api_key: str,
    timeout: float = 30.0,
    extra_headers: Optional[dict] = None,
) -> list[str]:
    """向远端询问可用模型列表（尽力而为，失败必须说明原因）。

    策略：对每条候选 URL × 每种认证头组合依次尝试，任一返回 2xx 且能解析出
    模型即成功。全部失败时抛 ModelDiscoveryError，消息里列出**试过的每条 URL
    及其 HTTP 状态/异常**，让 UI 能给出可操作提示，而不是一句"未发现模型"。

    anthropic 协议在全部失败时回退到内置常用模型名列表（保持原行为）。
    """
    import requests

    # 复用一条会话：探测会打多个 URL，每条都新建连接既慢又容易触发对端限流。
    # trust_env 按需关闭 —— 若用户环境里配了 ALL_PROXY 而代理没起，requests
    # 会把所有请求都塞给代理直接 ConnectionError，表现为「明明能访问却探测失败」。
    session = requests.Session()
    if _discovery_ignores_proxy():
        session.trust_env = False

    urls = _listing_candidates(base_url, protocol)
    schemes = _auth_schemes(api_key, extra_headers)
    attempts: list[str] = []

    for url in urls:
        for headers in schemes:
            try:
                resp = session.get(url, headers=headers, timeout=timeout)
            except Exception as e:  # noqa: BLE001 - 网络错误同样要记录下来
                attempts.append(f"{url} -> {type(e).__name__}: {e}")
                continue

            if resp.status_code >= 400:
                attempts.append(f"{url} -> HTTP {resp.status_code}")
                # 认证失败/无权限时换下一种认证头再试；其它错误换下一条 URL
                if resp.status_code in (401, 403):
                    continue
                break

            try:
                data = resp.json()
            except Exception as e:  # noqa: BLE001
                attempts.append(f"{url} -> HTTP {resp.status_code} 但响应不是 JSON: {e}")
                break

            models = _extract_model_ids(data)
            if models:
                logger.info("模型发现成功 (%s %s): %d 个", protocol, url, len(models))
                return models
            attempts.append(
                f"{url} -> HTTP {resp.status_code} 但无法从响应中解析出模型列表"
            )
            break

    detail = "；".join(attempts) if attempts else "没有可用的候选地址"
    logger.warning("模型发现失败 (%s, base_url=%s): %s", protocol, base_url, detail)

    if protocol == "anthropic":
        logger.warning("Anthropic 模型发现不可用，回退到内置常用模型列表")
        return list(ANTHROPIC_FALLBACK_MODELS)

    raise ModelDiscoveryError(
        "未发现模型：已尝试以下地址但均未成功 —— " + detail +
        "。若该服务确实没有模型列表端点（常见于部分兼容网关），"
        "请直接手工填写模型 ID（如 gpt-4o-mini），保存后即可使用。"
    )


def chat_completion_url(base_url: str) -> str:
    """合成 chat completions 的完整 URL（base_url 可含或不含 /v1，也可已含端点）。"""
    base = normalize_base_url(base_url)
    if not base:
        return ""
    return base + "/chat/completions" if base.lower().endswith("/v1") \
        else base + "/v1/chat/completions"


def resolve_chat_headers(
    api_key: str, extra_headers: Optional[dict] = None
) -> dict:
    """chat 请求的认证头（用户显式给的优先）。"""
    headers = dict(extra_headers or {})
    headers.setdefault("Content-Type", "application/json")
    if api_key and not any(
        h.lower() in ("authorization", "x-api-key", "api-key") for h in headers
    ):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


TEST_CHAT_MESSAGE = "请只回复两个字：你好"

# Anthropic 官方 /v1/models 不可用时的兜底列表
ANTHROPIC_FALLBACK_MODELS = [
    "claude-3-5-haiku-latest",
    "claude-3-5-sonnet-latest",
    "claude-3-7-sonnet-latest",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
]
