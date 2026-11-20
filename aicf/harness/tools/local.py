# harness/tools/local.py
# 项目本地工具目录的发现与装载（`aicf init` 生成的骨架用同一套约定）。
#
# 约定（也是骨架 README 里写的那条）：
#   ./tools/  下每个 *.py 暴露一个模块级列表 ``TOOLS``，
#   元素是**普通函数**（自动从签名/docstring 生成 schema）或 Tool 实例。
#
# 为什么放 harness 而不是 CLI：`aicf tool list`、`aicf tool exec`、`aicf run`
# 和骨架的 agent.py 都要吃同一份 tools/ 目录 —— 装载规则只能有一个答案。
#
# 安全口径：装载的是**当前工作目录里的代码**，与「在那个目录里跑
# python agent.py」是同一信任级别；不扫隐藏目录，不递归子目录，
# 加载失败只跳过并报告，绝不让一个坏文件拖垮整个目录。
#
# 隐式扫描必须显式声明：CLI 对 cwd 的自动扫描**只认带标记文件
# （.aicf_tools）的 tools/ 目录**。世界上有一堆项目顶层就有一个
# tools/ 目录（构建脚本、导出工具……），在人家的工作目录里静默
# 执行任意 python 文件是不可接受的 —— `aicf init` 的骨架自带标记，
# 手工建的目录写一个空标记文件即可。

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

from .base import Tool
from .function_tool import tool_from_function

#: 本地工具模块在 sys.modules 里的命名空间前缀。
#: 不放在顶层 —— 避免与用户的其它同名模块（tools/ 是个常见名字）互相遮蔽。
_MODULE_PREFIX = "aicf_project_tools_"

#: 隐式扫描的标记文件。没有标记的 tools/ 目录不会被扫描。
MARKER_FILENAME = ".aicf_tools"


def is_project_tools_dir(directory: str | Path) -> bool:
    """是不是一个被显式声明过的 aicf 本地工具目录（目录存在 + 有标记）。"""
    root = Path(directory)
    return root.is_dir() and (root / MARKER_FILENAME).exists()


class LocalToolsError(ValueError):
    """tools/ 目录本身的问题（不存在 / 不是目录）。"""


def _import_module(path: Path) -> ModuleType:
    """按文件路径导入一个模块（不要求它是包的一部分）。"""
    module_name = f"{_MODULE_PREFIX}{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 构建 import spec")
    module = importlib.util.module_from_spec(spec)
    # 注册进 sys.modules：dataclass / get_type_hints 等反射机制需要能查到它。
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # 导入失败别留半初始化的模块在 sys.modules 里（反射机制会查到它）。
        sys.modules.pop(module_name, None)
        raise
    return module


def _coerce(candidate: Any, source: str) -> Tool:
    """把 TOOLS 列表里的元素统一成 Tool。"""
    if isinstance(candidate, Tool):
        return candidate
    if callable(candidate):
        return tool_from_function(candidate)
    raise TypeError(f"{source}: TOOLS 里的元素必须是函数或 Tool，得到 {type(candidate)!r}")


def load_local_tools(directory: str | Path,
                     *,
                     on_error: Optional[Callable[[str], None]] = None,
                     include_hidden: bool = False,
                     ) -> list[Tool]:
    """装载 ``directory`` 下的项目本地工具。

    on_error   每个坏文件调一次（传入可读的原因）；不传则 print 到 stderr。
               坏文件**不阻断**其它文件 —— 骨架刚起步时别让一个笔误
               把整个目录变成黑盒。
    """
    root = Path(directory)
    if not root.exists():
        raise LocalToolsError(f"工具目录不存在: {root}")
    if not root.is_dir():
        raise LocalToolsError(f"不是目录: {root}")

    def default_on_error(message: str) -> None:
        import sys as _sys
        print(f"[aicf] 跳过：{message}", file=_sys.stderr)

    report = on_error or default_on_error
    tools: list[Tool] = []
    for path in sorted(root.glob("*.py")):
        if not include_hidden and path.name.startswith("_"):
            continue
        try:
            module = _import_module(path)
        except (Exception, SystemExit) as error:
            # SystemExit 也要接住：用户模块在 import 时 sys.exit() 是常见事故
            # （顶层脚本 / 依赖检查），它不是 Exception 的子类。
            # KeyboardInterrupt 不吞 —— Ctrl+C 该停还是要停。
            report(f"{path}: 导入失败（{error!r}）")
            continue
        declared = getattr(module, "TOOLS", None)
        if declared is None:
            report(f"{path}: 没有模块级 TOOLS 列表（约定见骨架 README）")
            continue
        if not isinstance(declared, (list, tuple)):
            report(f"{path}: TOOLS 必须是列表")
            continue
        for i, candidate in enumerate(declared):
            try:
                tools.append(_coerce(candidate, f"{path} TOOLS[{i}]"))
            except Exception as error:  # noqa: BLE001
                report(f"{path} TOOLS[{i}]: {error}")
    return tools


def attach_local_tools(registry: Any, directory: str | Path,
                       *,
                       on_error: Optional[Callable[[str], None]] = None) -> int:
    """把 ``directory`` 里的工具注册进 registry，返回成功注册的数量。

    与标准工具重名的项目工具**跳过并报告**（replace=False 语义）：
    静默覆盖一条标准工具等于把 file.read 换成了用户代码 —— 那必须显式做。
    """
    def default_on_error(message: str) -> None:
        import sys as _sys
        print(f"[aicf] 跳过：{message}", file=_sys.stderr)

    report = on_error or default_on_error
    tools = load_local_tools(directory, on_error=report)
    attached = 0
    for tool in tools:
        if registry.has(tool.name):
            report(f"工具 {tool.name} 与已有工具重名，跳过"
                   f"（如需覆盖请显式 unregister 后再注册）")
            continue
        registry.register(tool)
        attached += 1
    return attached


__all__ = [
    "MARKER_FILENAME",
    "LocalToolsError",
    "attach_local_tools",
    "is_project_tools_dir",
    "load_local_tools",
]
