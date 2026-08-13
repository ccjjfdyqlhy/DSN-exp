# harness/pipeline/outputs.py
# OutputRenderer — 输出渲染 SPI。
#
# 管线产出 ctx.outputs 中的各类产物（text/audio/image/...），
# 由实现将产物投递到具体通道（终端 / Web / 扬声器）。
#
# 语音只是众多渲染器之一；纯文本 Agent 可以用 TextRenderer 直出。

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional

from .base import Context


class OutputRenderer(ABC):
    """把管线产物渲染/投递到具体通道。"""

    name: str = ""

    @abstractmethod
    def render(self, ctx: Context) -> Any:
        """渲染 ctx.outputs 中的产物，返回投递结果（可被上层忽略）。"""

    async def render_stream(self, ctx: Context) -> AsyncGenerator[Any, None]:
        """流式渲染。默认把 render() 结果作为单帧 yield。"""
        result = self.render(ctx)
        yield result

    def __repr__(self) -> str:
        return f"<OutputRenderer {self.name}>"


class TextRenderer(OutputRenderer):
    """纯文本直出渲染器 — 把 reply 作为文本输出。"""

    name = "text"

    def render(self, ctx: Context) -> Any:
        return ctx.reply


class CompositeRenderer(OutputRenderer):
    """按产物类型分发的组合渲染器。"""

    def __init__(self, renderers: Optional[dict[str, OutputRenderer]] = None):
        self.renderers = renderers or {}

    def register(self, kind: str, renderer: OutputRenderer) -> "CompositeRenderer":
        self.renderers[kind] = renderer
        return self

    def render(self, ctx: Context) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for kind, value in ctx.outputs.items():
            renderer = self.renderers.get(kind)
            if renderer is not None:
                results[kind] = renderer.render(ctx)
            else:
                results[kind] = value
        if not ctx.outputs and ctx.reply:
            text = self.renderers.get("text")
            results["text"] = text.render(ctx) if text else ctx.reply
        return results
