# PersonalityMaterials — 通用性格蒸馏素材导入工具
# V3 引用通过实例属性 self._v3 注入

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("PersonalityMaterials")

# 模块级回退
_v3_ref = None


def set_v3_ref(v3):
    global _v3_ref
    _v3_ref = v3


class PersonalityImporter:
    def import_experience(
        self,
        source_path: str = "",
        text: str = "",
        source_label: str = "",
        card_id: str = "exa",
    ) -> dict:
        v3 = getattr(self, "_v3", None) or _v3_ref
        if v3 is None:
            return {"success": False, "error": "V3 系统不可用"}

        try:
            card = v3.get_card(card_id)
            if not card:
                return {"success": False, "error": f"角色卡 {card_id} 不存在"}

            resolved_path = None
            if source_path:
                sp = Path(source_path).resolve()
                if sp.exists() and sp.is_file():
                    content = sp.read_text(encoding="utf-8")
                    label = source_label or sp.stem
                    resolved_path = sp
                else:
                    return {"success": False, "error": f"源文件不存在: {source_path}"}
            elif text.strip():
                content = text.strip()
                label = source_label or "手动输入"
            else:
                return {"success": False, "error": "未提供文本来源"}

            # 复制源文件到 materials 目录持久化
            materials_dir = self._materials_dir(card_id)
            materials_dir.mkdir(parents=True, exist_ok=True)
            dest_name = self._dest_filename(label, resolved_path)
            dest_path = materials_dir / dest_name
            dest_path.write_text(content, encoding="utf-8")
            logger.info("素材文件已复制: %s → %s",
                         resolved_path.name if resolved_path else "(text)", dest_path.name)

            # 通过 V3 导入经历
            entry = v3.import_experience(card_id, content, label)
            if entry is None:
                return {"success": False, "error": "导入失败（V3 内部错误）"}

            return {
                "success": True,
                "source": label,
                "saved_to": str(dest_path),
                "original_length": len(content),
                "summary_length": len(entry.summary) if entry.summary else 0,
                "total_experiences": len(card.experiences) + 1,
            }

        except FileNotFoundError as e:
            return {"success": False, "error": f"文件不存在: {e}"}
        except Exception as e:
            logger.error("导入经历素材失败: %s", e)
            return {"success": False, "error": str(e)}

    def list_experiences(self, card_id: str = "exa") -> dict:
        v3 = getattr(self, "_v3", None) or _v3_ref
        if v3 is None:
            return {"success": False, "error": "V3 系统不可用"}

        try:
            card = v3.get_card(card_id)
            if not card:
                return {"success": False, "error": f"角色卡 {card_id} 不存在"}

            items = []
            for i, exp in enumerate(card.experiences):
                items.append({
                    "index": i + 1,
                    "source": exp.file or "文本输入",
                    "text_preview": (exp.text or exp.summary)[:120],
                    "summary_preview": exp.summary[:120] if exp.summary else "",
                    "original_length": exp.original_length,
                    "has_summary": bool(exp.summary),
                })

            return {
                "success": True,
                "count": len(items),
                "items": items,
                "card_id": card_id,
                "card_name": card.display_name or card.name,
            }

        except Exception as e:
            logger.error("列出经历素材失败: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def _materials_dir(card_id: str) -> Path:
        return Path(__file__).resolve().parent.parent.parent.parent.parent / \
               "character_cards" / "materials" / card_id

    @staticmethod
    def _dest_filename(label: str, source_path: Path | None) -> str:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in label)[:60]
        if source_path:
            ext = source_path.suffix
            if ext.lower() in (".txt", ".md", ".lrc"):
                return safe + ext
        return safe + ".txt"
