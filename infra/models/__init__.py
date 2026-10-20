# infra/models/__init__.py
"""infra.models —— `infra.orchestrator` 的历史兼容层。

## 为什么存在

早期模型的抽象与编排放在 `infra/models/`，后来统一迁到 `infra/orchestrator/`。
仓库里仍有若干 `from infra.models.xxx import ...` 的旧写法，本模块负责让它们继续可用。

## 新代码请直接用 `infra.orchestrator`

```python
# 推荐
from infra.orchestrator.base import ChatMessage
# 兼容（等价，但不建议新增）
from infra.models.base import ChatMessage
```

## 实现方式（以及为什么不能更简单）

本目录下**只有这一个 `__init__.py`**，没有真实子模块文件。实现手段是把
`infra.orchestrator.*` 的模块对象直接登记进 `sys.modules` 的 `infra.models.*` 键。

这里有两个必须注意的细节：

1. **`infra.models` 这个键必须指向 orchestrator 包本身**，否则
   `import infra.models.base` 会走正常的子模块查找，找不到文件而失败。
2. **映射表必须与 orchestrator 的子模块保持同步**。历史上这份表漏了
   `router` / `anthropic` 等条目，导致 `from infra.models.router import ...`
   时灵时不灵——取决于之前有没有人先导入过 `infra.orchestrator`。

因此现在改为「显式白名单 + 自动兜底枚举」：白名单保证确定性，
兜底枚举让新增子模块即使忘了登记也能工作。
"""

from __future__ import annotations

import importlib
import sys

from infra import orchestrator

#: 需要预加载的 orchestrator 子模块。新增子模块时请同步加到这里——
#: 兼容层的确定性依赖此表（只靠自动枚举会漏掉「尚未被导入」的子模块）。
_PUBLIC_SUBMODULES = (
    "base",
    "provider",
    "scheduler",
    "failover",
    "lmstudio",
    "openai",
    "anthropic",
    "router",
    "dynamic_router",
    "stub",
    "local_engine",
    "local_chat",
    "llamacpp",
    "strata",
)


def _alias(name: str) -> None:
    """把 infra.orchestrator.<name> 注册为 infra.models.<name>（同一模块对象）。"""
    key = f"infra.models.{name}"
    if key in sys.modules:
        return
    try:
        module = importlib.import_module(f"infra.orchestrator.{name}")
    except Exception:  # noqa: BLE001 - 可选子模块缺失不应拖垮兼容层
        return
    sys.modules[key] = module
    # 同步挂到 orchestrator 包属性上，保持 import 语义一致
    if not hasattr(orchestrator, name):
        try:
            setattr(orchestrator, name, module)
        except Exception:  # noqa: BLE001
            pass


# 关键一步：先把 infra.models 指向 orchestrator 包，再登记子模块别名。
# 顺序反了会让 `import infra.models.xxx` 落到真实文件查找上。
sys.modules["infra.models"] = orchestrator

for _name in _PUBLIC_SUBMODULES:
    _alias(_name)

# 兜底：把已经加载、但不在白名单里的 orchestrator 子模块也一并登记。
for _loaded_name, _module in list(sys.modules.items()):
    if not _loaded_name.startswith("infra.orchestrator."):
        continue
    _short = _loaded_name[len("infra.orchestrator."):]
    if "." in _short or not _short:
        continue
    _key = f"infra.models.{_short}"
    if _key not in sys.modules:
        sys.modules[_key] = _module

# 顶层符号重导出（ChatMessage / IChatClient / ModelOrchestrator ...）
from infra.orchestrator import *  # noqa: F401,F403,E402
from infra.orchestrator import __all__ as __all__  # noqa: F401,E402
