# apps/dsn_ui/engine.py
"""DSN-UI 后端引擎：连接 harness.orchestrator、AgentCoordinator 与前端通信。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from apps.dsn_ui.agent import DSNUIAgentCoordinator
from harness.orchestrator import (
    ChatMessage,
    ChatResponse,
    LlamaServerConfig,
    ModelOrchestrator,
    ModelSourceType,
)

logger = logging.getLogger("DSNUIEngine")


class DSNUIEngine:
    def __init__(
        self,
        max_concurrent_slots: int = 2,
        on_topic_converged: Optional[Callable[[str, str], None]] = None,
    ):
        self.orchestrator = ModelOrchestrator.get_instance(max_concurrent_slots=max_concurrent_slots)
        self.workspace_root = Path(__file__).resolve().parent.parent.parent
        self.agent = DSNUIAgentCoordinator(
            orchestrator=self.orchestrator,
            workspace_root=self.workspace_root,
            on_topic_converged=on_topic_converged,
        )
        self._init_default_profiles()
        # 在 profile 注册完成后，重新套用用户保存过的启动参数覆盖，
        # 使「保存为预设」的设置跨重启持续生效。
        self._apply_saved_launch_overrides()

    # ── 启动参数覆盖持久化 ──

    def _launch_overrides_file(self) -> Path:
        """启动参数覆盖的持久化文件（按模型名索引）。"""
        d = self.workspace_root / "apps" / "dsn_ui" / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d / "model_launch_overrides.json"

    def load_launch_overrides(self) -> Dict[str, dict]:
        """读取全部已保存的启动参数覆盖。"""
        try:
            f = self._launch_overrides_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except Exception as e:  # noqa: BLE001
            logger.warning("读取启动参数覆盖失败: %s", e)
        return {}

    def save_launch_override(self, model_name: str, params: dict) -> dict:
        """保存某模型的启动参数覆盖（持久化 + 立即写入运行中配置）。

        这样「保存」后：立即生效（下一次加载使用新参数）且跨重启保留。
        """
        overrides = self.load_launch_overrides()
        overrides[model_name] = dict(params or {})
        f = self._launch_overrides_file()
        f.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("已持久化模型 %s 的启动参数覆盖: %s", model_name, sorted(params or {}))
        return overrides[model_name]

    def clear_launch_override(self, model_name: str) -> bool:
        """清除某模型的持久化覆盖（恢复 profile 原始参数）。"""
        overrides = self.load_launch_overrides()
        if model_name not in overrides:
            return False
        overrides.pop(model_name, None)
        f = self._launch_overrides_file()
        f.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("已清除模型 %s 的启动参数覆盖", model_name)
        return True

    def _apply_saved_launch_overrides(self) -> None:
        """启动时把所有保存过的覆盖套用到 orchestrator 配置上。"""
        overrides = self.load_launch_overrides()
        if not overrides:
            return
        applied = 0
        for model_name, params in overrides.items():
            try:
                changed = self.orchestrator.apply_launch_params(model_name, params)
                if changed:
                    applied += 1
            except KeyError:
                logger.info("覆盖对应的模型不存在，跳过: %s", model_name)
            except Exception as e:  # noqa: BLE001
                logger.warning("套用启动参数覆盖失败 %s: %s", model_name, e)
        if applied:
            logger.info("已套用 %d 个模型的启动参数覆盖", applied)

    def _init_default_profiles(self) -> None:
        """从 model_profiles 目录预加载模型定义至 Orchestrator。"""
        profiles_dir = self.workspace_root / "apps" / "dsn" / "model_profiles"
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
                        max_tokens=int(data.get("ctx_size", 128000)),
                    )
            except Exception as e:
                logger.warning("预加载 profile %s 失败: %s", yml_file.name, e)

        # 注册 API 模型（允许通过 OPENAI_CTX_SIZE / DSN_OPENAI_CTX_SIZE 指定上下文长度，默认 128000）
        api_key = os.getenv("OPENAI_API_KEY", "")
        openai_ctx = int(os.getenv("DSN_OPENAI_CTX_SIZE", os.getenv("OPENAI_CTX_SIZE", "128000")))
        if api_key:
            self.orchestrator.register_api_openai(
                name="deepseek-v4-flash",
                api_key=api_key,
                base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
                remote_model_name="deepseek-chat",
                max_tokens=openai_ctx,
            )
            self.orchestrator.register_api_openai(
                name="deepseek-v4-pro",
                api_key=api_key,
                base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
                remote_model_name="deepseek-reasoner",
                max_tokens=openai_ctx,
            )

        # ── Bonsai-demo 集成（可选）──
        # 自动发现 ~/Bonsai-demo 自带的自定义 llama.cpp 构建与多模态模型，
        # 注册为可调度的本地模型。目录不存在时静默跳过，不影响启动。
        try:
            from apps.dsn_ui.bonsai_integration import register_bonsai_models
            names = register_bonsai_models(self.orchestrator)
            if names:
                logger.info("Bonsai-demo 集成就绪，已注册 %d 个模型: %s", len(names), names)
        except Exception as e:  # noqa: BLE001
            logger.warning("Bonsai-demo 集成失败（忽略，不影响启动）: %s", e)
