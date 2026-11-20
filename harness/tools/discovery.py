# harness/tools/discovery.py
# ToolDiscovery：工具目录的发现与快照（策划案 §4.4.2）。
#
# 四条来源（策划案原文）：
#   静态注册   registry.register(ToolSpec, handler)      —— 已有
#   Skill 装载 harness/skills/loader.py                  —— 已有
#   MCP 桥接   harness/tools/mcp.py → mcp.<server>.<tool> —— 已有
#   发现       ToolDiscovery —— 本模块
#
# 为什么要「发现」这件事存在：
#   `aicf tool list` 只回答「现在装了什么」，回答不了三件事：
#   1. **版本** —— 同一 name 可并存多版本；Artifact 用版本引用
#      （shell@v3）而非名字引用，升级才不会打断线上。
#   2. **来源** —— 这个工具是内置的、skill 带来的，还是 MCP 桥来的？
#      审计要能回答「谁把这条执行路径放进来的」。
#   3. **目录快照** —— eval 按工具版本分组对比、控制面做资产管理，
#      都需要一份 name/version/effect/sandbox/scopes 的冻结清单。
#
# 依赖规则：本模块只读 ToolRegistry 与 Tool 的公开属性，
# 不 import infra —— 它属于 Kernel Plane 的工具面。

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import Tool, ToolRegistry

logger = logging.getLogger("harness.tools.discovery")


@dataclass
class CatalogEntry:
    """目录快照的一条（策划案 §4.4.2 ToolDiscovery.list 的返回形状）。"""

    name: str
    version: str
    effect: str
    sandbox: str
    network: str
    scopes: tuple[str, ...]
    destructive: bool
    owner: str
    source: str = 'builtin'          # builtin | skill | mcp:<server> | file:<path>
    summary: str = ''
    params_schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'version': self.version,
            'effect': self.effect,
            'sandbox': self.sandbox,
            'network': self.network,
            'scopes': list(self.scopes),
            'destructive': self.destructive,
            'owner': self.owner,
            'source': self.source,
            'summary': self.summary,
            'params_schema': self.params_schema,
        }


def spec_of(tool: Tool) -> dict:
    """取一个工具的契约字段（没有声明就按最严格档）。

    与 guard.spec_for() 的语义一致（默认 effectful + isolated），但这里
    返回**普通 dict**：发现面只读快照，不该为了看一眼目录就构造守卫。
    """
    spec = getattr(tool, 'spec', None)
    read_only = bool(getattr(tool, 'read_only', False))
    defaults = {
        'effect': 'pure' if read_only else 'effectful',
        'sandbox': 'readonly' if read_only else 'isolated',
        'network': 'none',
    }
    if spec is not None:
        return {
            'effect': str(getattr(spec, 'effect', defaults['effect'])),
            'sandbox': str(getattr(spec, 'sandbox', defaults['sandbox'])),
            'network': str(getattr(spec, 'network', defaults['network'])),
            'scopes': tuple(getattr(spec, 'scopes', ()) or ()),
            'destructive': bool(getattr(spec, 'destructive', False)),
            'owner': str(getattr(spec, 'owner', '') or ''),
            'version': str(getattr(spec, 'version', '') or ''),
        }
    return {
        'effect': defaults['effect'],
        'sandbox': defaults['sandbox'],
        'network': defaults['network'],
        'scopes': (),
        'destructive': False,
        'owner': '',
        'version': str(getattr(tool, 'version', '1.0')),
    }


class ToolDiscovery:
    """工具目录的发现器：快照 / 版本解析 / 文件扫描 / MCP 清单。"""

    def __init__(self, registry: ToolRegistry, *,
                 source_of: dict[str, str] | None = None) -> None:
        self._registry = registry
        # ManagedToolRegistry 自带 owner 追踪；普通 ToolRegistry 就用调用方给的
        self._source_of = source_of or {}

    # ── 目录快照 ─────────────────────────────────────────
    def snapshot(self) -> list[CatalogEntry]:
        """当前目录的快照（给 eval 分组、控制面资产、`tool list`）。"""
        source_attr = getattr(self._registry, 'source_of', None)
        entries: list[CatalogEntry] = []
        for tool in self._registry.tools():
            s = spec_of(tool)
            if source_attr is not None:
                try:
                    source = str(source_attr(tool.name) or 'builtin')
                except Exception:  # noqa: BLE001
                    source = 'builtin'
            else:
                source = self._source_of.get(tool.name, 'builtin')
            entries.append(CatalogEntry(
                name=tool.name,
                version=s['version'],
                effect=s['effect'],
                sandbox=s['sandbox'],
                network=s['network'],
                scopes=s['scopes'],
                destructive=s['destructive'],
                owner=s['owner'],
                source=source,
                summary=getattr(tool, 'description', '') or '',
                params_schema=getattr(tool, 'parameters', {}) or {},
            ))
        entries.sort(key=lambda e: e.name)
        return entries

    def snapshot_json(self) -> str:
        return json.dumps([e.to_dict() for e in self.snapshot()],
                          ensure_ascii=False, indent=2, default=str)

    # ── 版本 ─────────────────────────────────────────────
    def resolve(self, ref: str) -> Tool | None:
        """解析 `name@version` 或 `name` 引用。

        带版本时：版本不匹配返回 None（宁缺毋滥 —— 静默换版本
        正是「上游升级打断线上」的另一种形态）。
        """
        name, _, wanted = str(ref or '').partition('@')
        tool = self._registry.get(name)
        if tool is None:
            return None
        if wanted and str(tool.version) != wanted:
            logger.warning('工具 %s 的版本是 %s，引用要求 %s —— 拒绝静默换版',
                           name, tool.version, wanted)
            return None
        return tool

    def versions(self, name: str) -> list[str]:
        """同一 name 出现过的版本（发现层记录；注册表本身按 name 键控）。"""
        tool = self._registry.get(name)
        return [str(tool.version)] if tool is not None else []

    # ── 文件扫描 ─────────────────────────────────────────
    def scan_directory(self, path: str | Path, *,
                       namespace: str = '',
                       register: bool = True) -> list[Tool]:
        """扫描目录里的 Python 文件，把其中的 Tool 定义装进注册表。

        「工具可以被发现」是 rc1 C6 的后半句：Skill/YAML 之外的第三种
        来源就是**本地文件**。规则：
          - 每个 *.py 模块级暴露的 Tool 实例（或函数）都会被收集；
          - 模块在受控名字空间下 import（不是 sys.path 直挂）；
          - import 失败的文件**跳过并记录**，不让一个坏文件毁掉整个目录。
        """
        root = Path(path)
        if not root.is_dir():
            logger.warning('工具目录不存在: %s', root)
            return []
        found: list[Tool] = []
        for py in sorted(root.glob('*.py')):
            if py.name.startswith('_'):
                continue
            module = self._load_module(py)
            if module is None:
                continue
            found.extend(self._collect_from_module(module, namespace))
        if register:
            for tool in found:
                if self._registry.get(tool.name) is not None:
                    # 同名已存在不覆盖：发现面无权决定替换（replace 是
                    # 注册面的显式动作，带 replace=True 才发生）。
                    logger.info('工具 %s 已注册，扫描结果跳过', tool.name)
                    continue
                self._registry.register(tool, source=f'file:{root}')
        return found

    def _load_module(self, py: Path):
        spec = importlib.util.spec_from_file_location(
            f'_discovered_tools_{py.stem}', py)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001
            logger.warning('工具文件 %s 加载失败（跳过）: %s', py, error)
            return None
        return module

    def _collect_from_module(self, module: Any,
                             namespace: str) -> list[Tool]:
        found: list[Tool] = []
        for _, value in sorted(vars(module).items()):
            if isinstance(value, Tool):
                found.append(self._maybe_namespaced(value, namespace))
                continue
            # @tool 装饰过的函数在这里已经是 Tool（function_tool.tool
            # 返回 Tool）；万一有人只写了裸函数，不猜参数 —— 发现不猜。
        return found

    def _maybe_namespaced(self, tool: Tool, namespace: str) -> Tool:
        if not namespace or tool.name.startswith(f'{namespace}.'):
            return tool
        from .base import Tool as _Tool  # 局部引用避免循环
        clone = _Tool(
            name=f'{namespace}.{tool.name}',
            description=tool.description,
            handler=tool.handler,
            parameters=tool.parameters,
            async_mode=tool.async_mode,
            version=tool.version,
            spec=tool.spec,
        )
        return clone

    # ── MCP 清单 ─────────────────────────────────────────
    def mcp_servers(self, config_path: str | Path = 'mcp_servers.yaml'
                    ) -> list[dict]:
        """读 MCP 声明文件，返回服务器清单（不连接）。

        目录快照要能「预告」MCP 工具长什么样 —— 名字是
        `mcp.<server>.<tool>` 命名空间（策划案 §4.4.2）。
        真正的连接由 harness/tools/mcp.py 的 MCPManager 负责。
        """
        path = Path(config_path)
        if not path.exists():
            return []
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except Exception as error:  # noqa: BLE001
            logger.warning('MCP 声明 %s 解析失败: %s', path, error)
            return []
        servers = []
        for item in (data.get('servers') or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            servers.append({
                'name': name,
                'namespace': f'mcp.{name}',
                'transport': str(item.get('transport') or 'stdio'),
                'enabled': bool(item.get('enabled', True)),
            })
        return servers


__all__ = [
    'CatalogEntry',
    'ToolDiscovery',
    'spec_of',
]
