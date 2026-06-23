# subapp_loader.py
# Sub-App 配置加载器 — 解析 subapp.yaml → SubAppConfig

from __future__ import annotations

import logging
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("SubAppLoader")


@dataclass
class SubAppConfig:
    name: str = ""
    version: str = "1.0"
    description: str = ""
    author: str = "community"

    # 模型
    model_provider: str = "deepseek"
    model_name: str = "deepseek-v4-flash"
    model_temperature: float = 0.7
    model_max_tokens: int = 4096
    model_timeout: int = 300
    model_api_key: str = ""

    # 本地模型
    lmstudio_base_url: str = "http://localhost:4501"

    # 人格
    personality_preset: str = ""
    personality_file: str = ""

    # 插件控制
    plugins_enable: list[str] = field(default_factory=list)
    plugins_disable: list[str] = field(default_factory=list)

    # 技能
    skills_dirs: list[str] = field(default_factory=list)

    # 提示词
    prompts_dirs: list[str] = field(default_factory=list)

    # 运行模式
    mode: str = "interactive"  # scheduled | interactive | daemon

    # 定时调度
    schedule_cron: str = ""
    schedule_prompt: str = ""

    # 存储
    database_path: str = ""

    # Agent
    agent_active: bool = True
    agent_max_steps: int = 5
    agent_token_budget: int = 1000000
    agent_timeout: float = 120.0

    # 记忆
    memory_enabled: bool = True
    memory_summary_length: int = 100

    # 扩展
    extra: dict = field(default_factory=dict)

    @property
    def subapp_dir(self) -> str:
        return self.extra.get("subapp_dir", "")

    def resolve_path(self, relative: str) -> str:
        if Path(relative).is_absolute():
            return relative
        base = self.subapp_dir or "."
        return str(Path(base) / relative)


def load_subapp_config(subapp_path: str) -> SubAppConfig:
    """
    加载 subapp 配置。

    subapp_path 可以是:
    - 目录路径，包含 subapp.yaml
    - 直接指向 subapp.yaml 的路径
    """
    p = Path(subapp_path)
    if p.is_dir():
        yaml_path = p / "subapp.yaml"
    else:
        yaml_path = p
        p = p.parent

    if not yaml_path.exists():
        raise FileNotFoundError(f"subapp.yaml 未找到: {subapp_path}")

    with open(yaml_path, "r", encoding='utf-8-sig') as f:
        data = yaml.safe_load(f) or {}

    return _build_config(data, str(p))


def _build_config(data: dict, subapp_dir: str) -> SubAppConfig:
    meta = data.get("meta", data)

    model = data.get("model", {})
    plugins = data.get("plugins", {})
    personality = data.get("personality", {})
    schedule = data.get("schedule", {})
    agent = data.get("agent", {})

    config = SubAppConfig(
        name=meta.get("name", ""),
        version=meta.get("version", "1.0"),
        description=meta.get("description", ""),
        author=meta.get("author", "community"),
        model_provider=model.get("provider", "deepseek"),
        model_name=model.get("model", "deepseek-v4-flash"),
        model_temperature=model.get("temperature", 0.7),
        model_max_tokens=model.get("max_tokens", 4096),
        model_timeout=model.get("timeout", 300),
        model_api_key=model.get("api_key", ""),
        lmstudio_base_url=model.get("lmstudio_base_url", "http://localhost:4501"),
        personality_preset=personality.get("preset", ""),
        personality_file=personality.get("file", ""),
        plugins_enable=plugins.get("enable", []),
        plugins_disable=plugins.get("disable", []),
        skills_dirs=data.get("skills_dirs", ["skills"]),
        prompts_dirs=data.get("prompts_dirs", ["prompts"]),
        mode=data.get("mode", "interactive"),
        schedule_cron=schedule.get("cron", ""),
        schedule_prompt=schedule.get("prompt", ""),
        database_path=data.get("database_path", ""),
        agent_active=agent.get("active", True),
        agent_max_steps=agent.get("max_steps", 5),
            agent_token_budget=agent.get("token_budget", 1000000),
        agent_timeout=agent.get("timeout", 120.0),
        memory_enabled=data.get("memory_enabled", True),
        memory_summary_length=data.get("memory_summary_length", 100),
        extra={"subapp_dir": subapp_dir, "_raw": data},
    )

    logger.info("已加载 SubApp 配置: %s (%s)", config.name, subapp_dir)
    return config
