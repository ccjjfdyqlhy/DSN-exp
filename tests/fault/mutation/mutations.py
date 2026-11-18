# tests/fault/mutation/mutations.py
# 变异清单 —— 「如果我们不小心删掉了 X，哪条测试会拦住」。
#
# 【这份清单是什么】
#   一张**测试套件的能力清单**。
#   读它就知道：托管运行时 / 审批 / 沙箱的哪一条保护一旦被拆掉，
#   故障注入层会不会立刻变红 —— 也就是「这些测试到底有没有牙齿」。
#
#   它比测试本身更有长期价值：测试会随着实现演进而改，
#   但「哪条保护由哪条用例守着」这个映射关系必须一直成立。
#
# 【每条变异必须写明「它保护的是什么」】
#   只写「monkeypatch 了哪个函数」是不够的 ——
#   半年后没人记得 `ResultCache.get_record` 是干嘛的。
#   所以每条都有 protects（人话的保护描述）与 detail（拆掉后会怎样）。
#
# 【为什么不把变异做成「进程内 monkeypatch 后直接跑 pytest」】
#   进程内改实现有泄漏风险：一个变异没恢复干净，会让**后面不相关的测试**
#   莫名其妙地红 —— 这种红极难排查。所以每条变异都在**独立子进程**里跑
#   （见 test_mutation_guards.py），变异工具永远不会污染测试套件。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: 一次「应用变异 → 检查是否真的生效」的动作。
#:
#: apply 返回一个 probe：probe() 为 True 表示「补丁确实打上了」。
#: 这一步是防**静默失效**的关键：如果哪天实现改了名，
#: monkeypatch 会打不上（patch 一个不存在的属性只是新建了一个属性），
#: 工具就会「什么都没抓到」并报告「全部通过」——
#: 那是这个工具最危险的失效模式。
Patch = Callable[[], Callable[[], bool]]


@dataclass(frozen=True)
class Mutation:
    """一条变异。

    name        变异 id（用 MUTATION=<name> 选中）
    protects    这条保护是什么（人话）
    detail      拆掉它之后，产品会怎样坏掉
    expect_red  预期会变红的用例 id（子串匹配）
    targets     跑哪些测试文件
    patch       应用变异；返回 probe 函数
    """

    name: str
    protects: str
    detail: str
    expect_red: tuple[str, ...]
    targets: tuple[str, ...]
    patch: Patch = field(repr=False)


# ── 各个变异的 patch 实现 ────────────────────────────

def _patch_pending_intent() -> Callable[[], bool]:
    """拆掉「在途 intent」判定。

    保护的是：结果未知的 effectful 调用**绝不自动重放**（策划案 §4.2.3）。
    拆掉它之后：崩溃恢复时那次「副作用可能已经发生」的调用会被再执行一次
    —— 重复扣款 / 重复发消息。
    """
    import infra.runtime.managed as managed

    original = managed.ManagedRuntime._pending_intent
    managed.ManagedRuntime._pending_intent = lambda self, key: None
    return lambda: managed.ManagedRuntime._pending_intent is not original


def _patch_result_cache() -> Callable[[], bool]:
    """拆掉幂等结果缓存。

    保护的是：重复投递同一 tool_call 不产生第二次副作用（R7）。
    拆掉它之后：同一幂等键投递 3 次 → 工具跑 3 次 → 副作用发生 3 次。
    """
    import infra.runtime.idempotency as idem

    original_get = idem.ResultCache.get_record
    original_result = idem.ResultCache.get_result
    idem.ResultCache.get_record = lambda self, key: None
    idem.ResultCache.get_result = lambda self, key: None

    def probe() -> bool:
        return (idem.ResultCache.get_record is not original_get
                and idem.ResultCache.get_result is not original_result)

    return probe


def _patch_checkpoint_decode() -> Callable[[], bool]:
    """拆掉「快照损坏」判定。

    保护的是：checkpoint 是**可丢弃的加速器**，坏了要退化成 journal 重放
    （策划案 §4.2.2 / 用例 7）。
    拆掉它之后：损坏的快照被当成可用 → 恢复从一个空状态继续 →
    已完成的工具调用被当成「没做过」→ 重复副作用。
    """
    import infra.runtime.checkpoint as checkpoint

    original = checkpoint.CheckpointStore._decode
    checkpoint.CheckpointStore._decode = staticmethod(lambda record: record)

    def probe() -> bool:
        return checkpoint.CheckpointStore._decode is not original

    return probe


def _patch_journal_dedupe() -> Callable[[], bool]:
    """拆掉事件去重。

    保护的是：消费方按 seq 去重，重复投递不重复计费（用例 6 / §4.2.2）。
    拆掉它之后：同一笔 token 被计费两次 → 预算被虚耗、成本归因失真。
    """
    import infra.runtime.journal as journal

    original = journal.Journal.dedupe
    journal.Journal.dedupe = staticmethod(lambda events: list(events))

    def probe() -> bool:
        return journal.Journal.dedupe is not original

    return probe


def _patch_trace_seq_dedupe() -> Callable[[], bool]:
    """拆掉 trace 消费方的 seq 去重。

    保护的是：trace 消费方按 seq 去重（§4.2.2）。
    拆掉它之后：一次模型调用在 trace 里出现两个 usage span →
    成本排查从此开始说谎。
    """
    import infra.observability.trace as trace

    original = trace.TraceCollector._emit

    def no_dedupe(self, kind, payload):
        data = dict(payload or {})
        data.pop('seq', None)
        return original(self, kind, data)

    trace.TraceCollector._emit = no_dedupe

    def probe() -> bool:
        return trace.TraceCollector._emit is not original

    return probe


def _patch_path_scan() -> Callable[[], bool]:
    """拆掉路径越界判定。

    保护的是：路径白名单（`../` 穿越 / 符号链接逃逸，§4.4.6 / 用例 4）。
    拆掉它之后：`cat ../../etc/passwd` 被放行 → 工作区外的机密可读。

    注意要打**两处**：
      * paths.scan_path_violations        —— 判定层本身（直接测它的那几条用例）
      * restricted.scan_path_violations   —— 后端持有的那份绑定
    只打第一处的话，后端那条路径完全不受影响 ——
    「from .paths import scan_path_violations」是一次**值拷贝**，
    之后改 paths 模块的属性对已经导入的名字无效。
    """
    import harness.tools.sandbox.paths as paths
    import harness.tools.sandbox.restricted as restricted

    original_paths = getattr(paths, 'scan_path_violations', None)
    original_backend = getattr(restricted, 'scan_path_violations', None)
    if original_paths is None or original_backend is None:
        return lambda: False        # 目标不存在 → 工具会报「变异没生效」

    paths.scan_path_violations = lambda tokens, policy, **kwargs: []
    restricted.scan_path_violations = lambda tokens, policy, **kwargs: []

    def probe() -> bool:
        return (paths.scan_path_violations is not original_paths
                and restricted.scan_path_violations is not original_backend)

    return probe


def _patch_network_check() -> Callable[[], bool]:
    """拆掉沙箱的网络判定。

    保护的是：network='allowlist' 时非白名单域名被拦（用例 5 / §4.4.6）。
    拆掉它之后：agent 可以把工作区里的数据 POST 到任意域名 → 数据外泄。
    """
    import harness.tools.sandbox.restricted as restricted

    original = getattr(restricted, 'check_network', None)
    if original is None:
        return lambda: False        # 目标不存在 → 工具会报「变异没生效」

    restricted.check_network = lambda level, tokens, allowlist: ''

    def probe() -> bool:
        return restricted.check_network is not original

    return probe


def _patch_awaiting_approval() -> Callable[[], bool]:
    """恢复时不认 awaiting_approval 的轮次。

    保护的是：审批等待期间进程退出 → 重启后仍处于 awaiting_approval（用例 3）。
    拆掉它之后：重启后这次审批被当成「没发生过」→ 人在回路形同虚设。
    """
    import infra.runtime.store as store

    original = store.SqliteRuntimeStore.last_open_turn

    def no_awaiting(self, session_id):
        turn = original(self, session_id)
        if turn is not None and turn.status == 'awaiting_approval':
            return None
        return turn

    store.SqliteRuntimeStore.last_open_turn = no_awaiting

    def probe() -> bool:
        return store.SqliteRuntimeStore.last_open_turn is not original

    return probe


def _patch_approval_submit() -> Callable[[], bool]:
    """决策回填失效。

    保护的是：审批决策可补填（用例 3）。
    拆掉它之后：重启后这次调用永远悬着 —— 要么等超时被拒，
    要么永远不返回。
    """
    from harness.approval.broker import LocalApprovalBroker

    original = LocalApprovalBroker.submit
    LocalApprovalBroker.submit = lambda self, request_id, decision: False

    def probe() -> bool:
        return LocalApprovalBroker.submit is not original

    return probe


def _patch_approval_restore() -> Callable[[], bool]:
    """待决请求恢复不出来。

    保护的是：进程重启后待决的审批请求能被捞回来（用例 3）。
    拆掉它之后：审批请求的**内容**只活在内存里 → 进程一死就永久悬空。
    """
    from harness.approval.broker import LocalApprovalBroker

    original = LocalApprovalBroker.restore_pending
    LocalApprovalBroker.restore_pending = lambda self, request: None

    def probe() -> bool:
        return LocalApprovalBroker.restore_pending is not original

    return probe


def _patch_inert_thing() -> Callable[[], bool]:
    """**假变异**：拆掉一个没有任何用例依赖的东西。

    存在的唯一目的：让元测试能验证「工具会如实报告『没被抓住』」。
    一个只会说「全部通过」的工具，比没有工具更危险 ——
    它让人误以为每条保护都有人守着。
    """
    from harness.tools.base import Tool

    original = Tool.to_openai_schema
    Tool.to_openai_schema = lambda self: {}

    def probe() -> bool:
        return Tool.to_openai_schema is not original

    return probe


# ── 变异清单 ──────────────────────────────────────────

MUTATIONS: dict[str, Mutation] = {
    mutation.name: mutation
    for mutation in (
        Mutation(
            name='pending_intent',
            protects='结果未知的 effectful 调用绝不自动重放（§4.2.3）',
            detail='崩溃恢复时，那次「副作用可能已经发生」的调用会被再执行一次'
                   '（重复扣款 / 重复发消息）',
            expect_red=(
                'test_kill9_during_effectful_tool_blocks_automatic_replay',
                'test_guard_refuses_to_replay_the_crashed_effectful_call',
            ),
            targets=('tests/fault/test_crash_recovery.py',),
            patch=_patch_pending_intent,
        ),
        Mutation(
            name='result_cache',
            protects='重复投递同一 tool_call 不产生第二次副作用（R7）',
            detail='同一幂等键投递 3 次 → 工具跑 3 次 → 副作用发生 3 次',
            expect_red=(
                'test_same_idempotency_key_delivered_three_times_runs_side_effect_once',
                'test_redelivery_after_restart_still_runs_side_effect_once',
                'test_guard_entry_point_delivered_three_times_runs_side_effect_once',
            ),
            targets=('tests/fault/test_idempotent_delivery.py',),
            patch=_patch_result_cache,
        ),
        Mutation(
            name='checkpoint_decode',
            protects='checkpoint 是可丢弃的加速器，坏了要退化成 journal 重放（§4.2.2）',
            detail='损坏的快照被当成可用 → 恢复从空状态继续 → 重复副作用',
            expect_red=(
                'test_corrupt_checkpoint_raises_explicit_error',
                'test_recovery_falls_back_to_journal_replay_when_checkpoint_corrupt',
                'test_tool_results_survive_a_corrupt_checkpoint',
            ),
            targets=('tests/fault/test_checkpoint_corruption.py',),
            patch=_patch_checkpoint_decode,
        ),
        Mutation(
            name='journal_dedupe',
            protects='消费方按 seq 去重，重复投递不重复计费（用例 6 / §4.2.2）',
            detail='同一笔 token 被计费两次 → 预算被虚耗、成本归因失真',
            expect_red=(
                'test_duplicate_event_delivery_does_not_double_bill',
                'test_journal_dedupe_keeps_first_occurrence_and_order',
                'test_recovery_replay_after_checkpoint_does_not_double_bill',
            ),
            targets=('tests/fault/test_event_redelivery_billing.py',),
            patch=_patch_journal_dedupe,
        ),
        Mutation(
            name='trace_seq_dedupe',
            protects='trace 消费方按 seq 去重（§4.2.2）',
            detail='一次模型调用在 trace 里出现两个 usage span → 成本排查说谎',
            expect_red=(
                'test_duplicate_event_delivery_produces_one_trace_span_per_event',
                'test_trace_collector_drops_redelivered_event_by_seq',
            ),
            targets=('tests/fault/test_event_redelivery_billing.py',),
            patch=_patch_trace_seq_dedupe,
        ),
        Mutation(
            name='path_scan',
            protects='路径白名单：`../` 穿越与符号链接逃逸被拦（用例 4 / §4.4.6）',
            detail='`cat ../../etc/passwd` 被放行 → 工作区外的机密可读',
            expect_red=(
                'test_cat_dotdot_etc_passwd_is_flagged_as_traversal',
                'test_symlink_escape_is_flagged',
                'test_sandbox_backend_blocks_cat_dotdot_etc_passwd',
            ),
            targets=('tests/fault/test_sandbox_path_escape.py',),
            patch=_patch_path_scan,
        ),
        Mutation(
            name='network_check',
            protects="network='allowlist' 时非白名单域名被拦（用例 5 / §4.4.6）",
            detail='agent 可以把工作区里的数据 POST 到任意域名 → 数据外泄',
            expect_red=(
                'test_network_to_non_allowlisted_domain_is_denied',
                'test_network_none_blocks_outgoing_traffic',
                'test_empty_allowlist_denies_everything',
            ),
            targets=('tests/fault/test_sandbox_network_deny.py',),
            patch=_patch_network_check,
        ),
        Mutation(
            name='awaiting_approval',
            protects='审批等待期间进程退出 → 重启后仍处于 awaiting_approval（用例 3）',
            detail='重启后这次审批被当成「没发生过」→ 人在回路形同虚设',
            expect_red=(
                'test_process_killed_while_awaiting_approval_stays_awaiting_approval',
            ),
            targets=('tests/fault/test_approval_crash_resume.py',),
            patch=_patch_awaiting_approval,
        ),
        Mutation(
            name='approval_submit',
            protects='审批决策可补填（用例 3）',
            detail='重启后这次调用永远悬着 —— 要么等超时被拒，要么永远不返回',
            expect_red=(
                'test_approval_decision_can_be_filled_in_after_restart',
            ),
            targets=('tests/fault/test_approval_crash_resume.py',),
            patch=_patch_approval_submit,
        ),
        Mutation(
            name='approval_restore',
            protects='进程重启后待决的审批请求能被捞回来（用例 3）',
            detail='审批请求的内容只活在内存里 → 进程一死就永久悬空',
            expect_red=(
                'test_approval_decision_can_be_filled_in_after_restart',
            ),
            targets=('tests/fault/test_approval_crash_resume.py',),
            patch=_patch_approval_restore,
        ),
        Mutation(
            name='inert_thing',
            protects='（无）—— 这是一条**假变异**，用来验证工具本身有效',
            detail='拆掉一个没有任何用例依赖的东西；预期：**没有任何用例变红**',
            expect_red=(),
            targets=('tests/fault/test_crash_recovery.py',
                     'tests/fault/test_idempotent_delivery.py',
                     'tests/fault/test_event_redelivery_billing.py'),
            patch=_patch_inert_thing,
        ),
    )
}


def apply_mutation(name: str) -> bool:
    """应用一条变异，返回「补丁是否真的生效」。

    返回 False 意味着 monkeypatch 没打上（实现改了名 / 属性没了）——
    这时工具必须**大声报错**，而不是安静地报告「没被抓住」。
    """
    mutation = MUTATIONS.get(name)
    if mutation is None:
        raise KeyError(f'未知变异: {name}（可用: {sorted(MUTATIONS)}）')
    probe = mutation.patch()
    return bool(probe())


__all__ = ['MUTATIONS', 'Mutation', 'apply_mutation']
