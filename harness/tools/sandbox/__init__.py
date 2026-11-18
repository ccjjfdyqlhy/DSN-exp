# harness/tools/sandbox —— 隔离执行。
#
# base.py 是协议；restricted.py / namespaced.py 是后端实现（后端实现由
# R3 工作流落地）。

from typing import Sequence

from .base import (
    BackendName,
    NetworkLevel,
    Sandbox,
    SandboxRequest,
    SandboxResult,
)


# ── R3：后端实现与选择 ────────────────────────────────────
#
# 追加在 base.py 的契约之下。base.py 是**协议**（策划案 §4.4.4），
# 这里是**实现**。两者分开是为了让「换后端」不需要改协议。

from .paths import PathPolicy, PathViolation, scan_path_violations  # noqa: E402
from .restricted import (  # noqa: E402
    ResourceLimits,
    RestrictedSandbox,
    VIOLATION_CMD_DENIED,
    VIOLATION_NET_DENY,
    VIOLATION_PATH_DENIED,
    VIOLATION_PATH_ESCAPE,
)
from .namespaced import (  # noqa: E402
    NamespacedSandbox,
    detect_capabilities,
)


def detect_best_backend(*, network_allowlist: Sequence[str] = (),
                        allowlist: Sequence[str] | None = None,
                        ) -> Sandbox:
    """挑一个当前可用的沙箱后端。

    优先级：namespaced（有内核级隔离）> restricted（兜底）。

    设计取舍：这里**不返回 None**，也不抛异常。
    「没有强隔离」不是错误状态，是一个**必须被看见的降级状态** ——
    返回的 restricted 后端的 degraded 恒为 True，上层据此决定
    「降级即拒绝」还是「降级放行 + 记审计」。

    另：detect_best_backend 只在**装配期**调用一次。
    不要在每次工具调用时调用 —— 它会真跑一遍探测命令（几十毫秒）。
    """
    caps = detect_capabilities()
    if caps.any_available:
        return NamespacedSandbox(network_allowlist=network_allowlist,
                                 allowlist=allowlist)
    return RestrictedSandbox(network_allowlist=network_allowlist,
                             allowlist=allowlist)


__all__ = [
    # 协议
    'Sandbox',
    'SandboxRequest',
    'SandboxResult',
    'NetworkLevel',
    'BackendName',
    # 后端
    'NamespacedSandbox',
    'RestrictedSandbox',
    'detect_best_backend',
    'detect_capabilities',
    # 路径判定
    'PathPolicy',
    'PathViolation',
    'scan_path_violations',
    # 违规码
    'VIOLATION_CMD_DENIED',
    'VIOLATION_NET_DENY',
    'VIOLATION_PATH_DENIED',
    'VIOLATION_PATH_ESCAPE',
    'ResourceLimits',
]
