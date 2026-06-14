# prompt/personality_v3/traits.py
# 50维量化人格指标体系 — 定义、分类、标签、边界描述

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class TraitDimension:
    tid: str
    name: str
    name_en: str
    category: str
    category_en: str
    low_label: str
    high_label: str
    low_desc: str
    high_desc: str

    def format(self, value: float) -> str:
        clamped = max(0.0, min(1.0, value))
        if clamped < 0.3:
            return f"{self.name}偏{self.low_label}"
        elif clamped < 0.45:
            return f"{self.name}略偏{self.low_label}"
        elif clamped < 0.55:
            return f"{self.name}中正"
        elif clamped < 0.7:
            return f"{self.name}略偏{self.high_label}"
        else:
            return f"{self.name}偏{self.high_label}"


CATEGORIES: dict[str, str] = {
    "A": "核心禀赋",
    "B": "情绪架构",
    "C": "认知风格",
    "D": "社交取向",
    "E": "语言风格",
    "F": "价值观与道德",
    "G": "关系动力学",
    "H": "行为驱动",
}

CATEGORIES_EN: dict[str, str] = {
    "A": "Core Disposition",
    "B": "Emotional Architecture",
    "C": "Cognitive Style",
    "D": "Social Orientation",
    "E": "Communication Style",
    "F": "Values & Morals",
    "G": "Relationship Dynamics",
    "H": "Behavioral Drivers",
}

ALL_DIMENSIONS: list[TraitDimension] = [
    # === A: 核心禀赋 ===
    TraitDimension("A1", "开放性", "Openness", "A", "Core Disposition",
                    "保守", "好奇", "保守、守旧、循规蹈矩", "好奇、开放、爱探索新事物"),
    TraitDimension("A2", "尽责性", "Conscientiousness", "A", "Core Disposition",
                    "散漫", "严谨", "散漫、随性、拖延", "严谨、自律、做事有条理"),
    TraitDimension("A3", "外向性", "Extraversion", "A", "Core Disposition",
                    "内向", "外向", "内向、安静、独处恢复精力", "外向、健谈、社交中获得能量"),
    TraitDimension("A4", "宜人性", "Agreeableness", "A", "Core Disposition",
                    "批判", "温和", "批判、怀疑、坚持己见", "温和、信任、愿意妥协"),
    TraitDimension("A5", "神经质", "Neuroticism", "A", "Core Disposition",
                    "稳定", "敏感", "情绪稳定、处变不惊", "敏感、易焦虑、情绪起伏大"),

    # === B: 情绪架构 ===
    TraitDimension("B1", "情绪丰富度", "Emotional Range", "B", "Emotional Architecture",
                    "单调", "丰富", "情感单调，只有少数几种情绪", "情感丰富，细微情绪变化多"),
    TraitDimension("B2", "情绪外显度", "Emotional Expressiveness", "B", "Emotional Architecture",
                    "内敛", "外显", "面无表情，内心激动外表平静", "喜怒哀乐全写在脸上"),
    TraitDimension("B3", "情绪恢复力", "Emotional Resilience", "B", "Emotional Architecture",
                    "脆弱", "坚韧", "受伤后久久不能平复", "迅速从负面情绪中恢复"),
    TraitDimension("B4", "共情能力", "Empathy", "B", "Emotional Architecture",
                    "冷漠", "敏感", "对他人感受无动于衷", "能深刻体会他人情绪"),
    TraitDimension("B5", "情绪感染力", "Emotional Contagion", "B", "Emotional Architecture",
                    "免疫", "易染", "情绪不被他人带动", "情绪极易被环境影响"),
    TraitDimension("B6", "主导情绪基调", "Dominant Mood Baseline", "B", "Emotional Architecture",
                    "悲观", "乐观", "悲观底色，习惯性看坏", "乐观底色，习惯性看好"),

    # === C: 认知风格 ===
    TraitDimension("C1", "理性-直觉", "Rational-Intuitive", "C", "Cognitive Style",
                    "理性", "直觉", "纯理性、逻辑优先、数据驱动", "凭直觉、感受优先"),
    TraitDimension("C2", "抽象-具体", "Abstract-Concrete", "C", "Cognitive Style",
                    "抽象", "具体", "抽象概括、理论思维", "关注具体细节、实操"),
    TraitDimension("C3", "分析-整体", "Analytic-Holistic", "C", "Cognitive Style",
                    "分析", "整体", "拆解问题、逐层分析", "全局视角、联系起来看"),
    TraitDimension("C4", "好奇心", "Curiosity", "C", "Cognitive Style",
                    "淡漠", "旺盛", "对未知漠不关心", "极度好奇、总想问为什么"),
    TraitDimension("C5", "创造力", "Creativity", "C", "Cognitive Style",
                    "常规", "创新", "循规蹈矩、复制已有方案", "天马行空、常有新奇想法"),
    TraitDimension("C6", "认知复杂度", "Cognitive Complexity", "C", "Cognitive Style",
                    "简单", "复杂", "非黑即白、二元思维", "能容纳矛盾、多角度思考"),

    # === D: 社交取向 ===
    TraitDimension("D1", "亲和需求", "Affiliation Need", "D", "Social Orientation",
                    "疏离", "渴望", "疏离、独处也不焦虑", "高度渴望亲密和归属"),
    TraitDimension("D2", "支配性", "Dominance", "D", "Social Orientation",
                    "顺从", "主导", "顺从、被动、跟随", "主导、控制局面、发号施令"),
    TraitDimension("D3", "社交主动性", "Social Initiative", "D", "Social Orientation",
                    "被动", "主动", "被动等待、从不主动搭话", "主动联系、热场、破冰"),
    TraitDimension("D4", "信任倾向", "Trust Propensity", "D", "Social Orientation",
                    "多疑", "信任", "疑心重、话不可全信", "真诚待人不设防"),
    TraitDimension("D5", "独立性", "Independence", "D", "Social Orientation",
                    "依附", "独立", "强烈依附、缺乏主见", "独当一面、自力更生"),
    TraitDimension("D6", "竞争性", "Competitiveness", "D", "Social Orientation",
                    "佛系", "好胜", "佛系、输赢无所谓", "处处要赢、不容落后"),
    TraitDimension("D7", "社交策略", "Social Strategy", "D", "Social Orientation",
                    "笨拙", "灵活", "孤僻、抗拒社交、读不懂氛围", "擅长读氛围、灵活应对"),
    TraitDimension("D8", "正式度", "Formality", "D", "Social Orientation",
                    "随性", "正经", "随性不拘、俚语无忌", "礼仪周正、正经八百"),

    # === E: 语言风格 ===
    TraitDimension("E1", "话量", "Verbosity", "E", "Communication Style",
                    "寡言", "健谈", "沉默寡言、惜字如金", "滔滔不绝、长篇大论"),
    TraitDimension("E2", "语速感", "Speech Pace", "E", "Communication Style",
                    "缓慢", "急促", "缓慢、字斟句酌", "语速快、想到什么说什么"),
    TraitDimension("E3", "幽默倾向", "Humor", "E", "Communication Style",
                    "严肃", "诙谐", "不苟言笑、一本正经", "风趣幽默、张口就来的笑点"),
    TraitDimension("E4", "讽刺倾向", "Sarcasm", "E", "Communication Style",
                    "真诚", "辛辣", "从不阴阳怪气", "冷嘲热讽是标配"),
    TraitDimension("E5", "直率度", "Directness", "E", "Communication Style",
                    "委婉", "直率", "拐弯抹角、委婉含蓄", "直言不讳、开门见山"),
    TraitDimension("E6", "诗意度", "Poetic Tendency", "E", "Communication Style",
                    "平实", "华丽", "大白话、毫不修饰", "出口成诗、修辞丰富"),
    TraitDimension("E7", "引用习惯", "Quotation Habit", "E", "Communication Style",
                    "自创", "引经", "不引用、全部自己说", "经常引用名言/典故/成语"),
    TraitDimension("E8", "语气词密度", "Particle Density", "E", "Communication Style",
                    "干脆", "软糯", "从不加呢吧啊哦", "呢嘛呀咯满天飞"),

    # === F: 价值观与道德 ===
    TraitDimension("F1", "正义感", "Justice Sensitivity", "F", "Values & Morals",
                    "淡漠", "强烈", "冷眼旁观、事不关己", "路见不平、嫉恶如仇"),
    TraitDimension("F2", "责任心", "Responsibility", "F", "Values & Morals",
                    "推诿", "担当", "出了事推卸、不揽活", "一诺千金、主动承责"),
    TraitDimension("F3", "忠诚度", "Loyalty", "F", "Values & Morals",
                    "善变", "忠贞", "墙头草、利益驱动", "忠贞不渝、从一而终"),
    TraitDimension("F4", "自尊水平", "Self-Esteem", "F", "Values & Morals",
                    "自卑", "自信", "自卑自轻、容易否定自己", "自信心强、不轻易怀疑自己"),
    TraitDimension("F5", "完美主义", "Perfectionism", "F", "Values & Morals",
                    "随性", "完美", "差不多就行、能跑就好", "事无巨细、吹毛求疵"),
    TraitDimension("F6", "道德弹性", "Moral Flexibility", "F", "Values & Morals",
                    "刚性", "弹性", "绝对道德、底线不可破", "视情况灵活调整准则"),

    # === G: 关系动力学 ===
    TraitDimension("G1", "亲密能力", "Intimacy Capacity", "G", "Relationship Dynamics",
                    "回避", "投入", "回避亲密、设防心重", "愿意投入、享受亲近"),
    TraitDimension("G2", "依赖倾向", "Dependency", "G", "Relationship Dynamics",
                    "自足", "依赖", "自给自足不靠别人", "凡事巴望别人帮忙"),
    TraitDimension("G3", "养育欲", "Nurturing Instinct", "G", "Relationship Dynamics",
                    "疏离", "呵护", "不愿照顾、嫌别人麻烦", "母性/父性爆棚、爱照顾人"),
    TraitDimension("G4", "嫉妒倾向", "Jealousy", "G", "Relationship Dynamics",
                    "大度", "善妒", "毫不在意、心胸开阔", "独占欲强、容易吃醋"),
    TraitDimension("G5", "依恋风格偏向", "Attachment Style Bias", "G", "Relationship Dynamics",
                    "安全", "焦虑", "安全型依恋、关系稳定", "焦虑/回避型依恋、关系动荡"),
    TraitDimension("G6", "情感投入速度", "Emotional Investment Rate", "G", "Relationship Dynamics",
                    "慢热", "速热", "日久生情、慢热", "一见如故、迅速敞开心扉"),

    # === H: 行为驱动 ===
    TraitDimension("H1", "主动性", "Proactivity", "H", "Behavioral Drivers",
                    "被动", "主动", "等人安排、从不自发", "主动出击、无事找事"),
    TraitDimension("H2", "耐心", "Patience", "H", "Behavioral Drivers",
                    "急躁", "耐心", "急性子、等不及", "超长待机、不急不躁"),
    TraitDimension("H3", "果断性", "Decisiveness", "H", "Behavioral Drivers",
                    "犹豫", "果断", "选择恐惧、纠结不断", "雷厉风行、当机立断"),
    TraitDimension("H4", "冒险倾向", "Risk-Taking", "H", "Behavioral Drivers",
                    "谨慎", "冒险", "安全第一、从不冒险", "极限追求者、赌性重"),
    TraitDimension("H5", "秩序感", "Orderliness", "H", "Behavioral Drivers",
                    "随性", "有序", "乱就乱、无所谓", "洁癖强迫症、必须整齐"),
]

TRAIT_MAP: dict[str, TraitDimension] = {t.tid: t for t in ALL_DIMENSIONS}

TRAIT_IDS = [t.tid for t in ALL_DIMENSIONS]

TRAIT_IDS_BY_CATEGORY: dict[str, list[str]] = {}
for t in ALL_DIMENSIONS:
    TRAIT_IDS_BY_CATEGORY.setdefault(t.category, []).append(t.tid)

DIMENSION_COUNT = len(ALL_DIMENSIONS)


def default_indicator_vector() -> dict[str, float]:
    return {t.tid: 0.5 for t in ALL_DIMENSIONS}


def clamp_vector(vec: dict[str, float]) -> dict[str, float]:
    return {k: max(0.0, min(1.0, v)) for k, v in vec.items()}


def vector_to_labels(vec: dict[str, float]) -> dict[str, str]:
    result = {}
    for t in ALL_DIMENSIONS:
        v = vec.get(t.tid, 0.5)
        result[t.tid] = t.format(v)
    return result


def deviant_dimensions(vec: dict[str, float], threshold: float = 0.15) -> list[dict]:
    """返回显著偏离中性 0.5 的维度描述"""
    deviants = []
    for t in ALL_DIMENSIONS:
        v = vec.get(t.tid, 0.5)
        deviation = abs(v - 0.5)
        if deviation >= threshold:
            deviants.append({
                "tid": t.tid,
                "name": t.name,
                "value": round(v, 2),
                "label": t.format(v),
                "deviation": round(deviation, 2),
            })
    deviants.sort(key=lambda d: d["deviation"], reverse=True)
    return deviants


def format_deviant_dimensions(vec: dict[str, float], top_n: int = 15) -> str:
    deviants = deviant_dimensions(vec, threshold=0.10)[:top_n]
    if not deviants:
        return "（无明显偏离中性的维度）"
    lines = []
    for d in deviants:
        direction = "→" if d["value"] > 0.5 else "←"
        lines.append(f"- {d['tid']} {d['name']}: {d['value']:.2f} {direction} {d['label']}")
    return "\n".join(lines)
