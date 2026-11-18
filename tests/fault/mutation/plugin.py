# tests/fault/mutation/plugin.py
# 变异插件 —— 被**子进程**加载（`-p plugin`），只在那一个子进程里改实现。
#
# 【为什么是插件而不是 conftest】
#   插件只在显式 `-p plugin` 时才加载：
#     * 正常跑测试时它根本不在进程里 → 绝对不会污染测试套件；
#     * 变异跑在独立子进程里 → 就算补丁没恢复干净，也只脏那一个子进程。
#   conftest 是无条件加载的 —— 用它做变异等于把「变异」变成默认行为。
#
# 【用法】
#   MUTATION=pending_intent \
#     PYTHONPATH=tests/fault/mutation \
#     python -m pytest -q tests/fault/test_crash_recovery.py -p plugin
#
# 【环境变量】
#   MUTATION   要应用的变异 id；为空则什么都不做（正常跑测试就是这个状态）

from __future__ import annotations

import os

#: 补丁没打上时打出来的标记（父进程据此判定「变异根本没生效」）
NOT_APPLIED_MARKER = 'MUTATION_NOT_APPLIED'


def pytest_configure(config) -> None:
    name = (os.environ.get('MUTATION') or '').strip()
    if not name:
        return

    from mutations import apply_mutation

    try:
        applied = apply_mutation(name)
    except KeyError as error:
        raise SystemExit(str(error)) from error
    if not applied:
        # 补丁没打上（实现改名了 / 属性没了）—— 必须让人看见，
        # 否则工具会安静地报告「没被抓住」，看起来像「这条保护没人守」。
        print(f'{NOT_APPLIED_MARKER}:{name}', flush=True)
