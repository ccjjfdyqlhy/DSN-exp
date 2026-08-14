# harness/prompts/engine.py
# PromptEngine — 模块化提示词引擎（场景无关）。
#
# 从 dekacode prompt_engine 提炼并引擎化：
#   - 提示词片段（fragment）：Markdown 文件 + YAML 前注（title/description/enabled/order）
#   - 按 order 排序、enabled 过滤，模式化组装 system prompt
#   - {tools} / {member} / {names} 占位符渲染
#   - 与 harness 的 ToolRegistry 解耦：工具描述由调用方注入（render 函数）
#
# 创新点（对比 dekacode）：
#   - 片段可声明 required/context 标签，供策略层（SegmentedContextAssembler 等）引用
#   - 支持片段间依赖（depends_on），组装时自动补齐依赖片段

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_YAML_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


@dataclass
class PromptFragment:
    """一个提示词片段：文件路径 + 元数据 + 内容。"""

    file_path: str = ""
    title: str = ""
    description: str = ""
    enabled: bool = True
    order: int = 50
    content: str = ""
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return Path(self.file_path).stem

    @classmethod
    def from_file(cls, file_path: str) -> "PromptFragment":
        frag = cls(file_path=file_path)
        frag._parse()
        return frag

    def _parse(self) -> None:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except (FileNotFoundError, IOError):
            self.content = ""
            return
        m = _YAML_FRONT_RE.match(raw)
        if m:
            self.content = m.group(2).strip()
            for line in m.group(1).strip().split("\n"):
                self._parse_yaml_line(line.strip())
        else:
            self.content = raw.strip()

    def _parse_yaml_line(self, line: str) -> None:
        if ":" not in line:
            return
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "title":
            self.title = value
        elif key == "description":
            self.description = value
        elif key == "enabled":
            self.enabled = value.lower() in ("true", "yes", "1")
        elif key == "order":
            try:
                self.order = int(value)
            except ValueError:
                pass
        elif key == "tags":
            self.tags = [t.strip() for t in value.split(",") if t.strip()]
        elif key == "depends_on":
            self.depends_on = [d.strip() for d in value.split(",") if d.strip()]


class PromptEngine:
    """按目录加载片段并按 order/enabled 组装 system prompt。"""

    def __init__(self, prompts_dir: Optional[str] = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else None
        self.fragments: list[PromptFragment] = []
        self._loaded = False
        # 渲染器：({name} 占位符) → 文本；默认无
        self._renderers: dict[str, Callable[[], str]] = {}

    # ── 注册 ──

    def register_renderer(self, name: str, renderer: Callable[[], str]) -> "PromptEngine":
        """注册占位符渲染器（如 "tools" → 工具描述列表）。"""
        self._renderers[name] = renderer
        return self

    def load_all(self) -> None:
        self.fragments.clear()
        if self.prompts_dir is None or not self.prompts_dir.is_dir():
            return
        for fpath in sorted(self.prompts_dir.glob("*.md")):
            frag = PromptFragment.from_file(str(fpath))
            if frag.content:
                self.fragments.append(frag)
        self._loaded = True

    def add_fragment(self, title: str, content: str, *,
                     order: int = 50, enabled: bool = True,
                     tags: Optional[list[str]] = None,
                     depends_on: Optional[list[str]] = None) -> "PromptEngine":
        """编程式注册片段（无需文件）。"""
        frag = PromptFragment(
            title=title, content=content, order=order, enabled=enabled,
            tags=tags or [], depends_on=depends_on or [],
        )
        self.fragments.append(frag)
        self._loaded = True
        return self

    # ── 查询 ──

    def get_enabled(self, *, exclude_titles: Optional[set[str]] = None,
                    only_tags: Optional[list[str]] = None) -> list[PromptFragment]:
        if not self._loaded:
            self.load_all()
        frags = [f for f in self.fragments if f.enabled]
        if exclude_titles:
            frags = [f for f in frags if f.title not in exclude_titles]
        if only_tags:
            frags = [f for f in frags if any(t in f.tags for t in only_tags)]
        # 依赖补齐
        seen: set[str] = set()
        out: list[PromptFragment] = []
        stack = list(sorted(frags, key=lambda f: f.order))
        while stack:
            f = stack.pop(0)
            if f.title in seen:
                continue
            for dep in f.depends_on:
                dep_frag = self.get_fragment(dep)
                if dep_frag and dep_frag.title not in seen and dep_frag in frags:
                    out.append(dep_frag)
                    seen.add(dep_frag.title)
            if f.title not in seen:
                out.append(f)
                seen.add(f.title)
        return out

    def get_fragment(self, fragment_id: str) -> Optional[PromptFragment]:
        for f in self.fragments:
            if f.id == fragment_id or f.title == fragment_id:
                return f
        return None

    def reload(self) -> None:
        self._loaded = False
        self.load_all()

    # ── 组装 ──

    def build_system_prompt(self, *, exclude_titles: Optional[set[str]] = None,
                            only_tags: Optional[list[str]] = None) -> str:
        sections = []
        for frag in self.get_enabled(exclude_titles=exclude_titles,
                                     only_tags=only_tags):
            content = self._render(frag)
            if content:
                sections.append(content)
        return "\n\n".join(sections)

    def _render(self, frag: PromptFragment) -> str:
        content = frag.content
        for name, renderer in self._renderers.items():
            placeholder = "{" + name + "}"
            if placeholder in content:
                try:
                    content = content.replace(placeholder, renderer())
                except Exception:
                    continue
        return content

    def summary(self) -> str:
        parts = []
        for f in sorted(self.fragments, key=lambda x: x.order):
            flag = "✓" if f.enabled else "✗"
            parts.append(f"  [{flag}] {f.title} (order={f.order}, tags={f.tags})")
        return "\n".join(parts) if parts else "(无片段)"

    def __repr__(self) -> str:
        return f"<PromptEngine fragments={len(self.fragments)} dir={self.prompts_dir}>"
