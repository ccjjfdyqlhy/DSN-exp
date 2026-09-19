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

logger = logging.getLogger("DSNUIProviders")

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

    # ── 持久化 ──

    def load(self) -> list[dict]:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict) and isinstance(raw.get("providers"), list):
                    return raw["providers"]
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 api_providers.json 失败: %s", e)
        return []

    def save(self, providers: list[dict]) -> None:
        try:
            self.path.write_text(
                json.dumps(providers, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001
            logger.error("写入 api_providers.json 失败: %s", e)

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
        record = {
            "id": pid,
            "label": str(data.get("label") or existing and existing.get("label") or "Provider"),
            "protocol": protocol,
            "base_url": str(data.get("base_url") or DEFAULT_BASE_URLS[protocol]),
            "api_key": str(data.get("api_key") or ""),
            "models": list(data.get("models") or (existing or {}).get("models") or []),
            "enabled": bool(data.get("enabled", True)),
            "extra_headers": dict(data.get("extra_headers") or {}),
            "timeout": int(data.get("timeout") or 300),
            "max_tokens": int(data.get("max_tokens") or 4096),
            "created_at": (existing or {}).get("created_at") or time.time(),
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
        "created_at": provider.get("created_at"),
    }


def discovered_model_name(provider_label: str, model: str) -> str:
    """注册进 orchestrator 的模型名（带 provider 前缀避免冲突）。"""
    return f"{provider_label} / {model}"


# ────────────────────────── 远端模型发现 ──────────────────────────

def discover_models(
    *,
    protocol: str,
    base_url: str,
    api_key: str,
    timeout: float = 30.0,
    extra_headers: Optional[dict] = None,
) -> list[str]:
    """向远端询问可用模型列表。

    三种协议的发现方式不同：
      * chat / responses → GET {base_url}/models（OpenAI 标准）
      * anthropic        → GET {base_url}/v1/models
                           （Anthropic 官方 2024 年后提供；失败则回退到一个
                            内置的常用模型名列表，保证 UI 可用）
    """
    headers = dict(extra_headers or {})
    headers.setdefault("Content-Type", "application/json")

    if protocol == "anthropic":
        headers.setdefault("x-api-key", api_key)
        headers.setdefault("anthropic-version", "2023-06-01")
        url = base_url.rstrip("/") + "/v1/models"
    else:
        headers.setdefault("Authorization", f"Bearer {api_key}")
        base = base_url.rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"

    import requests
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            detail = (resp.text or "")[:500]
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("模型发现失败 (%s %s): %s", protocol, url, e)
        raise

    # OpenAI 形态：{"data": [{"id": ...}]}
    # Anthropic 形态：{"data": [{"id": ..., "display_name": ...}]}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("远端返回的模型列表格式无法识别")

    out: list[str] = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
            if mid:
                out.append(str(mid))
    out = sorted(set(out))
    logger.info("模型发现成功 (%s): %d 个", protocol, len(out))
    return out


# Anthropic 官方 /v1/models 不可用时的兜底列表
ANTHROPIC_FALLBACK_MODELS = [
    "claude-3-5-haiku-latest",
    "claude-3-5-sonnet-latest",
    "claude-3-7-sonnet-latest",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
]
