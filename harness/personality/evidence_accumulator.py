# prompt/personality_v3/evidence_accumulator.py
# 特质证据累积器 — 事件 → 维度证据 → 贝叶斯式缓慢更新 (可塑系数衰减)
# 早期可塑、后期固化，符合真实人格发展规律。定期 consolidate 写回蒸馏产物。

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from typing import TYPE_CHECKING
from .events import PerceptionRecord
from .traits import TRAIT_IDS
from .persistence import _get_conn_from_db

if TYPE_CHECKING:
    from .character_card import CharacterCard

logger = logging.getLogger("EvidenceAccumulator")

# 单条证据（medium 强度）指向的"观测值"偏移：obs = 0.5 + direction·SPREAD·intensity_factor
# 证据累积使 mu 渐近收敛到 obs，而非一路冲到 0/1 边界
EVIDENCE_OBS_SPREAD = 0.20
# 可塑时间尺度: α(n) = 1 / (1 + n / τ)，τ 越大越慢固化
PLASTICITY_TAU = 200.0
# 初始不确定性 σ0
SIGMA0 = 0.20
# 不确定性下限（σ 随证据收敛，最小 0.05）
SIGMA_MIN = 0.05
# 累积多少条证据后触发一次 consolidate（写回蒸馏产物）
CONSOLIDATE_EVERY = 50


class EvidenceAccumulator:
    """
    以角色卡为单位累积"经历证据"，缓慢演化 50 维特质向量。

    状态:
      - mu:      {card_id: {tid: float}}  演化后的特质均值
      - sigma:   {card_id: {tid: float}}  每维不确定性
      - counts:  {card_id: {tid: int}}    每维证据条数
    """

    def __init__(self, db=None):
        self._db = db
        self._mu: dict[str, dict[str, float]] = {}
        self._sigma: dict[str, dict[str, float]] = {}
        self._counts: dict[str, dict[str, int]] = {}
        self._pending: dict[str, int] = {}
        self._lock = threading.Lock()

    # === 持久化 ===

    def _get_conn(self):
        return _get_conn_from_db(self._db)

    def init_tables(self) -> None:
        if self._db is None:
            return
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS personality_evidence (
                    card_id TEXT PRIMARY KEY,
                    mu_json TEXT NOT NULL DEFAULT '{}',
                    sigma_json TEXT NOT NULL DEFAULT '{}',
                    counts_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
        except Exception as e:
            logger.error("创建证据表失败: %s", e)

    def load_card(self, card_id: str) -> dict | None:
        if self._db is None:
            return None
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT mu_json, sigma_json, counts_json FROM personality_evidence WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "mu": json.loads(row["mu_json"]),
                "sigma": json.loads(row["sigma_json"]),
                "counts": json.loads(row["counts_json"]),
            }
        except Exception as e:
            logger.error("加载证据失败 card=%s: %s", card_id, e)
            return None

    def flush_card(self, card_id: str) -> None:
        if self._db is None:
            return
        with self._lock:
            mu = self._mu.get(card_id)
            if mu is None:
                return
            sigma = self._sigma.get(card_id, {})
            counts = self._counts.get(card_id, {})
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO personality_evidence (card_id, mu_json, sigma_json, counts_json, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(card_id) DO UPDATE SET
                       mu_json = excluded.mu_json,
                       sigma_json = excluded.sigma_json,
                       counts_json = excluded.counts_json,
                       updated_at = datetime('now')""",
                (card_id, json.dumps(mu, ensure_ascii=False),
                 json.dumps(sigma, ensure_ascii=False),
                 json.dumps(counts, ensure_ascii=False)),
            )
            conn.commit()
        except Exception as e:
            logger.error("flush 证据失败 card=%s: %s", card_id, e)

    # === 证据累积 ===

    def seed(self, card_id: str, base_vector: dict[str, float]) -> None:
        """以蒸馏产物的 indicator_vector 作为演化起点（若尚未有历史）。"""
        with self._lock:
            if card_id in self._mu:
                return
            stored = self.load_card(card_id)
            if stored and stored.get("mu"):
                self._mu[card_id] = stored["mu"]
                self._sigma[card_id] = stored.get("sigma", {})
                self._counts[card_id] = stored.get("counts", {})
                return
            mu = {tid: float(base_vector.get(tid, 0.5)) for tid in TRAIT_IDS}
            self._mu[card_id] = mu
            self._sigma[card_id] = {tid: SIGMA0 for tid in TRAIT_IDS}
            self._counts[card_id] = {tid: 0 for tid in TRAIT_IDS}

    def add_evidence(self, card_id: str, perception: PerceptionRecord,
                     base_vector: dict[str, float]) -> None:
        self.seed(card_id, base_vector)
        evidence = perception.trait_evidence()
        if not evidence:
            return
        intensity = perception.intensity_factor

        with self._lock:
            mu = self._mu[card_id]
            sigma = self._sigma[card_id]
            counts = self._counts[card_id]

            for tid, direction in evidence.items():
                n = counts.get(tid, 0)
                alpha = 1.0 / (1.0 + n / PLASTICITY_TAU)
                cur = mu.get(tid, 0.5)
                # 证据指向的观测值（朝该方向偏移），mu 渐近收敛到它
                obs = max(0.0, min(1.0, 0.5 + direction * EVIDENCE_OBS_SPREAD * intensity))
                new_val = max(0.0, min(1.0, cur + alpha * (obs - cur)))
                mu[tid] = round(new_val, 4)

                # 证据越多不确定性越小 → 人格逐渐固化
                cur_sigma = sigma.get(tid, SIGMA0)
                sigma[tid] = round(max(SIGMA_MIN, cur_sigma * (1.0 - alpha * 0.5)), 4)
                counts[tid] = n + 1

            self._pending[card_id] = self._pending.get(card_id, 0) + 1

        logger.debug("EvidenceAccumulator: card=%s %s(n=%d) 已累积",
                     card_id, list(evidence.keys()), counts.get(next(iter(evidence), ""), 0))

    # === 查询 ===

    def get_mu(self, card_id: str) -> dict[str, float]:
        with self._lock:
            return dict(self._mu.get(card_id, {}))

    def get_plasticity(self, card_id: str) -> dict[str, float]:
        """每维可塑系数 α，越高代表该维仍易受新经历影响。"""
        with self._lock:
            counts = self._counts.get(card_id, {})
        return {tid: 1.0 / (1.0 + counts.get(tid, 0) / PLASTICITY_TAU) for tid in TRAIT_IDS}

    def get_total(self, card_id: str) -> int:
        with self._lock:
            counts = self._counts.get(card_id, {})
        return sum(counts.values())

    def should_consolidate(self, card_id: str) -> bool:
        with self._lock:
            return self._pending.get(card_id, 0) >= CONSOLIDATE_EVERY

    def consolidate(
        self,
        card_id: str,
        distilled_json_path: str | Path,
        card: CharacterCard | None = None,
    ) -> dict | None:
        """
        把演化后的 mu 写回 .distilled.json 的 indicator_vector。
        若 .distilled.json 不存在但提供了 card，则自动创建基线蒸馏文件并写入演化值。
        返回更新后的 indicator_vector；失败返回 None。
        """
        with self._lock:
            mu = self._mu.get(card_id)
            if mu is None:
                return None
        path = Path(distilled_json_path)
        if not path.exists():
            if card is not None:
                # 针对空白卡或尚未执行过大模型蒸馏的角色卡，初始化基础 .distilled.json
                from datetime import datetime as _dt, timezone as _tz
                base_data = {
                    "distillation_id": f"distill_{card_id}_evolved",
                    "card_id": card_id,
                    "version": 1,
                    "content_fingerprint": card.compute_fingerprint(),
                    "model_used": "bayesian_evolution",
                    "created_at": _dt.now(_tz.utc).isoformat(),
                    "foundation_description": card.natural_language.combined() if card.natural_language else "",
                    "behavioral_patterns": [],
                    "speech_patterns": [],
                    "emotional_model": {},
                    "relational_model": {},
                    "indicator_vector": {tid: float(mu.get(tid, 0.5)) for tid in TRAIT_IDS},
                    "trait_narrative": {},
                }
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(base_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    with self._lock:
                        self._pending[card_id] = 0
                    logger.info("EvidenceAccumulator: 自动创建并 consolidate 演化产物 card=%s", card_id)
                    return base_data["indicator_vector"]
                except Exception as e:
                    logger.error("创建蒸馏产物并 consolidate 失败 card=%s: %s", card_id, e)
                    return None
            else:
                logger.warning("consolidate: 蒸馏产物不存在 %s", path)
                return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            old_vec = data.get("indicator_vector", {})
            merged = {tid: float(mu.get(tid, old_vec.get(tid, 0.5))) for tid in TRAIT_IDS}
            data["indicator_vector"] = merged
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            with self._lock:
                self._pending[card_id] = 0
            logger.info("EvidenceAccumulator: 人格演化已 consolidate card=%s dims=%d", card_id, len(merged))
            return merged
        except Exception as e:
            logger.error("consolidate 失败 card=%s: %s", card_id, e)
            return None
