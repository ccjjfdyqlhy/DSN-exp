# prompt/personality_v3/character_card.py
# 角色卡数据结构 — YAML 读写、校验

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .traits import TRAIT_IDS, default_indicator_vector

logger = logging.getLogger("CharacterCard")


@dataclass
class CorpusEntry:
    etype: str
    source: str = ""
    content: str = ""

    def to_dict(self) -> dict:
        return {"type": self.etype, "source": self.source, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict) -> CorpusEntry:
        return cls(etype=data.get("type", ""), source=data.get("source", ""), content=data.get("content", ""))


@dataclass
class ExperienceEntry:
    text: str = ""
    file: str = ""
    summary: str = ""
    original_length: int = 0

    def to_dict(self) -> dict:
        return {"text": self.text, "file": self.file, "summary": self.summary, "original_length": self.original_length}

    @classmethod
    def from_dict(cls, data: dict) -> ExperienceEntry:
        return cls(
            text=data.get("text", ""),
            file=data.get("file", ""),
            summary=data.get("summary", ""),
            original_length=data.get("original_length", 0),
        )


@dataclass
class NaturalLanguage:
    personality: str = ""
    behavior: str = ""
    speech_style: str = ""
    values: str = ""
    emotional_traits: str = ""

    def combined(self) -> str:
        parts = []
        for key in ("personality", "behavior", "speech_style", "values", "emotional_traits"):
            v = getattr(self, key, "")
            if v:
                parts.append(v)
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "personality": self.personality,
            "behavior": self.behavior,
            "speech_style": self.speech_style,
            "values": self.values,
            "emotional_traits": self.emotional_traits,
        }

    @classmethod
    def from_dict(cls, data: dict) -> NaturalLanguage:
        return cls(
            personality=data.get("personality", ""),
            behavior=data.get("behavior", ""),
            speech_style=data.get("speech_style", ""),
            values=data.get("values", ""),
            emotional_traits=data.get("emotional_traits", ""),
        )


@dataclass
class DynamicConfig:
    seed: int = 42
    noise_amplitude: float = 0.12
    mood_volatility: float = 0.15
    temporal_drift_rate: float = 0.02
    response_inertia: float = 0.35
    environment_sensitivity: float = 0.3

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "noise_amplitude": self.noise_amplitude,
            "mood_volatility": self.mood_volatility,
            "temporal_drift_rate": self.temporal_drift_rate,
            "response_inertia": self.response_inertia,
            "environment_sensitivity": self.environment_sensitivity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DynamicConfig:
        return cls(
            seed=data.get("seed", 42),
            noise_amplitude=data.get("noise_amplitude", 0.12),
            mood_volatility=data.get("mood_volatility", 0.15),
            temporal_drift_rate=data.get("temporal_drift_rate", 0.02),
            response_inertia=data.get("response_inertia", 0.35),
            environment_sensitivity=data.get("environment_sensitivity", 0.3),
        )


@dataclass
class CharacterCard:
    card_id: str
    name: str = ""
    display_name: str = ""
    version: str = "1.0"
    description: str = ""
    author: str = "user"

    natural_language: NaturalLanguage = field(default_factory=NaturalLanguage)
    corpus: list[CorpusEntry] = field(default_factory=list)
    experiences: list[ExperienceEntry] = field(default_factory=list)
    dynamic_config: DynamicConfig = field(default_factory=DynamicConfig)
    manual_overrides: dict[str, float] = field(default_factory=dict)

    extends: str = ""

    created: str = ""
    updated: str = ""

    def __post_init__(self):
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()
        if not self.updated:
            self.updated = self.created

    def compute_fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(self.card_id.encode())
        h.update(self.natural_language.combined().encode())
        for c in self.corpus:
            h.update(c.content.encode())
        for e in self.experiences:
            h.update((e.text + e.summary).encode())
        return f"sha256:{h.hexdigest()[:40]}"

    def get_experiences_text(self) -> str:
        parts = []
        for exp in self.experiences:
            if exp.summary:
                parts.append(exp.summary)
            elif exp.text:
                parts.append(exp.text)
        return "\n\n".join(parts)

    def get_corpus_text(self) -> str:
        parts = []
        for c in self.corpus:
            header = f"[{c.etype}]"
            if c.source:
                header += f" ({c.source})"
            parts.append(f"{header}\n{c.content}")
        return "\n\n".join(parts)

    def get_adjusted_indicator_vector(self) -> dict[str, float]:
        base = default_indicator_vector()
        base.update(self.manual_overrides)
        return base

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "extends": self.extends,
            "natural_language": self.natural_language.to_dict(),
            "corpus": [c.to_dict() for c in self.corpus],
            "experiences": [e.to_dict() for e in self.experiences],
            "dynamic_config": self.dynamic_config.to_dict(),
            "manual_overrides": self.manual_overrides,
        }

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), allow_unicode=True, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict) -> CharacterCard:
        card = cls(
            card_id=data.get("card_id", ""),
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            author=data.get("author", "user"),
            natural_language=NaturalLanguage.from_dict(data.get("natural_language", {})),
            corpus=[CorpusEntry.from_dict(c) for c in data.get("corpus", [])],
            experiences=[ExperienceEntry.from_dict(e) for e in data.get("experiences", [])],
            dynamic_config=DynamicConfig.from_dict(data.get("dynamic_config", {})),
            manual_overrides=data.get("manual_overrides", {}),
            extends=data.get("extends", ""),
        )
        card.manual_overrides = {k: float(v) for k, v in card.manual_overrides.items() if k in TRAIT_IDS}
        return card

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> CharacterCard:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"角色卡文件不存在: {p}")
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("角色卡 YAML 格式错误：顶层必须是映射")
        return cls.from_dict(data)

    @classmethod
    def from_yaml_string(cls, content: str) -> CharacterCard:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError("角色卡 YAML 格式错误")
        return cls.from_dict(data)

    def validate(self) -> list[str]:
        errors = []
        if not self.card_id:
            errors.append("card_id 不能为空")
        if not self.name:
            errors.append("name 不能为空")
        if not self.natural_language.personality and not self.corpus:
            errors.append("自然语言描述或语料单至少需要一个有内容")
        if self.dynamic_config.noise_amplitude < 0 or self.dynamic_config.noise_amplitude > 1:
            errors.append("noise_amplitude 必须在 [0, 1]")
        return errors
