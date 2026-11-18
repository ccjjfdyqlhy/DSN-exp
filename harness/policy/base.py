# harness/policy/base.py
# 准入策略端口的**再导出**。
#
# 实现与协议都住在 infra/policy/（见那里的文件头说明：端口与共享数据类型
# 住在 infra，harness 往上依赖它）。这里保留一个薄壳，是为了让 harness 侧的
# 代码能用 `from ..policy.base import PolicyDecision` 这样的短路径，
# 同时让「这个类型到底定义在哪」只有一个答案。

from infra.policy.base import (
    DeniedReason,
    PolicyDecision,
    PolicyEngine,
    PolicyRule,
    Risk,
)

__all__ = [
    'PolicyDecision',
    'PolicyEngine',
    'PolicyRule',
    'Risk',
    'DeniedReason',
]
