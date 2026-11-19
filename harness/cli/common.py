# harness/cli/common.py
# CLI 各子命令共用的装配与输出helpers。
#
# 关键设计：CLI 默认**离线可用**。
# `aicf run` 不配任何 API key 也能跑（用桩模型），这样「90 秒上手」
# 和 CI 里的冒烟测试都不需要网络。

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness.tools.registry import ManagedToolRegistry
from harness.tools.standard import ToolDeps, install_standard_tools


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def out_json(payload: Any) -> None:
    """把结构化结果打到 stdout（机器可读）。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8')
    return target


@dataclass
class ToolCatalog:
    """一份工具目录（名字 + 契约）。"""

    registry: ManagedToolRegistry

    def entries(self) -> list[dict]:
        from harness.tools.guard import ToolGuard
        guard = ToolGuard()
        rows = []
        for tool in self.registry.tools():
            spec = guard.spec_for(tool)
            rows.append({
                'name': tool.name,
                'version': spec.version,
                'effect': spec.effect,
                'sandbox': spec.sandbox,
                'network': spec.network,
                'destructive': spec.destructive,
                'scopes': list(spec.scopes),
                'summary': spec.summary or tool.description,
            })
        rows.sort(key=lambda row: row['name'])
        return rows


def build_registry(include: Optional[list[str]] = None,
                   deps: Optional[ToolDeps] = None) -> ManagedToolRegistry:
    """建一个带标准工具集的注册表。

    这里**不挂 guard** —— CLI 的 `tool exec` 会显式挂，
    免得 `tool list` 之类的只读命令也被审批拦住。
    """
    registry = ManagedToolRegistry()
    install_standard_tools(registry, deps=deps or ToolDeps(), include=include)
    return registry


def build_model(*, model: str = '', base_url: str = '', api_key: str = '',
                prompt: str = ''):
    """建一个模型客户端。

    给了 base_url 或 api_key → 真的 OpenAI 兼容端点；
    否则 → 桩模型（离线可用）。
    """
    key = api_key or os.environ.get('OPENAI_API_KEY', '')
    if base_url or key:
        from infra.orchestrator.openai import OpenAICompatClient
        return OpenAICompatClient(
            model=model or 'gpt-4o-mini',
            base_url=base_url or os.environ.get('OPENAI_BASE_URL',
                                                'https://api.openai.com/v1'),
            api_key=key,
        )
    from infra.orchestrator.stub import StubChatClient
    from infra.orchestrator.base import ChatResponse

    def respond(messages, tools):
        # 桩模型：把用户输入回显出来，让 CLI 的离线演示有确定的结果。
        text = ''
        for message in reversed(messages or []):
            content = message.get('content') if isinstance(message, dict) else ''
            if content:
                text = str(content)
                break
        return ChatResponse(content=f'[stub] {text}')

    return StubChatClient(model=model or 'stub', respond=respond)


def security_mode(default: str = 'strict') -> str:
    """读 AICF_SECURITY_MODE 环境变量。

    strict（默认）= 策略 + 审批 + 沙箱 + 审计；
    legacy         = 直连（迁移期）。

    实现放在 harness.tools.guard —— 「安全模式有几个取值」只有一个答案。
    """
    from ..tools.guard import default_security_mode
    return default_security_mode(default)


__all__ = [
    'ToolCatalog',
    'build_model',
    'build_registry',
    'eprint',
    'out_json',
    'read_json',
    'security_mode',
    'write_json',
]
