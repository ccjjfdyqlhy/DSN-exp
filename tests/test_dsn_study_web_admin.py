# tests/test_dsn_study_web_admin.py
# 管理面板（迁移计划阶段 8）验收。
#
# 覆盖:
#   - 认证：infra/auth APIKeyManager（无 token 401 / 错 token 401 / 对 token 200）
#   - 数据源（新基座）：/status /resources /models /questions /reminders
#     /plugins /memory/users /memory/topics /persona/list /config /prompt
#     /plans /plan/today /checkin/calendar /logs
#   - 配置写入降级：/config/set 与 /config/undo 明确 501（计划 8.6 二选一）
#   - 面板页面可渲染
#   - 已删除端点确认（/vision/* /hibernate/* 等 404）
#
# ⚠️ 绝不在测试里调用 /api/admin/stop（会 os._exit 杀掉测试进程）。

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("admin_study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("admin_logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["ASR_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    os.environ["VISION_WARMUP"] = "false"
    os.environ.pop("WEB_ADMIN_API_KEY", None)   # 走自动生成密钥路径
    from apps.dsn_study import boot
    boot.create_application()
    return boot.app


@pytest.fixture()
def client(study_app):
    return study_app.test_client()


@pytest.fixture()
def key(study_app):
    return study_app.config["WEB_ADMIN_KEY"]


def _h(key):
    return {"X-Admin-Token": key}


# ── 认证 ──

def test_auth_required(client):
    rv = client.get("/api/admin/status")
    assert rv.status_code == 401
    rv = client.get("/api/admin/status", headers={"X-Admin-Token": "wrong"})
    assert rv.status_code == 401


def test_auth_via_query_param(client, key):
    """?admin_token= 保留（dsn 形状，为 <a>/媒体标签设计）。"""
    rv = client.get(f"/api/admin/status?admin_token={key}")
    assert rv.status_code == 200


def test_auto_generated_key_is_random(study_app):
    """未配置 WEB_ADMIN_API_KEY 时自动生成随机密钥（非固定值）。"""
    assert study_app.config["WEB_ADMIN_KEY"].startswith("adm_")


# ── 数据源 ──

def test_status(client, key):
    rv = client.get("/api/admin/status", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert d["app"] == "dsn_study"
    assert d["tools"] >= 40
    assert "questions_count" in d


def test_resources_from_infra_pool(client, key):
    rv = client.get("/api/admin/resources", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    # 资源池注册了 TTS/ASR 资源（列表可能为空 —— adopt 模式下仍应有条目或说明）
    assert "resources" in d and "slots" in d


def test_models_from_orchestrator(client, key):
    rv = client.get("/api/admin/models", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert "orchestrator" in d


def test_questions_stats(client, key):
    rv = client.get("/api/admin/questions", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert d["total"] >= 0
    assert isinstance(d["by_subject"], list)


def test_reminders(client, key):
    rv = client.get("/api/admin/reminders", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert isinstance(d["tasks"], list)


def test_plugins(client, key):
    rv = client.get("/api/admin/plugins", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert any("question_bank" in p for p in d["plugins"])
    assert any(t["key"].startswith("question_bank") for t in d["tools"])


def test_memory_users_and_chats(client, key):
    rv = client.get("/api/admin/memory/users", headers=_h(key))
    assert rv.get_json()["success"] is True
    rv = client.get("/api/admin/memory/chats/1", headers=_h(key))
    assert rv.get_json()["success"] is True


def test_memory_topics_or_note(client, key):
    rv = client.get("/api/admin/memory/topics/1", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    # TOPIC_ENABLED=false 时给出说明；=true 时返回列表
    assert "topics" in d


def test_persona_list(client, key):
    rv = client.get("/api/admin/persona/list", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    # PEV3 已装配 → 至少有 study_tutor 卡
    ids = [str(c.get("card_id", c.get("id", ""))) for c in d.get("cards", [])]
    assert any("study_tutor" in i for i in ids), ids


def test_config_readonly_and_masked(client, key):
    rv = client.get("/api/admin/config", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert d["writable"] is False
    # 敏感项脱敏
    assert d["config"].get("OPENAI_API_KEY") in ("***", "", "None")


def test_config_set_explicitly_unsupported(client, key):
    """计划 8.6：配置写入降级为「明确提示不支持」而不是假成功。"""
    rv = client.post("/api/admin/config/set", json={"key": "MAIN_MODEL_NAME",
                                                    "value": "x"},
                     headers=_h(key))
    assert rv.status_code == 501
    assert "不支持" in rv.get_json()["error"]
    rv = client.post("/api/admin/config/undo", headers=_h(key))
    assert rv.status_code == 501


def test_prompt_preview(client, key):
    rv = client.get("/api/admin/prompt?uid=1", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert len(d["prompt"]) > 100


def test_plans_and_today(client, key):
    rv = client.get("/api/admin/plans", headers=_h(key))
    assert rv.status_code == 200
    rv = client.get("/api/admin/plan/today", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True and "summary" in d


def test_checkin_calendar(client, key):
    rv = client.get("/api/admin/checkin/calendar", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert "calendar" in d and "streak" in d


def test_logs(client, key):
    rv = client.get("/api/admin/logs", headers=_h(key))
    d = rv.get_json()
    assert d["success"] is True
    assert isinstance(d["logs"], list)


# ── 面板页面 ──

def test_dashboard_page_renders(client, key):
    rv = client.get("/api/admin/")
    assert rv.status_code == 200
    assert b"dsn_study" in rv.data


# ── 已删除端点（计划 8.2） ──

def test_dropped_endpoints_are_404(client, key):
    for path in ("/api/admin/vision/streams",
                 "/api/admin/hibernate/check",
                 "/api/admin/hibernate/archive",
                 "/api/admin/pairing/generate",
                 "/api/admin/agents",
                 "/api/admin/detail/status",
                 "/api/admin/timer/toggle",
                 "/api/admin/checkin/video",
                 "/api/admin/exports"):
        rv = client.get(path, headers=_h(key))
        assert rv.status_code == 404, f"{path} 应已删除（got {rv.status_code}）"
