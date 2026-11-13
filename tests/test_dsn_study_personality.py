# -*- coding: utf-8 -*-
"""dsn_study 人格系统（阶段 2）—— 复用 harness/personality（PEV3）。

2026-11-08 之前 dsn_study 的 system prompt 只有 58 字身份描述，
**完全没有人格**：harness/personality 从未被 import，
PERSONALITY_V3_ENABLED / WORLD_ENABLED / NARRATIVE_ENABLED 三个开关
绑定了却无人读取。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


# ── 角色卡 ──

def test_study_tutor_card_exists_and_validates():
    """学习导师角色卡必须存在且通过 PEV3 校验。

    ⚠️ 位置变更（2026-11-11 重构）：``apps/dsn_study/character_cards/`` →
    ``apps/dsn_study/persona/cards/``。原因：旧目录被 ``.gitignore`` 忽略
    （``.gitignore:81-83,111``），意味着"小舟"这张卡**只存在于某一台机器上**；
    新目录是版本化的，卡进了 git。旧目录已归档到 ``persona/cards/_legacy/``。
    """
    from harness.personality.character_card import CharacterCard
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apps", "dsn_study", "persona", "cards", "study_tutor.yaml")
    assert os.path.isfile(path), "缺少学习导师角色卡: %s" % path
    card = CharacterCard.from_yaml_file(path)
    assert not card.validate(), card.validate()
    assert card.card_id == "study_tutor"
    assert card.natural_language.personality.strip()
    assert card.natural_language.behavior.strip()


def test_study_cards_dir_is_not_dsns():
    """**不能误用 dsn 的角色卡目录**。

    harness/personality 的 _find_default_cards_dir() 会去找
    apps/dsn/character_cards —— 那是 EXA「AI 同事」卡，不是学习导师。

    ⚠️ 断言改写（2026-11-11 重构）：卡片目录从 ``character_cards/`` 迁到了
    ``persona/cards/``（旧目录被 .gitignore 忽略，卡进不了版本库），
    所以这里改为断言**新目录**并且仍然要求显式指定默认卡。
    """
    from apps.dsn_study.config import Config
    assert getattr(Config, "PERSONALITY_ENABLED", False) is True
    from apps.dsn_study import boot
    import inspect
    src = inspect.getsource(boot.create_application)
    assert '"persona", "cards"' in src, "必须显式指定 study 自己的卡片目录"
    assert "PERSONALITY_DEFAULT_CARD" in src


# ── 装配 ──

def test_personality_assembled(study_app):
    p = study_app.personality
    assert p is not None, "人格系统未装配"
    assert p.enabled


def test_personality_uses_study_card(study_app):
    p = study_app.personality
    card_ids = [c.get("card_id") for c in p.list_cards()]
    assert "study_tutor" in card_ids, card_ids


def test_personality_prompt_in_system_prompt(study_app):
    """人格段落必须真的进 system prompt（而不是只存在但没用）。"""
    builder = study_app.prompt_builder
    builder.begin_turn(1, "")
    try:
        prompt = builder.build()
        assert "## 角色设定" in prompt, "人格段落未进入 system prompt"
        assert "小舟" in prompt, "人格内容不是学习导师卡"
    finally:
        builder.begin_turn(1, "")


def test_personality_api_routes_mounted(study_app):
    from apps.dsn_study import boot
    rules = {r.rule for r in boot.app.url_map.iter_rules()}
    for path in ("/api/personality/status", "/api/personality/current",
                 "/api/personality/list", "/api/personality/switch"):
        assert path in rules, "未挂载路由: %s" % path


def test_personality_status_api(study_app):
    from apps.dsn_study import boot
    client = boot.app.test_client()
    resp = client.get("/api/personality/status")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "uid" in data


def test_personality_list_api(study_app):
    from apps.dsn_study import boot
    client = boot.app.test_client()
    resp = client.get("/api/personality/list")
    assert resp.status_code == 200
    cards = resp.get_json().get("cards") or []
    assert any(c.get("card_id") == "study_tutor" for c in cards)


def test_personality_switch_requires_card_id(study_app):
    from apps.dsn_study import boot
    client = boot.app.test_client()
    resp = client.post("/api/personality/switch", json={})
    assert resp.status_code == 400


# ── 闭环 ──

class _StubClient:
    """最小桩客户端：够 AgentLoop 跑完一轮。"""

    def __init__(self, content="好的，这道题我们一步步看。"):
        self.content = content
        self.model = "stub"

    def invoke(self, messages, tools=None, **kwargs):
        from infra.orchestrator.base import ChatResponse
        return ChatResponse(content=self.content, model="stub")

    def stream(self, messages, tools=None, **kwargs):
        async def _gen():
            yield self.content
        return _gen()


def test_interaction_updates_affinity(study_app):
    """一轮对话后，亲密度与交互计数应当变化（人格闭环真的跑了）。

    ⚠️ 测试环境用**桩客户端**：conftest 会把 OPENAI_API_KEY 设成
    `sk-test-dummy-not-real`（CI 不应真调模型）。人格判定器在模型不可用时
    会自动回退启发式分类（personality_judge.py:157-159），闭环照样成立。
    """
    p = study_app.personality
    before = p.get_personality_status(1)
    b_aff = float(before.get("affinity_value") or 0.0)
    b_n = int(before.get("total_interactions") or 0)

    orig_client = study_app.agent.chat_client
    orig_judge = p._judge._chat
    study_app.agent.chat_client = _StubClient()
    p._judge.set_chat(None)          # → 启发式分类，不触网
    try:
        # 用启发式可识别的措辞（"太棒了"/"谢谢" → EVENT_THANKS，
        # 亲密度权重 +1.5）。无模型时人格判定器走启发式分类
        # （personality_judge.py:191），措辞决定事件类型。
        study_app.chat("太棒了，这道题终于搞懂了，谢谢！", user_id=1)
    finally:
        study_app.agent.chat_client = orig_client
        p._judge.set_chat(orig_judge)

    # 人格回写是**后台线程**（不阻塞回复），这里等它落地。
    import time
    deadline = time.time() + 10
    after = p.get_personality_status(1)
    while time.time() < deadline:
        if int(after.get("total_interactions") or 0) > b_n:
            break
        time.sleep(0.2)
        after = p.get_personality_status(1)

    a_aff = float(after.get("affinity_value") or 0.0)
    a_n = int(after.get("total_interactions") or 0)
    assert a_n > b_n, "交互计数未增加（analyze_interaction 没跑）"
    assert a_aff != b_aff, "亲密度未变化"


def test_personality_failure_degrades_gracefully(study_app):
    """人格系统故障不能让整轮对话失败。"""
    p = study_app.personality
    original = p.generate_personality_prompt
    orig_client = study_app.agent.chat_client

    def boom(uid):
        raise RuntimeError("人格服务挂了")

    p.generate_personality_prompt = boom
    study_app.agent.chat_client = _StubClient("好的。")
    try:
        reply = study_app.chat("随便说点什么", user_id=1)
        assert isinstance(reply, str) and reply
    finally:
        p.generate_personality_prompt = original
        study_app.agent.chat_client = orig_client
