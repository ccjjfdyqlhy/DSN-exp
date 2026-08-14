# harness/policy/predictor.py
# DurationPredictor — 请求耗时预测策略（场景无关）。
#
# 从 dekacode predictor.py 提炼并引擎化（保持死区学习 / 衰减学习率 / 三段式误差映射 /
# 权重钳位的核心算法），扩展：
#   - 序列化可注入（state_dir），多会话共享预测模型
#   - add() 支持 batch（多条记录一次性学习）

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class DurationPredictor:
    """预测 API 请求耗时：elapsed = w1*nc_k + w2*out_k + w3*c_k + b。

    nc_k = non-cached input (k tokens)，out_k = output (k tokens)，
    c_k = 总输入 (k tokens，复杂度特征)。
    死区 5s：误差小于死区视为足够准，不更新权重（奖励）。
    学习率随样本数衰减；误差幅度三段式映射（线性 / 次线性 / 封顶）。
    """

    def __init__(self, w1: float = 0.0, w2: float = 0.0, w3: float = 0.0,
                 b: float = 2.0, n: int = 0, *, dead_zone: float = 5.0,
                 state_dir: Optional[str] = None):
        self.w1, self.w2, self.w3, self.b, self.n = w1, w2, w3, b, n
        self.dead_zone = dead_zone
        self.state_dir = Path(state_dir) if state_dir else None

    def predict(self, input_tokens: int, cache_hit_input: int, output_est: int,
                pending_tasks: int = 0, total_tasks: int = 0) -> float:
        non_cached = max(input_tokens - cache_hit_input, 0)
        if self.n < 2:
            return 60.0
        nc_k = non_cached / 1000
        out_k = output_est / 1000
        c_k = input_tokens / 1000
        result = self.w1 * nc_k + self.w2 * out_k + self.w3 * c_k + self.b
        if pending_tasks > 0 and total_tasks > 0:
            result *= 1.0 + (pending_tasks / total_tasks) * 0.5
        return max(1, min(300, result))

    def add(self, input_tokens: int, cache_hit_input: int, output_tokens: int,
            elapsed: float) -> None:
        non_cached = max(input_tokens - cache_hit_input, 0)
        nc_k = non_cached / 1000
        out_k = output_tokens / 1000
        c_k = input_tokens / 1000
        pred = self.w1 * nc_k + self.w2 * out_k + self.w3 * c_k + self.b
        error = elapsed - pred
        abs_error = abs(error)

        if abs_error < self.dead_zone:
            self.n += 1
            return

        lr = 0.008 / (1 + self.n * 0.005)
        excess = abs_error - self.dead_zone
        if excess < 15:
            scale = (excess / 15) * lr
        else:
            scale = lr * min(4, 1 + ((excess - 15) / 15) ** 0.5)
        update = scale if error > 0 else -scale

        self.w1 += update * nc_k
        self.w2 += update * out_k
        self.w3 += update * c_k
        self.b += update
        self.w1 = max(-2, min(10, self.w1))
        self.w2 = max(-2, min(10, self.w2))
        self.w3 = max(-2, min(10, self.w3))
        self.b = max(0.5, min(120, self.b))
        self.n += 1

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {"w1": self.w1, "w2": self.w2, "w3": self.w3,
                "b": self.b, "n": self.n}

    @classmethod
    def from_dict(cls, data: dict, **kw) -> "DurationPredictor":
        return cls(w1=data.get("w1", 0.0), w2=data.get("w2", 0.0),
                   w3=data.get("w3", 0.0), b=data.get("b", 2.0),
                   n=data.get("n", 0), **kw)

    def save(self, path: Optional[str] = None) -> None:
        p = Path(path) if path else (self.state_dir / "predictor.json"
                                     if self.state_dir else None)
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Optional[str] = None, **kw) -> "DurationPredictor":
        if path and Path(path).exists():
            try:
                return cls.from_dict(json.loads(Path(path).read_text()), **kw)
            except Exception:
                pass
        return cls(**kw)

    def __repr__(self) -> str:
        return (f"<DurationPredictor n={self.n} "
                f"w=({self.w1:.3f},{self.w2:.3f},{self.w3:.3f}) b={self.b:.1f}s>")
