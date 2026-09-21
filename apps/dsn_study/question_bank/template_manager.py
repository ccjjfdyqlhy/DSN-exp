import json
import logging
import os
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("SubjectTemplateManager")

_TEMPLATES_DIR = Path(__file__).parent.parent / "skills" / "builtin" / "question_bank" / "templates"
_BUILTIN_TEMPLATES = ["3_subjects", "6_subjects", "9_subjects"]


class SubjectTemplateManager:

    def __init__(self, db):
        self._db = db

    def list_templates(self) -> list[dict]:
        templates = []
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT template_id, name, description, is_builtin, created_at "
            "FROM subject_templates ORDER BY is_builtin DESC, name"
        ).fetchall()
        for r in rows:
            templates.append({
                "template_id": r["template_id"],
                "name": r["name"],
                "description": r["description"],
                "is_builtin": bool(r["is_builtin"]),
                "created_at": r["created_at"],
            })
        return templates

    def get_template(self, template_name: str) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM subject_templates WHERE name = ?", (template_name,)
        ).fetchone()
        if not row:
            return None
        content = row["content"]
        try:
            content_obj = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            try:
                content_obj = yaml.safe_load(content) or {}
            except Exception:
                content_obj = {}
        return {
            "template_id": row["template_id"],
            "name": row["name"],
            "description": row["description"],
            "content": content_obj,
            "is_builtin": bool(row["is_builtin"]),
        }

    def import_template(self, template_path: str) -> dict:
        path = Path(template_path)
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {template_path}"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            return {"success": False, "error": f"解析模板失败: {e}"}
        name = data.get("name", path.stem)
        description = data.get("description", "")
        content = json.dumps(data, ensure_ascii=False)
        conn = self._db._get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO subject_templates (name, description, content, is_builtin) "
                "VALUES (?, ?, ?, 0)",
                (name, description, content),
            )
            conn.commit()
            logger.info("导入自定义模板: %s", name)
            return {"success": True, "name": name}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}

    def export_template(self, template_name: str, output_path: str) -> bool:
        template = self.get_template(template_name)
        if not template:
            return False
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                yaml.dump(template["content"], f, allow_unicode=True, default_flow_style=False)
            return True
        except Exception:
            return False

    def apply_template(self, template_name: str) -> dict:
        template = self.get_template(template_name)
        if not template:
            return {"success": False, "error": f"模板不存在: {template_name}"}
        content = template["content"]
        subjects = content.get("subjects", [])
        if not subjects:
            return {"success": False, "error": "模板中没有科目定义"}
        conn = self._db._get_connection()
        try:
            # 清空现有科目
            conn.execute("DELETE FROM subjects")
            for s in subjects:
                conn.execute(
                    "INSERT OR REPLACE INTO subjects (name, code, icon, typical_score, exam_duration) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        s.get("name", s.get("code", "")),
                        s.get("code", ""),
                        s.get("icon", ""),
                        s.get("typical_score", 100),
                        s.get("exam_duration", 120),
                    ),
                )
            # 清空现有题型
            qtypes = content.get("question_types", [])
            if qtypes:
                conn.execute("DELETE FROM question_types")
                for qt in qtypes:
                    subtypes = qt.get("subtypes", [qt.get("name", "")])
                    if not isinstance(subtypes, list):
                        subtypes = [subtypes]
                    for st in subtypes:
                        conn.execute(
                            "INSERT OR IGNORE INTO question_types (name, subtype, scoring_mode) "
                            "VALUES (?, ?, ?)",
                            (qt.get("name", ""), st, qt.get("scoring_mode", "exact")),
                        )
            conn.commit()
            logger.info("已应用模板: %s (%d 个科目)", template_name, len(subjects))
            return {"success": True, "subject_count": len(subjects)}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}

    def create_template(self, name: str, subjects: list[dict]) -> dict:
        if not subjects:
            return {"success": False, "error": "科目列表不能为空"}
        data = {
            "name": name,
            "description": f"用户自定义模板: {name}",
            "version": "1.0",
            "author": "user",
            "subjects": subjects,
            "question_types": [
                {"name": "选择题", "subtypes": ["单选", "多选"], "scoring_mode": "exact"},
                {"name": "填空题", "subtypes": ["填空"], "scoring_mode": "keyword"},
                {"name": "解答题", "subtypes": ["计算", "证明", "简答"], "scoring_mode": "llm"},
                {"name": "判断题", "subtypes": ["判断"], "scoring_mode": "exact"},
                {"name": "作文题", "subtypes": ["作文"], "scoring_mode": "llm"},
                {"name": "阅读理解", "subtypes": ["阅读"], "scoring_mode": "llm"},
            ],
        }
        content = json.dumps(data, ensure_ascii=False)
        conn = self._db._get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO subject_templates (name, description, content, is_builtin) "
                "VALUES (?, ?, ?, 0)",
                (name, data["description"], content),
            )
            conn.commit()
            # 保存到 custom 目录
            custom_dir = _TEMPLATES_DIR / "custom"
            custom_dir.mkdir(parents=True, exist_ok=True)
            output_path = custom_dir / f"{name}.yaml"
            with open(output_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            return {"success": True, "name": name}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}

    def delete_template(self, template_name: str) -> bool:
        if template_name in _BUILTIN_TEMPLATES:
            return False
        conn = self._db._get_connection()
        try:
            conn.execute(
                "DELETE FROM subject_templates WHERE name = ? AND is_builtin = 0",
                (template_name,),
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("删除模板失败: %s", e)
            conn.rollback()
            return False

    def has_subjects(self) -> bool:
        conn = self._db._get_connection()
        row = conn.execute("SELECT COUNT(*) as cnt FROM subjects").fetchone()
        return row["cnt"] > 0 if row else False

    def init_builtin_templates(self):
        conn = self._db._get_connection()
        try:
            for name in _BUILTIN_TEMPLATES:
                yaml_path = _TEMPLATES_DIR / f"{name}.yaml"
                if not yaml_path.exists():
                    continue
                row = conn.execute(
                    "SELECT 1 FROM subject_templates WHERE name = ?", (name,)
                ).fetchone()
                if row:
                    continue
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                content = json.dumps(data, ensure_ascii=False)
                conn.execute(
                    "INSERT INTO subject_templates (name, description, content, is_builtin) "
                    "VALUES (?, ?, ?, 1)",
                    (name, data.get("description", ""), content),
                )
            conn.commit()
            logger.info("内置科目模板初始化完成")
        except Exception as e:
            logger.error("初始化内置模板失败: %s", e)
            conn.rollback()

    def get_active_subjects(self) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT * FROM subjects WHERE is_active = 1 ORDER BY subject_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_subject_by_code(self, code: str) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM subjects WHERE code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None

    def get_question_types(self) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT * FROM question_types ORDER BY type_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_type_id(self, name: str, subtype: str = "") -> Optional[int]:
        conn = self._db._get_connection()
        if subtype:
            row = conn.execute(
                "SELECT type_id FROM question_types WHERE name = ? AND subtype = ?",
                (name, subtype),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT type_id FROM question_types WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()
        return row["type_id"] if row else None
