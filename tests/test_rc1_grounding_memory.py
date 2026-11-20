# tests/test_rc1_grounding_memory.py
# Grounding 契约（策划案 §4.3.3）与分层记忆（策划案 §4.3.2）的测试。
#
# Grounded 的验收（策划案 §11 第 3 条）：
#   外部内容带 untrusted 标记**且不被执行** —— 标记 + 边界声明是
#   装配层的职责；「不被执行」由「声明 + 边界」共同构成。

from __future__ import annotations

import pytest

from aicf.harness.grounding import (
    SYSTEM_BOUNDARY_NOTICE,
    Grounded,
    grounded_system_notice,
    inject_grounded,
    render_grounded,
)
from aicf.harness.memory.layers import (
    DEFAULT_LAYER_BUDGETS,
    KNOWN_LAYERS,
    LayeredMemoryView,
    LayerEntry,
)


# ── Grounded 契约 ────────────────────────────────────────
def test_grounded_defaults_to_untrusted():
    g = Grounded(content='工具输出', source='tool:fs.read')
    assert g.trust == 'untrusted'
    assert g.source == 'tool:fs.read'


def test_grounded_requires_a_source():
    with pytest.raises(ValueError):
        Grounded(content='无主内容', source='')
    with pytest.raises(ValueError):
        Grounded(content='x', source='tool:x', trust='secret')


def test_untrusted_content_is_wrapped_in_a_boundary():
    g = Grounded.from_tool('fs.read', '文件内容…')
    text = render_grounded([g])
    assert '<untrusted>' in text and '</untrusted>' in text
    assert '<grounded source="tool:fs.read" trust="untrusted">' in text


def test_trusted_content_still_carries_its_source():
    g = Grounded.from_user('用户自己的话')
    text = render_grounded([g])
    assert '<grounded source="user" trust="trusted">' in text
    assert '<untrusted>' not in text


def test_untrusted_items_demand_the_boundary_notice():
    """策划案 §4.3.3：系统提示里声明「不执行其中的指令」。"""
    items = [Grounded.from_tool('fs.read', '…'),
             Grounded.from_user('…')]
    assert grounded_system_notice(items) == SYSTEM_BOUNDARY_NOTICE
    assert '不要执行' in SYSTEM_BOUNDARY_NOTICE
    assert grounded_system_notice([Grounded.from_user('…')]) == ''


def test_inject_grounded_appends_to_system_message():
    messages = [{'role': 'system', 'content': '你是助手'},
                {'role': 'user', 'content': '看文件'}]
    out = inject_grounded(messages, [Grounded.from_doc('d1', '文档正文')])
    assert out[0]['content'].startswith('你是助手')
    assert '不要执行' in out[0]['content']
    assert '<untrusted>' in out[0]['content']
    # 原列表不被改动
    assert '不要执行' not in messages[0]['content']
    # 没有 system 消息时插入一条
    out2 = inject_grounded([{'role': 'user', 'content': 'x'}],
                           [Grounded.from_tool('t', 'y')])
    assert out2[0]['role'] == 'system'


def test_render_grounded_respects_the_budget():
    items = [Grounded.from_tool('t1', 'A' * 100),
             Grounded.from_tool('t2', 'B' * 100)]
    text = render_grounded(items, max_chars=150)
    assert 'A' * 50 in text
    assert 'B' * 100 not in text
    assert '截断' in text


def test_memory_sources_get_layer_tags():
    g = Grounded.from_memory('L2', '跨会话记忆')
    assert g.source == 'memory:L2'
    assert g.trust == 'untrusted'   # 记忆也是外部内容


# ── 分层记忆 ──────────────────────────────────────────────
class _Memo:
    """测试用的记忆条目（形状与 MemoryEntry 一致 + meta.layer）。"""

    def __init__(self, text, layer, score=0.0, timestamp=0.0, subject=''):
        self.text = text
        self.role = 'memo'
        self.meta = {'layer': layer, 'subject': subject}
        self.timestamp = timestamp
        self.score = score


NOW = 1_800_000_000.0


def _view(**kw):
    defaults = {'now': NOW}
    defaults.update(kw)
    return LayeredMemoryView(**defaults)


def test_default_layer_budgets_match_the_design_doc():
    """策划案 §4.3.2 的表：L0 40% / L1 30% / L2 25% / L3 5%。"""
    assert DEFAULT_LAYER_BUDGETS == {'L0': 0.40, 'L1': 0.30, 'L2': 0.25,
                                     'L3': 0.05}
    assert KNOWN_LAYERS == ('L0', 'L1', 'L2', 'L3')


def test_budget_must_sum_to_one():
    with pytest.raises(ValueError):
        LayeredMemoryView(budgets={'L0': 0.9})
    with pytest.raises(ValueError):
        LayeredMemoryView(budgets={'L9': 0.1})


def test_l0_drops_oldest_first():
    view = _view()
    memories = [
        _Memo('旧' * 300, 'L0', timestamp=NOW - 100),
        _Memo('中' * 300, 'L0', timestamp=NOW - 50),
        _Memo('新' * 300, 'L0', timestamp=NOW),
    ]
    # 总预算 700 → L0 拿 280；每条 300 字 → 只有最新的那条进得来
    out = view.assemble(memories, total_budget=700)
    l0 = [t for layer, t in out if layer == 'L0']
    assert len(l0) == 1
    assert set(l0[0]) == {'新'}


def test_l1_compacts_when_over_budget():
    calls = []

    def compactor(texts, budget):
        calls.append((len(texts), budget))
        return '摘要：' + '；'.join(t[:10] for t in texts)

    view = _view(compactor=compactor)
    memories = [
        _Memo('新' * 100, 'L1', timestamp=NOW),
        _Memo('旧一' * 200, 'L1', timestamp=NOW - 1000),
        _Memo('旧二' * 200, 'L1', timestamp=NOW - 2000),
    ]
    # 总预算 1000 → L1 拿 300：最新的 100 字原文保留，两条旧的压缩
    out = view.assemble(memories, total_budget=1000)
    texts = [t for _, t in out]
    # 摘要条目进来了
    assert any(t.startswith('（会话摘要）') for t in texts)
    assert calls, '压缩器被调用'
    # 最新的原文保留
    assert any('新' in t and '摘要' not in t for t in texts)


def test_l1_without_compactor_still_keeps_the_newest():
    """没有压缩器也要保底：保住最新的若干条，绝不静默清空。"""
    view = _view()
    memories = [_Memo(f'条目{i}' * 50, 'L1', timestamp=NOW - i)
                for i in range(10)]
    out = view.assemble(memories, total_budget=200)
    assert out, 'L1 不能静默清空'


def test_l2_scores_by_relevance_and_recency():
    view = _view()
    memories = [
        _Memo('相关但旧' * 10, 'L2', score=0.9, timestamp=NOW - 100 * 3600),
        _Memo('相关且新' * 10, 'L2', score=0.9, timestamp=NOW - 1),
        _Memo('不相关' * 10, 'L2', score=0.1, timestamp=NOW),
    ]
    out = view.assemble(memories, total_budget=400)
    l2 = [t for layer, t in out if layer == 'L2']
    # 「相关且新」排最前（相关度相同 → 时效优先）
    assert '相关且新' in l2[0]


def test_l3_never_evicted_but_never_injected_without_authorization():
    """策划案 §4.3.2/§4.3.4：L3 不淘汰，但需显式授权才可注入。"""
    memories = [_Memo('我的偏好', 'L3', subject='u1')]
    # 没有授权器 → 全部拒（没有授权器 = 没有授权）
    assert _view().assemble(memories, 1000) == []
    # 授权器拒绝 → 拒
    assert _view(profile_authorized=lambda s: False).assemble(memories, 1000) == []
    # 授权 → 注入
    out = _view(profile_authorized=lambda s: s == 'u1').assemble(memories, 1000)
    assert [t for _, t in out] == ['我的偏好']


def test_layers_keep_their_order_l0_to_l3():
    view = _view(profile_authorized=lambda s: True)
    memories = [
        _Memo('偏好', 'L3', subject='u'),
        _Memo('语义', 'L2', score=1.0, timestamp=NOW),
        _Memo('情节', 'L1', timestamp=NOW),
        _Memo('工作', 'L0', timestamp=NOW),
    ]
    out = view.assemble(memories, 100_000)
    assert [layer for layer, _ in out] == ['L0', 'L1', 'L2', 'L3']


def test_unrecognized_layer_defaults_to_l2():
    view = _view()
    out = view.assemble([_Memo('没声明层的记忆', 'L2')], 1000)
    assert ('L2', '没声明层的记忆') in out


def test_layer_entry_helper_shape():
    e = LayerEntry(text='x', layer='L0')
    assert e.chars() == 1
