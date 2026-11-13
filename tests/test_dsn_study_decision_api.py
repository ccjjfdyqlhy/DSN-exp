"""dsn_study 的决策 REST API 测试。

要点：**决策不可用时返回 200 + degraded 标记**，而不是 5xx ——
调用方（技能、前端）不该因为决策这一项挂了就整条失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.dsn_study.api import decision as decision_api  # noqa: E402


class _Auth:
    def authenticate(self, request):
        return {"id": 1}


@pytest.fixture()
def client(monkeypatch):
    app = Flask(__name__)
    decision_api.init_decision_api(_Auth())
    app.register_blueprint(decision_api.decision_bp)

    import apps.dsn_study.models.decision_service as ds

    # 默认：决策服务不可用（未装配资源池）
    monkeypatch.setattr(ds, "get_decision_service", lambda pool=None: None)
    monkeypatch.setattr(ds, "decision_service_status",
                        lambda pool=None: {"enabled": True, "registered": False})
    with app.test_client() as c:
        yield c


def test_status_returns_200(client):
    r = client.get("/api/decision/status")
    assert r.status_code == 200
    assert r.get_json()["enabled"] is True


def test_probe_degrades_without_service(client):
    r = client.post("/api/decision/probe", json={"text": "今天好累", "is_voice": True})
    assert r.status_code == 200
    body = r.get_json()
    assert body["degraded"] is True


def test_classify_requires_labels(client):
    r = client.post("/api/decision/classify", json={"text": "题目"})
    assert r.status_code == 400


def test_classify_degrades_without_service(client):
    r = client.post("/api/decision/classify",
                    json={"text": "题目", "labels": ["选择题", "填空题"]})
    assert r.status_code == 200
    assert r.get_json()["degraded"] is True


def test_retrieval_degrades_without_service(client):
    r = client.post("/api/decision/retrieval",
                    json={"question": "2024 GDP?", "context": ""})
    assert r.status_code == 200
    assert r.get_json()["degraded"] is True


def test_stop_reports_not_registered(client, monkeypatch):
    import apps.dsn_study.models.resource_setup as rs

    monkeypatch.setattr(rs, "get_study_pool", lambda: None)
    r = client.post("/api/decision/stop")
    assert r.status_code == 404


def test_requires_auth():
    app = Flask(__name__)
    decision_api.init_decision_api(None)
    app.register_blueprint(decision_api.decision_bp)
    with app.test_client() as c:
        r = c.get("/api/decision/status")
    assert r.status_code == 503
