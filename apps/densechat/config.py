# config.py — DenseChat WebUI 的配置模型（更多配置键、模型/Provider 管理）。
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SENSITIVE_KEYS = {"api_key"}
BOOL_KEYS = {
    "thinking_collapsed_default",
    "enable_skills",
    "enable_theme",
}
INT_KEYS = {
    "port", "max_steps", "max_output_chars", "context_budget",
    "max_history_messages",
}


def _env_bool(value: str, default: bool = False) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class DenseChatConfig:
    # 服务
    host: str = "0.0.0.0"
    port: int = 8080
    project_root: str = "."
    max_steps: int = 12
    max_output_chars: int = 6000
    context_budget: int = 60000
    max_history_messages: int = 100
    # 单轮处理超时（秒）：防止模型/数据库无限挂起导致服务不可用
    turn_timeout: int = 300

    # Provider / 模型
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    provider_name: str = "DeepSeek"
    flash_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"
    openai_model: str = "gpt-4o-mini"
    model_mode: str = "flash"
    input_price_per_mtok: float = 0.1
    output_price_per_mtok: float = 2.0
    providers_file: str = ""
    active_provider: str = "default"

    # 技能 / 提示词
    skills_dir: str = ""
    prompts_dir: str = ""
    enable_skills: bool = True
    enable_theme: bool = True

    # UI
    thinking_collapsed_default: bool = True
    theme: str = "dark"

    # 持久化
    db_path: str = ""
    users_db_path: str = ""
    # 用户系统：false 时跳过登录直接进入（匿名模式）
    enable_users: bool = True

    def __post_init__(self):
        if not self.project_root:
            self.project_root = str(Path.cwd())
        self.project_root = str(Path(self.project_root).resolve())
        if not self.db_path:
            self.db_path = str(Path.home() / ".densechat" / "densechat.db")
        if not self.users_db_path:
            self.users_db_path = str(Path.home() / ".densechat" / "users.db")
        if not self.providers_file:
            self.providers_file = str(Path.home() / ".densechat" / "providers.json")
        if not self.skills_dir:
            self.skills_dir = str(Path(__file__).parent / "skills")
        if not self.prompts_dir:
            self.prompts_dir = str(Path(__file__).parent / "prompts")

    @classmethod
    def from_env(cls, project_root: str | None = None) -> "DenseChatConfig":
        root = Path(project_root or os.getenv("DENSECHAT_PROJECT") or os.getcwd()).resolve()
        load_dotenv(root / ".env")

        def get(*names: str, default: Any = None) -> Any:
            for n in names:
                v = os.getenv(n)
                if v is not None and v != "":
                    return v
            return default

        cfg = cls(
            host=get("DENSECHAT_HOST", "HOST", default="0.0.0.0"),
            port=int(get("DENSECHAT_PORT", "PORT", default="8080")),
            project_root=str(root),
            max_steps=int(get("DENSECHAT_MAX_STEPS", default="12")),
            max_output_chars=int(get("DENSECHAT_MAX_OUTPUT_CHARS", default="6000")),
            context_budget=int(get("DENSECHAT_CONTEXT_BUDGET", default="60000")),
            max_history_messages=int(get("DENSECHAT_MAX_HISTORY_MESSAGES", default="100")),
            api_key=get("DENSECHAT_API_KEY", "OPENAI_API_KEY", default="") or "",
            base_url=get("DENSECHAT_BASE_URL", "OPENAI_API_BASE",
                         default="https://api.deepseek.com/v1"),
            provider_name=get("DENSECHAT_PROVIDER_NAME", default="DeepSeek"),
            flash_model=get("DENSECHAT_FLASH_MODEL", "FLASH_MODEL",
                            default="deepseek-v4-flash"),
            pro_model=get("DENSECHAT_PRO_MODEL", "PRO_MODEL", default="deepseek-v4-pro"),
            openai_model=get("DENSECHAT_OPENAI_MODEL", "OPENAI_MODEL",
                             default="gpt-4o-mini"),
            model_mode=get("DENSECHAT_MODEL_MODE", default="flash"),
            input_price_per_mtok=float(get("DENSECHAT_INPUT_PRICE_PER_MTok", default="0.1")),
            output_price_per_mtok=float(get("DENSECHAT_OUTPUT_PRICE_PER_MTok", default="2.0")),
            providers_file=get("DENSECHAT_PROVIDERS_FILE", default=""),
            active_provider=get("DENSECHAT_ACTIVE_PROVIDER", default="default"),
            skills_dir=get("DENSECHAT_SKILLS_DIR", default=""),
            prompts_dir=get("DENSECHAT_PROMPTS_DIR", default=""),
            enable_skills=_env_bool(get("DENSECHAT_ENABLE_SKILLS", default="true"), True),
            enable_theme=_env_bool(get("DENSECHAT_ENABLE_THEME", default="true"), True),
            thinking_collapsed_default=_env_bool(
                get("THINKING_COLLAPSED_DEFAULT", default="true"), True),
            theme=get("DENSECHAT_THEME", default="dark"),
            db_path=get("DENSECHAT_DB", default=""),
            users_db_path=get("DENSECHAT_USERS_DB", default=""),
            enable_users=_env_bool(get("DENSECHAT_ENABLE_USERS", default="true"), True),
        )
        return cfg

    def to_dict(self, *, masked: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if masked:
            for key in SENSITIVE_KEYS:
                if key in d and d[key]:
                    v = str(d[key])
                    d[key] = ("*" * 4) + v[-4:] if len(v) > 8 else "*" * len(v)
        return d

    def update(self, key: str, value: Any) -> Any:
        if not hasattr(self, key):
            raise KeyError(f"未知配置键: {key}")
        old = getattr(self, key)
        target_type = type(old)
        if target_type is bool:
            new_val = value if isinstance(value, bool) else _env_bool(str(value), old)
        elif target_type is int:
            new_val = int(value)
        else:
            new_val = str(value)
        setattr(self, key, new_val)
        if key == "db_path" and not new_val:
            self.db_path = str(Path.home() / ".densechat" / "densechat.db")
        if key == "users_db_path" and not new_val:
            self.users_db_path = str(Path.home() / ".densechat" / "users.db")
        if key == "providers_file" and not new_val:
            self.providers_file = str(Path.home() / ".densechat" / "providers.json")
        if key == "skills_dir" and not new_val:
            self.skills_dir = str(Path(__file__).parent / "skills")
        if key == "prompts_dir" and not new_val:
            self.prompts_dir = str(Path(__file__).parent / "prompts")
        return new_val

    @staticmethod
    def write_env(project_root: str, key: str, value: Any) -> None:
        env_path = Path(project_root) / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_key = {
            "host": "DENSECHAT_HOST", "port": "DENSECHAT_PORT",
            "max_steps": "DENSECHAT_MAX_STEPS",
            "max_output_chars": "DENSECHAT_MAX_OUTPUT_CHARS",
            "context_budget": "DENSECHAT_CONTEXT_BUDGET",
            "max_history_messages": "DENSECHAT_MAX_HISTORY_MESSAGES",
            "api_key": "DENSECHAT_API_KEY", "base_url": "DENSECHAT_BASE_URL",
            "provider_name": "DENSECHAT_PROVIDER_NAME",
            "flash_model": "DENSECHAT_FLASH_MODEL",
            "pro_model": "DENSECHAT_PRO_MODEL",
            "openai_model": "DENSECHAT_OPENAI_MODEL",
            "model_mode": "DENSECHAT_MODEL_MODE",
            "input_price_per_mtok": "DENSECHAT_INPUT_PRICE_PER_MTok",
            "output_price_per_mtok": "DENSECHAT_OUTPUT_PRICE_PER_MTok",
            "providers_file": "DENSECHAT_PROVIDERS_FILE",
            "active_provider": "DENSECHAT_ACTIVE_PROVIDER",
            "skills_dir": "DENSECHAT_SKILLS_DIR",
            "prompts_dir": "DENSECHAT_PROMPTS_DIR",
            "enable_skills": "DENSECHAT_ENABLE_SKILLS",
            "enable_theme": "DENSECHAT_ENABLE_THEME",
            "thinking_collapsed_default": "THINKING_COLLAPSED_DEFAULT",
            "theme": "DENSECHAT_THEME",
            "db_path": "DENSECHAT_DB",
            "users_db_path": "DENSECHAT_USERS_DB",
            "enable_users": "DENSECHAT_ENABLE_USERS",
        }.get(key)
        if not env_key:
            return
        lines = env_path.read_text(encoding="utf-8").splitlines(True) if env_path.exists() else []
        found = False
        prefix = env_key + "="
        comment_prefix = "# " + env_key + "="
        for i, line in enumerate(lines):
            if line.strip().startswith(prefix) or line.strip().startswith(comment_prefix):
                lines[i] = f"{env_key}={value}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{env_key}={value}\n")
        env_path.write_text("".join(lines), encoding="utf-8")
