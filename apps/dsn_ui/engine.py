# apps/dsn_ui/engine.py
"""DSN-UI 后端引擎：连接 harness.orchestrator 与前端通信。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.orchestrator import (
    ChatMessage,
    ChatResponse,
    LlamaServerConfig,
    ModelOrchestrator,
    ModelSourceType,
)

logger = logging.getLogger("DSNUIEngine")


class DSNUIEngine:
    def __init__(self, max_concurrent_slots: int = 2):
        self.orchestrator = ModelOrchestrator.get_instance(max_concurrent_slots=max_concurrent_slots)
        self._init_default_profiles()

    def _init_default_profiles(self) -> None:
        """从 model_profiles 目录预加载模型定义至 Orchestrator。"""
        profiles_dir = Path(__file__).resolve().parent.parent / "dsn" / "model_profiles"
        if not profiles_dir.exists():
            return

        import yaml
        for yml_file in sorted(profiles_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(yml_file.read_text(encoding="utf-8")) or {}
                name = data.get("model") or data.get("name") or yml_file.stem
                engine = data.get("engine", "lmstudio")
                priority = int(data.get("priority", 50))
                resident = bool(data.get("resident", False))
                immediate = bool(data.get("immediate", False))
                load_to = int(data.get("load_timeout", 180))
                req_to = int(data.get("request_timeout", 300))

                if engine in ("llama_cpp", "llamacpp"):
                    cfg_dict = data.get("llama_config") or {}
                    cfg = LlamaServerConfig.from_dict(cfg_dict)
                    self.orchestrator.register_local_llamacpp(
                        name=str(name),
                        config=cfg,
                        priority=priority,
                        resident=resident,
                        immediate=immediate,
                        load_timeout=load_to,
                        request_timeout=req_to,
                    )
                elif engine == "lmstudio":
                    self.orchestrator.register_api_lmstudio(
                        name=str(name),
                        base_url="http://localhost:4501",
                        remote_model_name=str(name),
                        priority=priority,
                        resident=resident,
                        immediate=immediate,
                        load_timeout=load_to,
                        request_timeout=req_to,
                    )
            except Exception as e:
                logger.warning("预加载 profile %s 失败: %s", yml_file.name, e)

        # 注册 DeepSeek 云端兜底模型
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            self.orchestrator.register_api_openai(
                name="deepseek-v4-flash",
                api_key=api_key,
                base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
                remote_model_name="deepseek-chat",
            )
            self.orchestrator.register_api_openai(
                name="deepseek-v4-pro",
                api_key=api_key,
                base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
                remote_model_name="deepseek-reasoner",
            )
