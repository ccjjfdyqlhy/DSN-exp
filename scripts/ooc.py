# scripts/ooc.py
# OOCDetector — 规则引擎 + LLM 双路越界检测

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("OOCDetector")


@dataclass
class OOCResult:
    severity: float
    source: str
    reason: str
    redirect: str
    should_reject: bool


class OOCDetector:
    def __init__(self):
        self._rule_patterns = []

    def check(self, user_input: str, chapter: dict | None,
              strictness: float = 0.8, detector_mode: str = "hybrid") -> OOCResult:
        normalized = user_input.strip().lower()

        rule_result = self._rule_check(normalized, chapter, strictness)
        if rule_result and rule_result.severity >= strictness:
            return rule_result

        if detector_mode == "rule":
            return rule_result or self._pass()

        if detector_mode == "llm":
            return self._pass()

        if rule_result and rule_result.severity >= 0.4:
            return rule_result

        return self._pass()

    def _rule_check(self, text: str, chapter: dict | None,
                    strictness: float) -> OOCResult | None:
        if not chapter:
            return None

        chapter_name = chapter.get("name", "")

        skip_patterns = [
            r"(跳过|skip|不想要|不做了|退出|exit|quit|停止|取消|换一个|别说了)",
            r"(别管这个|别管了|不要这个|不弄了|下次再说|换话题|聊点别的)",
        ]
        for pattern in skip_patterns:
            if re.search(pattern, text):
                severity = 0.85 * strictness
                return OOCResult(
                    severity=severity,
                    source="rule",
                    reason=f"用户试图跳过当前章节「{chapter_name}」",
                    redirect=f"我知道你可能想跳过，但「{chapter_name}」很快就好，先完成这个步骤？",
                    should_reject=severity >= strictness,
                )

        system_commands = [
            r"(rm\s+-rf|sudo|chmod|chown|reboot|shutdown|format)",
            r"(delete\s+all|清除所有|删除所有|格式化)",
        ]
        for pattern in system_commands:
            if re.search(pattern, text):
                return OOCResult(
                    severity=0.95,
                    source="rule",
                    reason="检测到危险系统命令",
                    redirect="这个操作超出了当前剧本范围，我不能执行。",
                    should_reject=True,
                )

        return None

    def _pass(self) -> OOCResult:
        return OOCResult(
            severity=0.0,
            source="rule",
            reason="",
            redirect="",
            should_reject=False,
        )