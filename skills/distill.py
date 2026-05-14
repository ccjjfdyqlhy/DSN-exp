# skills/distill.py
# 自动蒸馏引擎 — 从对话中挖掘模式，生成技能草案

from __future__ import annotations

import json
import logging
import re
import shutil
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("DistillationEngine")

# ── 模式挖掘 prompt ──

_ANALYSIS_PROMPT_TEMPLATE = """你是一个对话分析专家。请分析以下 AI 助手 (EXA) 与用户的对话记录，识别可以蒸馏为"技能"的重复模式。

## 什么是可蒸馏的模式？

1. **知识型模式**: 用户反复询问某类知识，AI 每次都用类似方式回答
2. **工作流模式**: 用户经常要求执行某个固定的多步骤流程
3. **工具使用模式**: AI 经常需要调用外部工具来完成某类任务
4. **偏好模式**: 用户对某类回答有明确的偏好

## 对话记录

{dialog_text}

## 输出要求

请以 JSON 数组格式输出发现的模式（仅出现频率 >= {min_freq} 次的模式）：

```json
[
  {{
    "name": "模式名称 (英文 snake_case)",
    "display_name": "中文显示名",
    "description": "详细描述",
    "category": "knowledge | workflow | tool_usage | preference",
    "occurrence_count": 出现次数,
    "example_exchanges": [
      {{"user": "用户说了什么", "assistant": "AI 怎么回答"}}
    ],
    "key_insights": ["关键知识点1", "关键知识点2"],
    "suggested_tools": []
  }}
]
```

如果没有值得蒸馏的模式，输出空数组 []。
请直接输出 JSON，不要有其他文字。"""

# ── 草案生成 prompt ──

_DRAFT_PROMPT_TEMPLATE = """你是一个技能设计师。根据以下从对话中提取的模式，生成一个完整的技能草案。

## 模式信息

名称: {name}
显示名: {display_name}
描述: {description}
分类: {category}
出现次数: {occurrence_count}
关键洞察: {insights}
建议工具: {tools}

## 典型对话示例

{examples}

## 输出要求

请生成以下文件内容，以 JSON 格式输出：

{{
  "skill.yaml": "技能元数据 YAML 内容",
  "prompts/instruction.md": "技能使用说明 (Markdown, 含 YAML frontmatter)",
  "prompts/patterns.md": "从对话中提取的知识/模式 (Markdown, 含 YAML frontmatter)",
  "prompts/examples.md": "使用示例 (Markdown, 含 YAML frontmatter)",
  "tools/main.py": "工具代码 (如需外部工具; 否则为 null)"
}}

### skill.yaml 格式:
```yaml
name: {name}
display_name: "{display_name}"
description: "{description}"
version: "0.1-draft"
author: "distilled"
source: "distilled"
enabled: false
status: "draft"
prompt_priority: 70
tags: [{category}]
tools: []
```

### prompts/*.md 格式:
每个 MD 文件需要 YAML frontmatter:
```
---
name: xxx
category: skills
priority: 70
---
```

请直接输出 JSON，不要有其他文字。"""


class DistillationEngine:
    """
    自动蒸馏引擎。

    从用户对话中提取模式，使用 LLM 分析后生成技能草案。
    草案保存到 skills/distilled/_drafts/，等待人工审核。
    """

    def __init__(
        self,
        db=None,                    # ChatDBManager
        skill_manager=None,         # SkillManager
        llm_client=None,            # LLM 客户端
        draft_dir: str = "skills/distilled/_drafts",
    ):
        self.db = db
        self.skill_manager = skill_manager
        self.llm = llm_client
        self.draft_dir = Path(draft_dir)
        self.draft_dir.mkdir(parents=True, exist_ok=True)

        self.min_conversations = 10
        self.min_pattern_frequency = 3
        self.max_draft_age_days = 7
        self.analysis_window_days = 30

    # ── 主流程 ──

    def run(self, user_id: int = None) -> dict[str, Any]:
        """执行一次完整蒸馏流程，返回报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "conversations_analyzed": 0,
            "patterns_found": 0,
            "drafts_created": 0,
            "drafts": [],
        }

        conversations = self._collect_conversations(user_id)
        report["conversations_analyzed"] = len(conversations)

        if len(conversations) < self.min_conversations:
            logger.info("对话数量不足 (%d < %d)，跳过蒸馏",
                        len(conversations), self.min_conversations)
            return report

        patterns = self._mine_patterns(conversations)
        report["patterns_found"] = len(patterns)

        if not patterns:
            logger.info("未发现可蒸馏的模式")
            return report

        for pattern in patterns:
            try:
                draft = self._generate_draft(pattern, conversations)
                if draft:
                    saved_path = self._save_draft(draft)
                    report["drafts_created"] += 1
                    report["drafts"].append({
                        "name": draft.get("_meta", {}).get("pattern", "unknown"),
                        "path": str(saved_path),
                        "pattern_count": pattern.get("occurrence_count", 0),
                    })
            except Exception as e:
                logger.error("生成草案失败: %s", e, exc_info=True)

        self._cleanup_old_drafts()
        return report

    # ── 对话收集 ──

    def _collect_conversations(self, user_id: int = None) -> list[dict]:
        if not self.db:
            return []

        cutoff = datetime.now() - timedelta(days=self.analysis_window_days)
        conversations: list[dict] = []

        try:
            chats = self.db.list_chats(user_id) if user_id else []
            for chat in chats:
                history = self.db.get_chat_history(
                    chat["user_id"] if "user_id" in chat else user_id,
                    chat["chat_id"]
                )
                for msg in history:
                    conversations.append({
                        "chat_id": chat.get("chat_id"),
                        "chat_name": chat.get("chat_name", ""),
                        "role": msg.get("role", ""),
                        "content": msg.get("content", ""),
                        "timestamp": msg.get("timestamp", ""),
                    })

            # 限制数量
            return conversations[-300:]
        except Exception as e:
            logger.error("收集对话失败: %s", e)
            return []

    # ── 模式挖掘 ──

    def _mine_patterns(self, conversations: list[dict]) -> list[dict]:
        if not self.llm:
            return []

        sampled = conversations[-200:]
        dialog_text = ""
        for msg in sampled:
            role = "用户" if msg["role"] == "user" else "EXA"
            content = msg["content"][:200]
            dialog_text += f"{role}: {content}\n"

        prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
            dialog_text=dialog_text,
            min_freq=self.min_pattern_frequency,
        )

        try:
            response = self.llm.send_message([
                {"role": "system", "content": prompt}
            ])
            return self._parse_patterns_response(response)
        except Exception as e:
            logger.error("模式挖掘 LLM 调用失败: %s", e)
            return []

    @staticmethod
    def _parse_patterns_response(response: str) -> list[dict]:
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if not json_match:
            return []
        try:
            patterns = json.loads(json_match.group())
            return patterns if isinstance(patterns, list) else []
        except json.JSONDecodeError:
            logger.warning("模式解析 JSON 失败")
            return []

    # ── 草案生成 ──

    def _generate_draft(self, pattern: dict, conversations: list[dict]) -> dict | None:
        if not self.llm:
            return None

        prompt = _DRAFT_PROMPT_TEMPLATE.format(
            name=pattern.get("name", "unknown"),
            display_name=pattern.get("display_name", ""),
            description=pattern.get("description", ""),
            category=pattern.get("category", ""),
            occurrence_count=pattern.get("occurrence_count", 0),
            insights=json.dumps(pattern.get("key_insights", []), ensure_ascii=False),
            tools=json.dumps(pattern.get("suggested_tools", []), ensure_ascii=False),
            examples=json.dumps(pattern.get("example_exchanges", []),
                                ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.send_message([
                {"role": "system", "content": prompt}
            ])
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return None
            draft = json.loads(json_match.group())
            draft["_meta"] = {
                "pattern": pattern.get("name"),
                "created_at": datetime.now().isoformat(),
                "source_conversations": len(conversations),
            }
            return draft
        except Exception as e:
            logger.error("生成草案失败: %s", e)
            return None

    # ── 文件操作 ──

    def _save_draft(self, draft: dict) -> Path:
        name = draft.get("_meta", {}).get("pattern", "")
        if not name:
            name = f"draft_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 从 skill.yaml 提取名称
        skill_yaml = draft.get("skill.yaml", "")
        yaml_match = re.search(r"name:\s*(\S+)", skill_yaml)
        if yaml_match:
            name = yaml_match.group(1)

        draft_path = self.draft_dir / name
        draft_path.mkdir(parents=True, exist_ok=True)

        for file_path, content in draft.items():
            if file_path.startswith("_"):
                continue
            if content is None:
                continue
            full_path = draft_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

        logger.info("草案已保存: %s", draft_path)
        return draft_path

    def _cleanup_old_drafts(self) -> None:
        if not self.draft_dir.exists():
            return
        cutoff = datetime.now() - timedelta(days=self.max_draft_age_days)
        for d in self.draft_dir.iterdir():
            if not d.is_dir():
                continue
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            if mtime < cutoff:
                shutil.rmtree(d)
                logger.info("清理过期草案: %s", d)

    # ── 草案管理 ──

    def list_drafts(self) -> list[dict]:
        drafts = []
        if not self.draft_dir.exists():
            return drafts
        for d in sorted(self.draft_dir.iterdir()):
            if not d.is_dir():
                continue
            yaml_file = d / "skill.yaml"
            if yaml_file.exists():
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                    drafts.append({
                        "name": data.get("name", d.name),
                        "display_name": data.get("display_name", ""),
                        "description": data.get("description", ""),
                        "version": data.get("version", ""),
                        "path": str(d),
                        "files": [f.name for f in d.rglob("*") if f.is_file()],
                    })
                except Exception:
                    drafts.append({
                        "name": d.name,
                        "path": str(d),
                        "error": "无法解析 skill.yaml",
                    })
        return drafts

    def approve_draft(self, name: str) -> bool:
        draft_dir = self.draft_dir / name
        if not draft_dir.exists():
            return False

        yaml_file = draft_dir / "skill.yaml"
        if yaml_file.exists():
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            data["status"] = "active"
            data["enabled"] = True
            version = data.get("version", "0.1-draft")
            data["version"] = version.replace("-draft", "")
            yaml_file.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False),
                encoding="utf-8"
            )

        # 移动到 distilled/
        target = Path("skills/distilled") / name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(draft_dir), str(target))

        if self.skill_manager:
            self.skill_manager.install(str(target))

        logger.info("草案已批准并激活: %s → %s", name, target)
        return True

    def reject_draft(self, name: str) -> bool:
        draft_dir = self.draft_dir / name
        if not draft_dir.exists():
            return False
        shutil.rmtree(draft_dir)
        logger.info("草案已拒绝并删除: %s", name)
        return True
