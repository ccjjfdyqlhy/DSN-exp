# prompt/impression.py
# ImpressionManager — 用户印象的查询/归纳/注入

import logging

logger = logging.getLogger("ImpressionManager")

IMPRESSION_CATEGORIES = [
    "兴趣", "工作", "技能", "习惯", "偏好", "项目", "设备", "社交", "其他",
]


class ImpressionManager:
    """
    用户印象管理器。

    职责:
      - 封装 chatdbmgr 的印象 CRUD
      - 生成自然语言印象摘要（注入 system prompt）
      - 判断是否需要触发全面了解协议
    """

    SSP_MIN_IMPRESSIONS = 5
    SSP_TRIGGER_AFFINITY = 1

    def __init__(self, db=None):
        self._db = db

    @property
    def has_db(self) -> bool:
        return self._db is not None

    def add(self, uid: int, category: str, content: str,
            confidence: float = 0.5, source: str = "inferred",
            evidence: str = "") -> int | None:
        if not self._db:
            return None
        try:
            impression_id = self._db.add_impression(
                uid, category, content, confidence, source, evidence,
            )
            logger.info("添加印象 uid=%d [%s] %s (置信度=%.2f)", uid, category, content[:60], confidence)
            return impression_id
        except Exception as e:
            logger.error("添加印象失败: %s", e)
            return None

    def update(self, impression_id: int, **fields) -> bool:
        if not self._db:
            return False
        return self._db.update_impression(impression_id, **fields)

    def delete(self, impression_id: int) -> bool:
        if not self._db:
            return False
        return self._db.delete_impression(impression_id)

    def query(self, uid: int, category: str = None,
              min_confidence: float = 0.5, limit: int = 50) -> list[dict]:
        if not self._db:
            return []
        return self._db.get_impressions(uid, category, min_confidence, limit)

    def count(self, uid: int) -> int:
        if not self._db:
            return 0
        return self._db.count_impressions(uid)

    def categories(self, uid: int) -> list[str]:
        if not self._db:
            return []
        return self._db.get_impression_categories(uid)

    def summary(self, uid: int) -> str:
        """生成对用户了解的简洁摘要（非 LLM 版本，纯数据库拼接）"""
        impressions = self.query(uid, min_confidence=0.3, limit=30)
        if not impressions:
            return "目前对用户还没有任何了解。"
        by_cat: dict[str, list[str]] = {}
        for imp in impressions:
            cat = imp.get("category", "其他")
            by_cat.setdefault(cat, []).append(imp["content"])
        lines = [f"对用户的了解（共 {len(impressions)} 条）："]
        for cat, items in by_cat.items():
            lines.append(f"  [{cat}]")
            for item in items[:5]:
                lines.append(f"    - {item}")
        return "\n".join(lines)

    def prompt_context(self, uid: int, top_n: int = 10) -> str:
        """生成注入 system prompt 的印象上下文"""
        impressions = self.query(uid, min_confidence=0.4, limit=top_n)
        if not impressions:
            return ""
        lines = ["## 你对用户的了解", ""]
        for imp in impressions:
            src = imp.get("source", "inferred")
            src_label = {"declared": "用户告知", "observed": "观察分析",
                         "inferred": "推理判断", "protocol": "深度扫描"}.get(src, src)
            lines.append(f"- [{imp['category']}] {imp['content']} (置信度: {imp['confidence']:.0%}, 来源: {src_label})")
        return "\n".join(lines)

    def should_propose_ssp(self, uid: int, affinity_level: int = 0) -> bool:
        """判断是否应主动提议全面了解协议"""
        imp_count = self.count(uid)
        if imp_count < self.SSP_MIN_IMPRESSIONS:
            return True
        if affinity_level <= self.SSP_TRIGGER_AFFINITY:
            return True
        return False

    def merge_similar(self, uid: int) -> int:
        """合并相似印象（简单版：同分类下完全相同的内容去重）"""
        all_imp = self.query(uid, min_confidence=0.0, limit=200)
        seen: dict[str, int] = {}
        merged = 0
        for imp in all_imp:
            key = f"{imp['category']}|{imp['content'].strip()}"
            if key in seen:
                older = seen[key]
                # 保留更高置信度的那条
                if imp["confidence"] > all_imp[all_imp.index(imp) - 1]["confidence"]:
                    self.delete(older)
                    seen[key] = imp["impression_id"]
                else:
                    self.delete(imp["impression_id"])
                merged += 1
            else:
                seen[key] = imp["impression_id"]
        if merged:
            logger.info("合并了 %d 条重复印象 uid=%d", merged, uid)
        return merged

    def load_impressions_from_text(self, uid: int, text: str, source: str = "protocol") -> int:
        """
        从 AI 生成的文本中解析印象条目并写入 DB。
        支持两种格式：
          IMPRESSION:类别:内容:置信度
          - [类别] 内容 (置信度: X%)
        """
        import re
        added = 0
        simple_pat = re.compile(r"IMPRESSION\s*:\s*(.+?)\s*:\s*(.+?)\s*:\s*(\d+)", re.IGNORECASE)
        bracket_pat = re.compile(r"-\s*\[(.+?)\]\s*(.+?)(?:\s*\(置信度[：:]\s*(\d+)%\))?\s*$")

        for line in text.split("\n"):
            match = simple_pat.search(line.strip()) or bracket_pat.search(line.strip())
            if not match:
                continue
            category = match.group(1).strip()
            content = match.group(2).strip()
            confidence_str = match.group(3) if match.lastindex >= 3 else None
            confidence = int(confidence_str) / 100.0 if confidence_str else 0.7
            if category not in IMPRESSION_CATEGORIES:
                category = "其他"
            if len(content) < 2:
                continue
            self.add(uid, category, content, confidence, source)
            added += 1
        if added:
            logger.info("从文本解析入库 %d 条印象 uid=%d", added, uid)
        return added