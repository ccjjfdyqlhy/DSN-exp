"""apps/harness_lab 的 pytest 包装 —— 让验证台成为仓库测试的一部分。

每个检查项一条用例：
  * 正常项 → 必须通过（验证台自身与 harness 的健康部分不会腐坏）
  * 已知缺陷 → `xfail(strict=True)`：**缺陷被修好的那天，这条用例会失败**，
    提醒把标记摘掉。

`strict=True` 是关键：普通 xfail 在问题被修复后会静默变成 XPASS，
缺陷就再也没人管了。
"""

from __future__ import annotations

import pytest

from apps.harness_lab.config import LabConfig
from apps.harness_lab.runner import run_scenario
from apps.harness_lab.scenarios import SCENARIOS

# ── 尚未修复的缺陷（为空表示当前无已知缺陷；修复后请删掉对应条目） ──
KNOWN_DEFECTS: dict[str, str] = {}

# ── 已修复的缺陷：对应的检查项必须**持续通过**，否则说明缺陷复活了 ──
FIXED_DEFECTS: dict[str, str] = {
    "persona.distillation_artifact_complete":
        "蒸馏产物结构化字段全空 —— pass2 被 max_tokens=3000 截断后 JSON 解析失败，"
        "解析器静默 return {}（已修：预算提到 8000/16000 + 结构校验 + 失败抛错）",
    "persona.distillation_indicator_vector_varied":
        "蒸馏的 50 维向量全是 0.5（已修：pass3 维度完整性校验 + 重试，不再静默补 0.5）",
    "persona.distillation_no_silent_empty":
        "截断导致产物为空时没有任何异常抛出（已修：DistillationError 显式抛错）",
    "persona.state_flush_required":
        "未 flush 的状态在重启后丢失（已修：on_interaction 写穿落库）",
    "persona.evidence_survives_restart":
        "证据状态重启后失忆（已修：mu/sigma/counts/pending 全部以 DB 为真源）",
    "persona.consolidate_counter_survives_restart":
        "固化计数重启后归零，门槛永远达不到（已修：pending 列持久化）",
    "persona.prompt_cache_isolated_per_user":
        "人格提示词缓存全局单份，多用户串人格（已修：缓存按 (卡, 用户, 关系阶段) 分桶）",
    "persona.fallback_no_foreign_persona":
        "兜底串硬编码了另一个应用的人格（已修：改为不含产品身份的行为准则）",
    "context.plan_is_pure":
        "SegmentedContextAssembler.plan() 就地改写调用方传入的段"
        "（已修：memo 分支改用 replace()）",
}


@pytest.fixture(scope="module")
def lab_results(tmp_path_factory):
    """跑一遍全部场景（隔离工作区，放在 pytest 的临时目录里）。"""
    out = tmp_path_factory.mktemp("harness_lab")
    cfg = LabConfig(output_dir=out)
    cfg.ensure_dirs()
    return {sc.id: run_scenario(sc, cfg) for sc in SCENARIOS}


def _cases(lab_results):
    for sc in SCENARIOS:
        result = lab_results.get(sc.id)
        if result is None:
            continue
        for check in result.checks:
            yield sc.id, check


ALL_CASES = list(_cases({"s": None}))  # 仅用于收集阶段的参数化（用下面的真实 fixture 覆盖）


@pytest.mark.parametrize("scenario_id,check_id", [
    (sc.id, cid) for sc in SCENARIOS for cid in sc.checks
])
def test_harness_lab_check(scenario_id, check_id, lab_results):
    """验证台的每一条检查项。"""
    result = lab_results.get(scenario_id)
    assert result is not None, f"场景 {scenario_id} 没有结果"
    assert result.ok, f"场景 {scenario_id} 执行异常: {result.error}"
    match = next((c for c in result.checks if c.id == check_id), None)
    assert match is not None, f"检查项 {check_id} 没有结果"
    if check_id in KNOWN_DEFECTS:
        pytest.xfail(f"{KNOWN_DEFECTS[check_id]}")
    assert match.passed, f"{check_id} 失败: {match.detail} | 证据: {match.evidence}"


def test_lab_all_scenarios_executed(lab_results):
    """所有场景都要能跑完（不能因为脚本报错而静默跳过）。"""
    assert len(lab_results) == len(SCENARIOS)
    errors = {sid: r.error for sid, r in lab_results.items() if not r.ok}
    assert not errors, f"场景执行异常: {errors}"


def test_lab_known_defects_still_reproducible(lab_results):
    """尚未修复的缺陷必须**仍然复现** —— 修好了就把那条也删掉。

    这是防止"缺陷被悄悄改没、但没人知道"的那道闸。
    """
    reproduced = set()
    for sc in SCENARIOS:
        result = lab_results.get(sc.id)
        for check in result.checks:
            if check.id in KNOWN_DEFECTS and not check.passed:
                reproduced.add(check.id)
    missing = [k for k in KNOWN_DEFECTS if k not in reproduced]
    assert not missing, (
        f"这些已知缺陷没有复现（可能已被修复，请从 KNOWN_DEFECTS 里删掉）: {missing}")


def test_lab_fixed_defects_stay_fixed(lab_results):
    """已修复的缺陷对应的检查项必须**持续通过** —— 缺陷复活即失败。"""
    by_id = {}
    for sc in SCENARIOS:
        for check in lab_results[sc.id].checks:
            by_id[check.id] = check
    regressed = []
    for check_id, why in FIXED_DEFECTS.items():
        check = by_id.get(check_id)
        if check is None:
            regressed.append(f"{check_id}: 检查项不见了")
        elif not check.passed:
            regressed.append(f"{check_id}: {check.detail}")
    assert not regressed, "已修复的缺陷复活了:\n  " + "\n  ".join(regressed)
