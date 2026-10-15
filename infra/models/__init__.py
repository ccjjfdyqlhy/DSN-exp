# infra/models/__init__.py
"""infra.models 兼容模块，全面重导出 infra.orchestrator。"""

import sys
from infra import orchestrator

# 将 infra.orchestrator 映射进 sys.modules 保持模块一致性
sys.modules["infra.models"] = orchestrator
sys.modules["infra.models.base"] = sys.modules.get("infra.orchestrator.base", orchestrator.base)
sys.modules["infra.models.llamacpp"] = sys.modules.get("infra.orchestrator.llamacpp", orchestrator.llamacpp)
sys.modules["infra.models.lmstudio"] = sys.modules.get("infra.orchestrator.lmstudio", orchestrator.lmstudio)
sys.modules["infra.models.openai"] = sys.modules.get("infra.orchestrator.openai", orchestrator.openai)
sys.modules["infra.models.scheduler"] = sys.modules.get("infra.orchestrator.scheduler", orchestrator.scheduler)
sys.modules["infra.models.provider"] = sys.modules.get("infra.orchestrator.provider", orchestrator.provider)
sys.modules["infra.models.failover"] = sys.modules.get("infra.orchestrator.failover", orchestrator.failover)
sys.modules["infra.models.dynamic_router"] = sys.modules.get("infra.orchestrator.dynamic_router", orchestrator.dynamic_router)
sys.modules["infra.models.stub"] = sys.modules.get("infra.orchestrator.stub", orchestrator.stub)
sys.modules["infra.models.local_engine"] = sys.modules.get("infra.orchestrator.local_engine", orchestrator.local_engine)
sys.modules["infra.models.local_chat"] = sys.modules.get("infra.orchestrator.local_chat", orchestrator.local_chat)
sys.modules["infra.models.strata"] = sys.modules.get("infra.orchestrator.strata", orchestrator.strata)

from infra.orchestrator import *
