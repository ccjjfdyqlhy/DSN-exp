# harness/models/__init__.py
"""harness.models 兼容模块，全面重导出 harness.orchestrator。"""

import sys
from harness import orchestrator

# 将 harness.orchestrator 映射进 sys.modules 保持模块一致性
sys.modules["harness.models"] = orchestrator
sys.modules["harness.models.base"] = sys.modules.get("harness.orchestrator.base", orchestrator.base)
sys.modules["harness.models.llamacpp"] = sys.modules.get("harness.orchestrator.llamacpp", orchestrator.llamacpp)
sys.modules["harness.models.lmstudio"] = sys.modules.get("harness.orchestrator.lmstudio", orchestrator.lmstudio)
sys.modules["harness.models.openai"] = sys.modules.get("harness.orchestrator.openai", orchestrator.openai)
sys.modules["harness.models.scheduler"] = sys.modules.get("harness.orchestrator.scheduler", orchestrator.scheduler)
sys.modules["harness.models.provider"] = sys.modules.get("harness.orchestrator.provider", orchestrator.provider)
sys.modules["harness.models.failover"] = sys.modules.get("harness.orchestrator.failover", orchestrator.failover)
sys.modules["harness.models.dynamic_router"] = sys.modules.get("harness.orchestrator.dynamic_router", orchestrator.dynamic_router)
sys.modules["harness.models.stub"] = sys.modules.get("harness.orchestrator.stub", orchestrator.stub)

from harness.orchestrator import *
