# harness/tools/registry.py
# Tool registry with ownership tracking and a diff-snapshot execution path.
#
# The plain ToolRegistry has no notion of who registered a tool; engines need
# it to re-register agent / skill / mcp tools without touching the built-ins.
# Execution optionally snapshots the file a tool is about to touch and appends
# the unified diff to the tool result, so the model sees what changed without
# a second read.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..filediff import FileDiff, format_diff_for_model, make_file_diff, snapshot_file
from .base import Tool, ToolRegistry
from .context import resolve_path


def tool_result_text(output: Any) -> str:
    """The model-facing text for a tool result.

    Tool handlers return whatever fits the job -- a str, a dict, a list, a
    dataclass.  The engine only ever shows *text* to the model, and anything
    that was not a str used to collapse to an empty string, so a tool that
    answered ``{'delivered': True}`` looked to the model like it returned
    nothing at all.  Structured results are serialized as JSON instead.
    """
    if output is None:
        return ''
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)


@dataclass
class AnnotatedTool(Tool):
    """A harness Tool plus engine-facing metadata.

    read_only    the tool only inspects the world (allowlists, display)
    vision_only  the result carries an image: only offered to vision models
    snapshot     the ``path`` argument mutates a file: the registry snapshots
                 it around the call and appends the diff to the result
    """

    read_only: bool = False
    vision_only: bool = False
    snapshot: bool = False


class ManagedToolRegistry(ToolRegistry):
    """A ToolRegistry that remembers owners and snapshots writes."""

    def __init__(self) -> None:
        super().__init__()
        self._source_of: dict[str, str] = {}

    def register(self, tool: Tool, *, replace: bool = False,
                 source: str = 'builtin') -> Tool:
        registered = super().register(tool, replace=replace)
        self._source_of[tool.name] = source
        return registered

    def unregister(self, name: str) -> bool:
        removed = super().unregister(name)
        self._source_of.pop(name, None)
        return removed

    # ── source management ───────────────────────────────────
    def source_of(self, name: str) -> str:
        return self._source_of.get(name, 'builtin')

    def names_by_source(self, source: str) -> list[str]:
        return [name for name, own in self._source_of.items() if own == source]

    def unregister_source(self, source: str) -> list[str]:
        removed = [name for name, own in self._source_of.items() if own == source]
        for name in removed:
            super().unregister(name)
            del self._source_of[name]
        return removed

    def unregister_source_prefix(self, prefix: str) -> list[str]:
        removed = [name for name, own in self._source_of.items()
                   if own.startswith(prefix)]
        for name in removed:
            super().unregister(name)
            del self._source_of[name]
        return removed

    # ── schemas ─────────────────────────────────────────────
    def build_schema(self, names: list[str] | None = None, *,
                     vision: bool = True) -> list[dict]:
        """OpenAI schemas; vision_only tools drop out when vision is False."""
        selected = (
            [self._tools[n] for n in names if n in self._tools]
            if names is not None else self.tools()
        )
        if not vision:
            selected = [t for t in selected
                        if not (isinstance(t, AnnotatedTool) and t.vision_only)]
        return [t.to_openai_schema() for t in selected]

    # ── execution ───────────────────────────────────────────
    def execute(self, name: str, args: dict[str, Any]) -> tuple[str, FileDiff | None, bool]:
        """Run a tool and return (model_text, file_diff, error).

        The text follows the engine convention: failures start with 'Error: '
        and keep the model in charge of recovery.  Tools that declare
        ``snapshot`` get their file snapshotted around the call and the
        unified diff appended to the text.
        """
        tool = self.get(name)
        if tool is None:
            return f'Error: unknown tool: {name}', None, True
        # Snapshot the file the tool will actually touch: paths resolve against
        # the tool context's working directory, not the process cwd.  The diff
        # keeps the path the model asked for so prompts stay readable.
        wants_snapshot = getattr(tool, 'snapshot', False)
        raw_path = str(args.get('path', '')) if wants_snapshot else ''
        path = resolve_path(raw_path) if raw_path else ''
        before = snapshot_file(path) if path else None
        result = tool.run(**args)
        text = tool_result_text(result.output)
        if not result.success:
            if not text.startswith('Error:'):
                text = f'Error: {result.error or text or "tool failed"}'
        file_diff = None
        if before is not None and path:
            after = snapshot_file(path)
            file_diff = make_file_diff(raw_path, before, after)
        if file_diff is not None and not text.startswith('Error:'):
            text += format_diff_for_model(file_diff)
        return text, file_diff, text.startswith('Error:')
