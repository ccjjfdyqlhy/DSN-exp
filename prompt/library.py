# prompt/library.py
# MD 文件提示词库 — 解析带 YAML frontmatter 的 .md 文件，按分类索引

from __future__ import annotations

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("PromptLibrary")

# frontmatter: 以 --- 开头和结尾的 YAML 块
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class PromptEntry:
    name: str
    category: str          # core / capabilities / extensions / skills
    version: str = "1.0"
    description: str = ""
    tags: list = field(default_factory=list)
    priority: int = 50
    enabled: bool = True
    content: str = ""
    source_file: str = ""


class PromptLibrary:
    """
    MD 文件提示词库。

    职责:
    - 从文件系统加载 .md 文件
    - 按 category 索引
    - 启用 / 禁用 / 热重载
    - 按 category 聚合输出
    """

    def __init__(self):
        self._entries: dict[str, PromptEntry] = {}
        self._file_mtimes: dict[str, float] = {}

    @property
    def entries(self) -> list[PromptEntry]:
        return list(self._entries.values())

    # ---- 加载 ----

    def scan_and_load(self, *dirs: str) -> int:
        """扫描所有目录下的 .md/.yaml 文件，加载到库中"""
        count = 0
        for d in dirs:
            p = Path(d)
            if not p.exists():
                logger.warning("提示词目录不存在: %s", p)
                continue
            for f in sorted(p.rglob("*")):
                if f.suffix in (".md", ".yaml", ".yml"):
                    if f.stem.upper() == "README":
                        continue
                    try:
                        self.load_file(str(f))
                        count += 1
                    except Exception as e:
                        logger.error("加载提示词失败 %s: %s", f, e)
        logger.info("PromptLibrary 加载了 %d 个文件", count)
        return count

    def load_file(self, path: str) -> PromptEntry | None:
        """加载单个 .md 文件，覆盖同 name 已有条目（惰性加载内容）"""
        text = Path(path).read_text(encoding='utf-8-sig')

        m = _FM_RE.match(text)
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                logger.warning("YAML frontmatter 解析失败: %s，使用默认元数据", path)
                meta = {}
            content = m.group(2).strip()
        else:
            meta = {}
            content = text.strip()

        has_fm = m is not None
        entry = PromptEntry(
            name=meta.get("name", Path(path).stem),
            category=meta.get("category", "extensions"),
            version=str(meta.get("version", "1.0")),
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            priority=int(meta.get("priority", 50)),
            enabled=meta.get("enabled", has_fm),
            content=content,
            source_file=str(path),
        )

        self._entries[entry.name] = entry
        self._file_mtimes[str(path)] = Path(path).stat().st_mtime
        logger.debug("已加载提示词: %s [%s] pri=%d", entry.name, entry.category, entry.priority)
        return entry

    # ---- 查询 ----

    def get(self, name: str) -> PromptEntry | None:
        return self._entries.get(name)

    def get_content(self, name: str) -> str:
        e = self._entries.get(name)
        return e.content if e and e.enabled else ""

    def get_content_by_category(self, category: str) -> str:
        """获取某个 category 下全部启用条目，按 priority 排序拼接"""
        entries = sorted(
            (e for e in self._entries.values() if e.category == category and e.enabled),
            key=lambda e: e.priority,
        )
        return "\n\n".join(e.content for e in entries if e.content.strip())

    def list_entries(self) -> list[dict]:
        return [
            {
                "name": e.name,
                "category": e.category,
                "description": e.description,
                "version": e.version,
                "priority": e.priority,
                "enabled": e.enabled,
                "tags": e.tags,
                "source_file": e.source_file,
            }
            for e in sorted(self._entries.values(), key=lambda x: (x.category, x.priority))
        ]

    # ---- 管理 ----

    def enable(self, name: str) -> bool:
        e = self._entries.get(name)
        if not e:
            return False
        e.enabled = True
        logger.info("已启用提示词: %s", name)
        return True

    def disable(self, name: str) -> bool:
        e = self._entries.get(name)
        if not e:
            return False
        e.enabled = False
        logger.info("已禁用提示词: %s", name)
        return True

    def toggle(self, name: str) -> bool | None:
        """切换启用状态，返回新状态"""
        e = self._entries.get(name)
        if not e:
            return None
        e.enabled = not e.enabled
        logger.info("提示词 %s → %s", name, "启用" if e.enabled else "禁用")
        return e.enabled

    def reload(self, name: str) -> bool:
        """从磁盘热重载单个文件"""
        e = self._entries.get(name)
        if not e or not e.source_file:
            return False
        return self.load_file(e.source_file) is not None

    def reload_all(self) -> int:
        """热重载有变化的文件（基于 mtime）"""
        count = 0
        for e in list(self._entries.values()):
            if not e.source_file:
                continue
            path = e.source_file
            try:
                new_mtime = Path(path).stat().st_mtime
                if self._file_mtimes.get(path, 0) < new_mtime:
                    self.load_file(path)
                    count += 1
            except OSError:
                pass
        if count == 0:
            logger.debug("reload_all: 无文件变更")
        else:
            logger.info("reload_all: 重载了 %d 个变更文件", count)
        return count

    def unload(self, name: str) -> bool:
        if name in self._entries:
            del self._entries[name]
            return True
        return False
