# apps/dsn_ui/tools.py
# DSN-UI 工具系统：仅使用 harness 原生工具 + 两阶段 toolbox 激活。
#
# 设计约束（重要）：
#   本模块刻意不桥接 apps/dsn/skills 体系。dsn_ui 的工具能力完全来自
#   harness 标准工具集，并统一走 ToolboxManager 的两阶段激活路径：
#     阶段 1  仅下发 toolbox 索引工具（内联可用工具 id + 描述）
#     阶段 2  模型按需激活后才下发对应工具的完整 schema
#   这样可以按需加载、避免一次性注入全部 schema 浪费上下文预算。

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from harness.tools.base import ToolRegistry
from harness.tools.toolbox import ToolboxManager, RegistryIndexSource
from harness.tools.standard import ToolDeps, install_standard_tools

logger = logging.getLogger("DSNUITools")


class DSNUIToolCoordinator:
    """DSN-UI 工具注册与两阶段 toolbox 调度器（纯 harness 实现）。"""

    def __init__(self, workspace_root: Path, max_output_chars: int = 6000):
        self.workspace_root = workspace_root
        self.max_output_chars = max_output_chars
        self.tool_reg = ToolRegistry()
        self._install_tools()

    def _install_tools(self) -> None:
        self.tool_reg = ToolRegistry()
        try:
            tool_deps = ToolDeps(workspace=str(self.workspace_root), max_output_chars=self.max_output_chars)
            install_standard_tools(self.tool_reg, deps=tool_deps)
        except Exception as e:
            logger.warning("安装 harness 标准工具失败: %s", e)

    def set_max_output_chars(self, chars: int) -> None:
        """更新工具输出最大字符数，并重新生成工具函数闭包。"""
        new_val = max(500, int(chars))
        if new_val != self.max_output_chars:
            self.max_output_chars = new_val
            self._install_tools()
            self.index_source = RegistryIndexSource(self.tool_reg)
            self.toolbox.source = self.index_source
            self.toolbox._cached_index = None

        # 两阶段动态激活：Stage1 只发 toolbox 索引，Stage2 才发已激活工具 schema
        self.index_source = RegistryIndexSource(self.tool_reg)
        self.toolbox = ToolboxManager(
            self.index_source,
            enabled=True,
            tool_name="toolbox",
            index_initial=True,
            nested=False,
        )

    def tool_names(self) -> list[str]:
        return sorted(self.tool_reg.names())

    def tool_index(self) -> list[dict]:
        """返回工具箱索引（id + 描述）。"""
        return list(self.toolbox._index())

    def get_skill_prompts(self) -> str:
        """dsn_ui 不再注入应用层技能提示词，统一由 toolbox 索引承载。"""
        return ""


# 兼容旧引用名，避免外部导入立即报错（内部语义已改为纯 harness 工具）。
DSNUISkillCoordinator = DSNUIToolCoordinator
