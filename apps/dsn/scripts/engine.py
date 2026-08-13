# scripts/engine.py
# ScriptEngine — 剧本解析/状态机/进度管理/条件求值

from __future__ import annotations

import hashlib
import logging
import re
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from apps.dsn.scripts.state import ScriptState

logger = logging.getLogger("ScriptEngine")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class KeyPoint:
    id: str
    type: str = "ai_action"
    description: str = ""
    condition: str = ""
    weight: float = 0.5
    completed: bool = False


@dataclass
class Transition:
    to: str
    condition: str = ""


@dataclass
class Chapter:
    id: str
    name: str = ""
    guidance: str = ""
    key_points: list[KeyPoint] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    is_ending: bool = False
    optional: bool = False
    entry_condition: str = ""


@dataclass
class Script:
    name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = "system"
    mode: str = "guide"
    trigger: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    chapters: list[Chapter] = field(default_factory=list)
    recording: dict = field(default_factory=dict)
    body: str = ""
    source_path: str = ""


class EvalContext:
    __slots__ = ("user_input", "ai_reply", "tool_name", "events",
                 "scores", "turn_count", "config")

    def __init__(self, user_input="", ai_reply="", tool_name="",
                 events=None, scores=None, turn_count=0, config=None):
        self.user_input = user_input
        self.ai_reply = ai_reply
        self.tool_name = tool_name
        self.events = events or {}
        self.scores = scores or {}
        self.turn_count = turn_count
        self.config = config


class ScriptEngine:
    def __init__(self, state: ScriptState | None = None):
        self._scripts: dict[str, Script] = {}
        self._state = state
        self._active_script: str = ""
        self._active_chapter: str = ""
        self._scores: dict[str, float] = {}
        self._turn_count: int = 0
        self._mode: str = ""
        self._user_id: int = 0
        self._allowed_keywords: set[str] = set()

    def scan_scripts(self, *directories: str) -> int:
        count = 0
        for d in directories:
            p = Path(d)
            if not p.exists():
                logger.warning("剧本目录不存在: %s", p)
                continue
            for f in sorted(p.rglob("*.md")):
                if f.stem.upper() == "README":
                    continue
                try:
                    self.load_script(str(f))
                    count += 1
                except Exception as e:
                    logger.error("加载剧本失败 %s: %s", f, e)
        logger.info("ScriptEngine 加载了 %d 个剧本", count)
        return count

    def load_script(self, path: str) -> str | None:
        text = Path(path).read_text(encoding="utf-8-sig")
        m = _FM_RE.match(text)
        if not m:
            logger.warning("剧本文件缺少 frontmatter: %s", path)
            return None

        data = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()

        name = data.get("name", "")
        if not name:
            logger.warning("剧本缺少 name: %s", path)
            return None

        chapters = []
        for ch_data in data.get("chapters", []):
            kps = []
            for kp_data in ch_data.get("key_points", []):
                kps.append(KeyPoint(
                    id=kp_data.get("id", ""),
                    type=kp_data.get("type", "ai_action"),
                    description=kp_data.get("description", ""),
                    condition=kp_data.get("condition", ""),
                    weight=kp_data.get("weight", 0.5),
                ))
            trans = []
            for t_data in ch_data.get("transitions", []):
                trans.append(Transition(
                    to=t_data.get("to", ""),
                    condition=t_data.get("condition", ""),
                ))
            chapters.append(Chapter(
                id=ch_data.get("id", ""),
                name=ch_data.get("name", ""),
                guidance=ch_data.get("guidance", ""),
                key_points=kps,
                transitions=trans,
                is_ending=ch_data.get("is_ending", False),
                optional=ch_data.get("optional", False),
                entry_condition=ch_data.get("entry_condition", ""),
            ))

        script = Script(
            name=name,
            display_name=data.get("display_name", name),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            author=data.get("author", "system"),
            mode=data.get("mode", "guide"),
            trigger=data.get("trigger", {}),
            settings=data.get("settings", {}),
            chapters=chapters,
            recording=data.get("recording", {}),
            body=body,
            source_path=path,
        )
        self._scripts[name] = script
        return name

    def get_script(self, name: str) -> Script | None:
        return self._scripts.get(name)

    def list_scripts(self) -> list[dict]:
        return [
            {"name": s.name, "display_name": s.display_name,
             "description": s.description, "mode": s.mode,
             "chapters": len(s.chapters)}
            for s in self._scripts.values()
        ]

    def start(self, script_id: str, user_id: int) -> bool:
        script = self._scripts.get(script_id)
        if not script:
            logger.warning("剧本不存在: %s", script_id)
            return False
        if not script.chapters:
            logger.warning("剧本无章节: %s", script_id)
            return False

        self._active_script = script_id
        self._active_chapter = script.chapters[0].id
        self._scores = {}
        self._turn_count = 0
        self._mode = script.mode
        self._user_id = user_id

        self._save_state()
        logger.info("剧本启动: %s (章节: %s)", script_id, self._active_chapter)
        return True

    def stop(self) -> None:
        if self.is_active() and self._state:
            self._state.clear(self._user_id)
        self._active_script = ""
        self._active_chapter = ""
        self._scores = {}
        self._turn_count = 0
        self._mode = ""
        self._user_id = 0
        logger.info("剧本已停止")

    def is_active(self) -> bool:
        return bool(self._active_script and self._active_chapter)

    def restore(self, user_id: int) -> bool:
        if not self._state:
            return False
        state = self._state.load(user_id)
        if not state or not state["active_script"]:
            return False
        self._active_script = state["active_script"]
        self._active_chapter = state["active_chapter"]
        self._scores = state["chapter_scores"]
        self._turn_count = state["turn_count"]
        self._user_id = user_id
        script = self._scripts.get(self._active_script)
        if script:
            self._mode = script.mode
        return True

    def get_chapter(self) -> Chapter | None:
        script = self._scripts.get(self._active_script)
        if not script:
            return None
        for ch in script.chapters:
            if ch.id == self._active_chapter:
                return ch
        return None

    def get_guidance(self) -> str:
        chapter = self.get_chapter()
        if not chapter:
            return ""
        script = self._scripts.get(self._active_script)
        parts = []
        if script and script.body:
            parts.append(script.body)
        if chapter.guidance:
            parts.append(chapter.guidance)
        return "\n\n".join(parts)

    def get_mode(self) -> str:
        return self._mode

    @property
    def settings(self) -> dict:
        script = self._scripts.get(self._active_script)
        return script.settings if script else {}

    @property
    def active_script(self) -> str:
        return self._active_script

    @property
    def active_chapter(self) -> str:
        return self._active_chapter

    @property
    def scores(self) -> dict[str, float]:
        return dict(self._scores)

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def increment_turn(self) -> None:
        self._turn_count += 1

    def check_key_points(self, user_input: str, ai_reply: str,
                         tool_name: str = "", events: dict = None) -> list[str]:
        chapter = self.get_chapter()
        if not chapter:
            return []

        ctx = EvalContext(
            user_input=user_input,
            ai_reply=ai_reply,
            tool_name=tool_name,
            events=events or {},
            scores=self._scores,
            turn_count=self._turn_count,
            config=_ConfigProxy(),
        )
        newly_completed = []
        for kp in chapter.key_points:
            if kp.id in self._scores:
                continue
            if self._eval_condition(kp.condition, ctx):
                self._scores[kp.id] = kp.weight
                newly_completed.append(kp.id)
                logger.info("关键点完成: %s (weight=%.2f)", kp.id, kp.weight)
        return newly_completed

    def advance(self) -> bool:
        chapter = self.get_chapter()
        if not chapter:
            return False
        if chapter.is_ending:
            return False

        for trans in chapter.transitions:
            if self._eval_transition(trans.condition):
                self._set_chapter(trans.to)
                logger.info("章节推进: %s → %s", chapter.id, trans.to)
                return True
        return False

    def force_advance(self, chapter_id: str) -> bool:
        script = self._scripts.get(self._active_script)
        if not script:
            return False
        valid_ids = {ch.id for ch in script.chapters}
        if chapter_id not in valid_ids:
            return False
        self._set_chapter(chapter_id)
        return True

    def is_complete(self) -> bool:
        chapter = self.get_chapter()
        return chapter is not None and chapter.is_ending

    def get_progress(self) -> dict:
        chapter = self.get_chapter()
        total_kp = len(chapter.key_points) if chapter else 0
        done_kp = sum(1 for kp_id in self._scores if self._scores.get(kp_id, 0) > 0)
        return {
            "script": self._active_script,
            "chapter": self._active_chapter,
            "chapter_name": chapter.name if chapter else "",
            "key_points_total": total_kp,
            "key_points_done": done_kp,
            "turn_count": self._turn_count,
            "is_ending": chapter.is_ending if chapter else False,
        }

    def get_trigger(self) -> dict:
        script = self._scripts.get(self._active_script)
        return script.trigger if script else {}

    def _set_chapter(self, chapter_id: str) -> None:
        self._active_chapter = chapter_id
        self._scores = {}
        self._save_state()

    def _save_state(self) -> None:
        if not self._state:
            return
        self._state.save(self._user_id, {
            "active_script": self._active_script,
            "active_chapter": self._active_chapter,
            "chapter_scores": self._scores,
            "flags": {},
            "turn_count": self._turn_count,
            "started_at": datetime.now().isoformat(),
        })

    def _eval_transition(self, condition: str) -> bool:
        if not condition or condition.strip() == "":
            return True
        return self._eval_condition(condition, EvalContext(scores=self._scores))

    def _eval_condition(self, condition: str, ctx: EvalContext) -> bool:
        if not condition or condition.strip() == "":
            return False
        condition = condition.strip()

        try:
            if condition == "true":
                return True
            if condition == "false":
                return False

            if " AND " in condition:
                parts = condition.split(" AND ")
                return all(self._eval_condition(p.strip(), ctx) for p in parts)
            if " OR " in condition:
                parts = condition.split(" OR ")
                return any(self._eval_condition(p.strip(), ctx) for p in parts)

            if ">=" in condition:
                left, right = condition.split(">=", 1)
                return self._eval_condition(left.strip(), ctx) >= float(right.strip())
            if "<=" in condition:
                left, right = condition.split("<=", 1)
                return self._eval_condition(left.strip(), ctx) <= float(right.strip())
            if "==" in condition:
                left, right = condition.split("==", 1)
                return self._eval_condition(left.strip(), ctx) == float(right.strip())
            if "!=" in condition:
                left, right = condition.split("!=", 1)
                return self._eval_condition(left.strip(), ctx) != right.strip().strip("'\"")
            if ">" in condition:
                left, right = condition.split(">", 1)
                return self._eval_condition(left.strip(), ctx) > float(right.strip())
            if "<" in condition:
                left, right = condition.split("<", 1)
                return self._eval_condition(left.strip(), ctx) < float(right.strip())

            m = re.match(r"^([a-zA-Z_]\w*)\(([^)]*)\)$", condition)
            if m:
                fn_name = m.group(1)
                raw_args = m.group(2)
                return self._call_fn(fn_name, raw_args, ctx)

            m = re.match(r"^config\.check\(['\"]([^'\"]+)['\"]\)$", condition)
            if m:
                key = m.group(1)
                try:
                    from apps.dsn.config import Config
                    val = getattr(Config, key.upper(), None) if hasattr(Config, key.upper()) else None
                    if val is None:
                        val = os.environ.get(key.upper(), "")
                    return bool(val)
                except Exception:
                    return False

            if condition in ctx.scores:
                return ctx.scores.get(condition, 0) > 0

            return False
        except Exception:
            logger.exception("条件求值失败: %s", condition)
            return False

    def _call_fn(self, name: str, raw_args: str, ctx: EvalContext) -> bool:
        args = raw_args.strip().strip("'\"") if raw_args else ""

        if name == "ai_mentions":
            return bool(args and args.lower() in ctx.ai_reply.lower())
        if name == "user_mentions":
            return bool(args and args.lower() in ctx.user_input.lower())
        if name == "ai_lists_presets":
            keywords = ["默认", "傲娇", "温柔", "预设", "自定义", "人格", "性格", "default", "tsundere", "gentle", "preset"]
            return any(kw in ctx.ai_reply for kw in keywords)
        if name == "user_chose_preset":
            keywords = ["默认", "傲娇", "温柔", "default", "tsundere", "gentle", "选", "这个"]
            return any(kw in ctx.user_input for kw in keywords)
        if name == "user_chose_custom":
            return "自定义" in ctx.user_input or "custom" in ctx.user_input.lower()
        if name == "user_affirms":
            keywords = ["好的", "好", "OK", "ok", "可以", "行", "是的", "对", "嗯", "是", "yes", "sure", "确定", "没问题"]
            return any(kw in ctx.user_input for kw in keywords)
        if name == "user_declines":
            keywords = ["不", "不要", "不用", "跳过", "取消", "no", "skip", "算了", "不需要"]
            return any(kw in ctx.user_input for kw in keywords)
        if name == "user_requests_action":
            keywords = ["试试", "试一下", "帮我", "用", "展示", "看看", "做", "执行"]
            return any(kw in ctx.user_input for kw in keywords)
        if name == "tool_used":
            return bool(args and args.lower() in ctx.tool_name.lower())
        if name == "config.check":
            try:
                from apps.dsn.config import Config
                val = getattr(Config, args.upper().replace(".", "_"), None)
                if val is None:
                    val = os.environ.get(args.upper(), "")
                return bool(val)
            except Exception:
                return False

        return False


class _ConfigProxy:
    def check(self, key: str) -> str:
        try:
            from apps.dsn.config import Config
            val = getattr(Config, key.upper(), None)
            return str(val) if val is not None else ""
        except Exception:
            return ""


def _compute_fingerprint(*items: str) -> str:
    h = hashlib.sha256()
    for item in items:
        h.update(item.encode("utf-8"))
    return h.hexdigest()[:16]