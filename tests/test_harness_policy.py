# tests/test_harness_policy.py
# 策略层（harness/policy/*）单元测试：路由 / 计量 / 预算 / 预测 / 保活。

from __future__ import annotations

import pytest

from harness.policy import (
    CacheWarmer,
    DurationPredictor,
    ModelConfig,
    ModelRouter,
    TokenBudget,
    TokenMeter,
)


# ── ModelRouter ──

def test_router_manual_override_wins():
    r = ModelRouter(ModelConfig())
    r.switch("pro")
    assert r.select() == "pro"
    r.switch("auto")
    assert r.select() == "flash"


def test_router_cheap_task_to_flash():
    r = ModelRouter(ModelConfig())
    assert r.select("search") == "flash"
    assert r.select("summary") == "flash"


def test_router_budget_pressure_downgrades():
    r = ModelRouter(ModelConfig())
    r.current_model = "pro"  # 默认档位为 pro，无手动覆盖
    assert r.select(budget_pressure=0.95) == "flash"


def test_router_get_model_config():
    r = ModelRouter(ModelConfig(flash_model="f", pro_model="p",
                                flash_api_key="fk", pro_api_key="pk"))
    cfg = r.get_model_config("pro")
    assert cfg["model"] == "p" and cfg["api_key"] == "pk"


# ── TokenMeter ──

def test_meter_records_cost():
    m = TokenMeter()
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "prompt_tokens_details": {"cached_tokens": 400},
    }
    rec = m.record(usage, model="flash", model_mode="flash")
    assert rec.cache_hit_input == 400
    assert rec.cache_miss_input == 600
    # flash: 0.6k*1.0 + 0.4k*0.02 + 0.5k*2.0 = $0.608/1000 级
    assert abs(rec.cost - (600 / 1e6 * 1.0 + 400 / 1e6 * 0.02 + 500 / 1e6 * 2.0)) < 1e-9
    assert rec.total_tokens == 1500
    assert m.total_tokens == 1500
    assert m.cache_hit_ratio == pytest.approx(400 / 1000)


def test_meter_summary():
    m = TokenMeter()
    m.record({"prompt_tokens": 1000, "completion_tokens": 0})
    assert "cost" in m.summary()
    assert "tokens" in m.summary()


# ── TokenBudget ──

def test_budget_pressure_and_exceed():
    meter = TokenMeter()
    events = []
    budget = TokenBudget(token_cap=500, on_exceed=lambda st: events.append(st.reason))
    budget.bind(meter)
    meter.record({"prompt_tokens": 400, "completion_tokens": 100})
    assert budget.pressure() == 1.0
    assert budget.check() is True
    assert budget.exceeded
    assert events  # on_exceed 触发一次


def test_budget_cost_cap():
    meter = TokenMeter()
    budget = TokenBudget(cost_cap=0.0001)
    budget.bind(meter)
    meter.record({"prompt_tokens": 1000, "completion_tokens": 100})
    assert budget.check() is True
    assert budget.exceeded


# ── DurationPredictor ──

def test_predictor_learns_and_converges():
    p = DurationPredictor(b=2.0, n=1)
    # 小样本时返回默认 60s（冷启动）
    assert p.predict(1000, 0, 100) == 60.0
    # 多次大误差样本（实际 45s）→ 权重学习，高估回调且向实际值靠近
    for _ in range(10):
        p.add(1000, 0, 100, 45.0)
    pred = p.predict(1000, 0, 100)
    assert pred < 60.0
    assert p.n >= 11
    # 序列化保留学习结果
    assert DurationPredictor.from_dict(p.to_dict()).w1 == p.w1


def test_predictor_serialization(tmp_path):
    p = DurationPredictor(w1=0.5, b=3.0, n=10)
    f = tmp_path / "pred.json"
    p.save(str(f))
    q = DurationPredictor.load(str(f))
    assert q.w1 == 0.5 and q.b == 3.0 and q.n == 10


# ── CacheWarmer ──

def test_warmer_keepalive_loop():
    import asyncio

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages, **kw):
            self.calls += 1
            return None

    client = FakeClient()
    warmer = CacheWarmer(client, lambda: [{"role": "user", "content": "."}],
                         interval=0.01)

    async def drive():
        warmer.start()
        await asyncio.sleep(0.05)
        await warmer.stop()
        return client.calls

    calls = asyncio.run(drive())
    assert calls >= 1
    assert warmer.keepalives >= 1
