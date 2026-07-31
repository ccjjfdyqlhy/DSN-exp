# models/api_accounts.py
# 多 OpenAI 兼容 API 账号管理 — 账号列表 + 优先级 + 自动回退
# 每个账号: name / base_url / api_key / model / priority / enabled
# 持久化: .dsn/api_accounts.json（含密钥，已 gitignore）

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("APIAccounts")

_ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".dsn", "api_accounts.json")

# 默认优先级（越小越优先）
DEFAULT_PRIORITY = 100


@dataclass
class APIAccount:
    name: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    priority: int = DEFAULT_PRIORITY
    enabled: bool = True
    backup_api_key: str = ""
    last_error: str = ""
    created_at: float = field(default_factory=time.time)

    def mask_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "priority": self.priority,
            "enabled": self.enabled,
            "backup_api_key": self.backup_api_key,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> APIAccount:
        return cls(
            name=data.get("name", ""),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            model=data.get("model", ""),
            priority=int(data.get("priority", DEFAULT_PRIORITY)),
            enabled=bool(data.get("enabled", True)),
            backup_api_key=data.get("backup_api_key", ""),
            last_error=data.get("last_error", ""),
            created_at=float(data.get("created_at", time.time())),
        )


class APIManager:
    """账号列表管理: 增删改查 + 优先级 + 持久化"""

    def __init__(self, path: str | None = None):
        self._path = path or _ACCOUNTS_FILE
        self._accounts: dict[str, APIAccount] = {}
        self._lock = threading.Lock()
        self.load()

    # === 持久化 ===

    def load(self) -> None:
        try:
            p = Path(self._path)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("accounts", [])
            with self._lock:
                self._accounts = {a.name: a for a in (APIAccount.from_dict(d) for d in items)}
            logger.info("API 账号已加载: %d 个", len(self._accounts))
        except Exception as e:
            logger.error("加载 API 账号失败: %s", e)

    def save(self) -> None:
        try:
            p = Path(self._path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                items = [a.to_dict() for a in sorted(self._accounts.values(),
                                                     key=lambda a: (a.priority, a.name))]
            p.write_text(json.dumps({"accounts": items}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            try:
                os.chmod(self._path, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.error("保存 API 账号失败: %s", e)

    # === CRUD ===

    def _env_fallback_account(self) -> APIAccount | None:
        """.env 中配置的主账号（OPENAI_API_KEY）。未在账号管理器中托管时作为隐含账号暴露。"""
        try:
            from config import Config
            key = getattr(Config, "OPENAI_API_KEY", "") or ""
            if not key or key == "sk-your-key-here":
                return None
            return APIAccount(
                name="main",
                base_url=getattr(Config, "OPENAI_API_BASE", "") or "",
                api_key=key,
                model=getattr(Config, "MAIN_MODEL_NAME", "") or "",
                priority=0,
                enabled=True,
            )
        except Exception as e:
            logger.debug("读取 .env 主账号失败: %s", e)
            return None

    def list_accounts(self) -> list[dict]:
        with self._lock:
            items = sorted(self._accounts.values(), key=lambda a: (a.priority, a.name))
        result = [a.to_dict() for a in items]
        # 无托管账号时，暴露 .env 中配置的主账号，避免"看似未配置"
        if not result:
            fb = self._env_fallback_account()
            if fb is not None:
                result.append(fb.to_dict())
        return result

    def get(self, name: str) -> APIAccount | None:
        with self._lock:
            return self._accounts.get(name)

    def add(self, name: str, base_url: str = "", api_key: str = "",
            model: str = "", priority: int | None = None,
            enabled: bool = True) -> tuple[bool, str]:
        if not name:
            return False, "账号名不能为空"
        with self._lock:
            if name in self._accounts:
                return False, f"账号 '{name}' 已存在"
            if priority is None:
                priority = max((a.priority for a in self._accounts.values()), default=0) + 10
            self._accounts[name] = APIAccount(
                name=name, base_url=base_url, api_key=api_key, model=model,
                priority=priority, enabled=enabled,
            )
        self.save()
        logger.info("API 账号已添加: %s (%s, priority=%d)", name, base_url, priority)
        return True, f"账号 '{name}' 已添加 (priority={priority})"

    def remove(self, name: str) -> tuple[bool, str]:
        with self._lock:
            if name not in self._accounts:
                return False, f"账号 '{name}' 不存在"
            del self._accounts[name]
        self.save()
        logger.info("API 账号已删除: %s", name)
        return True, f"账号 '{name}' 已删除"

    def set_priority(self, name: str, priority: int) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            return False, f"账号 '{name}' 不存在"
        acc.priority = int(priority)
        self.save()
        return True, f"账号 '{name}' 优先级设为 {priority}（越小越优先）"

    def set_enabled(self, name: str, enabled: bool) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            return False, f"账号 '{name}' 不存在"
        acc.enabled = enabled
        if not enabled:
            acc.last_error = ""
        self.save()
        state = "启用" if enabled else "禁用"
        return True, f"账号 '{name}' 已{state}"

    def set_model(self, name: str, model: str) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            return False, f"账号 '{name}' 不存在"
        acc.model = model
        self.save()
        return True, f"账号 '{name}' 模型设为 {model}"

    def set_backup_key(self, name: str, backup_key: str) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            return False, f"账号 '{name}' 不存在"
        acc.backup_api_key = backup_key
        self.save()
        return True, f"账号 '{name}' 备用 Token 已设置"

    def set_base_url(self, name: str, base_url: str) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            return False, f"账号 '{name}' 不存在"
        acc.base_url = base_url
        self.save()
        return True, f"账号 '{name}' Base URL 设为 {base_url}"

    # === 查询 ===

    def enabled_accounts(self) -> list[APIAccount]:
        with self._lock:
            accounts = [a for _, a in sorted(self._accounts.items(),
                                             key=lambda kv: (kv[1].priority, kv[1].name))
                        if a.enabled]
        if not accounts:
            fb = self._env_fallback_account()
            if fb is not None:
                accounts = [fb]
        return accounts

    def count(self) -> int:
        with self._lock:
            n = len(self._accounts)
        if n == 0 and self._env_fallback_account() is not None:
            return 1
        return n

    # === 连通性测试 ===

    def test(self, name: str, timeout: int = 30) -> tuple[bool, str]:
        acc = self.get(name)
        if not acc:
            # 允许测试 .env 隐含主账号（名称固定为 main）
            fb = self._env_fallback_account()
            if fb is not None and fb.name == name:
                acc = fb
        if not acc:
            return False, f"账号 '{name}' 不存在"
        try:
            from .clients import OpenAIChat
            chat = OpenAIChat(api_key=acc.api_key, model=acc.model or "test",
                              api_url=acc.base_url or None, timeout=timeout,
                              max_tokens=4)
            chat.reset_conversation()
            reply = chat.send_message("ping")
            acc.last_error = ""
            self.save()
            return True, f"测试成功, 模型响应: {reply[:30]}"
        except Exception as e:
            acc.last_error = str(e)
            self.save()
            logger.error("API 账号 %s 测试失败: %s", name, e)
            return False, f"测试失败: {e}"


# ── 全局单例 ──

_instance: APIManager | None = None
_instance_lock = threading.Lock()


def get_api_manager() -> APIManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = APIManager()
        return _instance


def reset_api_manager() -> None:
    """测试/重载用：清空单例"""
    global _instance
    with _instance_lock:
        _instance = None


# ── FailoverChat: 按优先级逐个账号尝试，出错自动回退下一个 ──

class FailoverChat:
    """
    包装多个 OpenAIChat 实例，接口与 OpenAIChat 兼容。
    调用时按优先级顺序尝试，任一账号抛错则回退到下一个；
    全部失败才抛出最后一个异常。
    """

    def __init__(self, accounts: list[APIAccount], timeout: int = 300):
        from .clients import OpenAIChat
        self._accounts: list[OpenAIChat] = []
        self._account_names: list[str] = []
        for acc in sorted(accounts, key=lambda a: (a.priority, a.name)):
            try:
                self._accounts.append(OpenAIChat(
                    api_key=acc.api_key,
                    model=acc.model or "deepseek-v4-flash",
                    api_url=acc.base_url or None,
                    timeout=timeout,
                ))
                self._account_names.append(acc.name)
                # 备用 Token：主 Token 失效时优雅顶上（同端点，紧随主账号之后）
                if acc.backup_api_key:
                    self._accounts.append(OpenAIChat(
                        api_key=acc.backup_api_key,
                        model=acc.model or "deepseek-v4-flash",
                        api_url=acc.base_url or None,
                        timeout=timeout,
                    ))
                    self._account_names.append(f"{acc.name}(备用)")
            except Exception as e:
                logger.error("FailoverChat: 初始化账号 %s 失败: %s", acc.name, e)

        self.messages: list[dict] = []
        self.last_usage = None
        self.last_model = None
        self._last_tool_calls = None
        self._last_account = None
        self.fallback_log: list[str] = []

    def __repr__(self):
        return f"<FailoverChat accounts={self._account_names}>"

    @property
    def last_tool_calls(self) -> Optional[list[dict]]:
        return self._last_tool_calls

    @property
    def active_account(self) -> Optional[str]:
        return self._last_account

    def _try_all(self, **kwargs) -> str:
        errors: list[tuple[str, str]] = []
        for acc, chat in zip(self._account_names, self._accounts):
            try:
                # 同步历史到当前账号，从同一状态重试
                chat.messages = list(self.messages)
                reply = chat.continue_conversation(**kwargs)
                self.messages = list(chat.messages)
                self.last_usage = chat.last_usage
                self.last_model = chat.last_model
                self._last_tool_calls = chat.last_tool_calls
                self._last_account = acc
                if errors:
                    self.fallback_log.append(f"{time.strftime('%H:%M:%S')} 回退到 {acc}（此前失败: {errors[0][0]}）")
                    logger.info("FailoverChat: %s 失败后回退到 %s 成功", errors[0][0], acc)
                return reply
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                errors.append((acc, msg))
                logger.warning("FailoverChat: 账号 %s 调用失败: %s", acc, msg)
                continue
        err = errors[-1][1] if errors else "无可用账号"
        raise RuntimeError(f"所有 API 账号均失败: {err}")

    def send_message(self, message: str, tools: list[dict] = None,
                     tool_choice: str = "auto",
                     extra_body: Optional[dict] = None) -> str:
        if not message or not isinstance(message, str):
            raise ValueError("消息内容必须为非空字符串")
        self.messages.append({"role": "user", "content": message})
        return self._try_all(tools=tools, tool_choice=tool_choice, extra_body=extra_body)

    def continue_conversation(self, tools: list[dict] = None,
                              tool_choice: str = "auto",
                              extra_body: Optional[dict] = None) -> str:
        return self._try_all(tools=tools, tool_choice=tool_choice, extra_body=extra_body)

    def reset_conversation(self) -> None:
        self.messages.clear()
        self._last_tool_calls = None
        self._last_account = None
        for chat in self._accounts:
            chat.reset_conversation()

    def set_model(self, model: str) -> None:
        for chat in self._accounts:
            chat.set_model(model)

    def set_api_key(self, api_key: str) -> None:
        for chat in self._accounts:
            chat.set_api_key(api_key)

    def get_history(self) -> list[dict]:
        return self.messages.copy()


def build_failover_chat(priority_names: list[str] | None = None,
                        timeout: int = 300) -> FailoverChat | None:
    """
    根据全局账号管理器构建 FailoverChat（按优先级排序）。
    没有任何启用账号时返回 None（调用方回退到单账号模式）。
    """
    mgr = get_api_manager()
    accounts = mgr.enabled_accounts()
    if not accounts:
        return None
    if priority_names:
        order = {n: i for i, n in enumerate(priority_names)}
        accounts = sorted(accounts, key=lambda a: order.get(a.name, 999))
    return FailoverChat(accounts, timeout=timeout)


def load_failover_chat(model_override: str | None = None,
                       api_key_fallback: str | None = None,
                       api_url_fallback: str | None = None,
                       timeout: int = 300) -> FailoverChat | None:
    """构建 FailoverChat；无账号时返回 None（调用方回退单账号模式）。"""
    mgr = get_api_manager()
    accounts = mgr.enabled_accounts()
    if not accounts:
        # 允许用单账号兜底配置初始化一个 FailoverChat（便于统一入口）
        if api_key_fallback:
            from .clients import OpenAIChat
            fc = FailoverChat([])
            try:
                chat = OpenAIChat(api_key=api_key_fallback,
                                  model=model_override or "deepseek-v4-flash",
                                  api_url=api_url_fallback or None,
                                  timeout=timeout)
                fc._accounts.append(chat)
                fc._account_names.append("default")
                return fc
            except Exception as e:
                logger.warning("load_failover_chat 单账号兜底初始化失败: %s", e)
                return None
        return None
    if model_override:
        for a in accounts:
            if not a.model:
                a.model = model_override
    return FailoverChat(accounts, timeout=timeout)
