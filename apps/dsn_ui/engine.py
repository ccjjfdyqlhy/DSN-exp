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

    # ── 远程 API Provider 管理 ──

    def reload_api_providers(self) -> int:
        """把持久化的 provider 全部注册/重建到 orchestrator。

        每次增删改 provider 后调用，使其模型立即可被选用。
        返回成功注册的模型数量。
        """
        from apps.dsn_ui.api_providers import discovered_model_name

        registered = 0
        for provider in self.provider_store.list():
            if not provider.get("enabled", True):
                continue
            label = provider.get("label") or "Provider"
            protocol = provider.get("protocol") or "chat"
            base_url = provider.get("base_url") or ""
            api_key = provider.get("api_key") or ""
            # provider 可显式声明 vision 能力：远端模型的模态无法自动探测，
            # 由用户在设置页勾选（存进 extra_headers 供服务端读取）。
            headers = dict(provider.get("extra_headers") or {})
            if provider.get("vision"):
                headers["x-dsn-vision"] = "true"
            else:
                headers.pop("x-dsn-vision", None)

            for model in provider.get("models") or []:
                name = discovered_model_name(label, str(model))
                try:
                    self.orchestrator.register_api_openai(
                        name=name,
                        api_key=api_key,
                        base_url=base_url,
                        remote_model_name=str(model),
                        temperature=0.7,
                        max_tokens=int(provider.get("max_tokens") or 4096),
                        timeout=float(provider.get("timeout") or 300),
                        extra_headers=headers,
                        protocol=protocol,
                        provider_label=label,
                    )
                    registered += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("注册 API 模型 %s 失败: %s", name, e)
        if registered:
            logger.info("已注册 %d 个远程 API 模型", registered)
        return registered

    def unregister_provider_models(
        self, provider_id: str, *, snapshot: Optional[dict] = None
    ) -> int:
        """从 orchestrator 移除某 provider 的模型注册。

        Args:
            provider_id: provider 标识
            snapshot: 更新前的 provider 快照。**更新场景必须传入** ——
                否则 store 里已是新模型列表，旧模型名会残留成僵尸注册
                （表现为改名/换模型后列表里同时出现新旧两条）。

        返回移除的模型数量。
        """
        provider = snapshot or self.provider_store.get(provider_id)
        if not provider:
            return 0
        label = provider.get("label") or "Provider"

        # 传入 snapshot（= 更新前的状态）时，要把该 provider 的**全部**旧注册
        # 清掉，因为模型列表可能已变；调用方随后会用新配置重建。
        # 不传 snapshot（= 删除场景）时同样全清。
        # 因此这里不存在需要保留的条目 —— keep 恒为空。
        removed = 0
        with self.orchestrator._registry_lock:
            for name, spec in list(self.orchestrator._specs.items()):
                if getattr(spec, "provider_label", None) != label:
                    continue
                self.orchestrator._specs.pop(name, None)
                removed += 1
        if removed:
            logger.info("已移除 provider %s 的 %d 个模型注册", label, removed)
        return removed

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
                    # profile 可声明 vision: true 表示该模型支持图像输入
                    if data.get("vision"):
                        logger.info("profile %s 声明支持视觉输入", yml_file.name)
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
