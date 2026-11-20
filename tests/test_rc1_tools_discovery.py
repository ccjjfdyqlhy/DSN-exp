# tests/test_rc1_tools_discovery.py
# ToolDiscovery 的测试 —— 策划案 §4.4.2 / rc1 C6。
#
# 目录快照要回答三件事：版本、来源、冻结清单（给 eval 分组与控制面资产）。

from __future__ import annotations

import json

from harness.tools.base import Tool, ToolRegistry, ToolResult
from harness.tools.discovery import ToolDiscovery
from harness.tools.registry import ManagedToolRegistry
from harness.tools.spec import ToolSpec


def read_tool():
    return Tool(name='fs.read', description='读文件',
                handler=lambda path='': ToolResult.ok(''),
                version='1.0',
                spec=ToolSpec(name='fs.read', version='1.0', effect='pure',
                              sandbox='readonly', owner='team-core'))


def shell_tool():
    return Tool(name='proc.run', description='跑命令',
                handler=lambda command='': ToolResult.ok(''),
                version='1.0',
                spec=ToolSpec(name='proc.run', version='1.0',
                              effect='effectful', sandbox='workspace',
                              network='none', destructive=False,
                              owner='team-core', scopes=('proc',)))


# ── 目录快照 ─────────────────────────────────────────────
def test_snapshot_lists_name_version_effect_sandbox():
    registry = ManagedToolRegistry()
    registry.register(read_tool())
    registry.register(shell_tool())
    discovery = ToolDiscovery(registry)
    entries = discovery.snapshot()
    by_name = {e.name: e for e in entries}
    assert by_name['fs.read'].effect == 'pure'
    assert by_name['fs.read'].sandbox == 'readonly'
    assert by_name['fs.read'].version == '1.0'
    assert by_name['fs.read'].owner == 'team-core'
    assert by_name['proc.run'].effect == 'effectful'
    assert by_name['proc.run'].scopes == ('proc',)
    # 冻结清单可序列化（eval / 控制面消费）
    payload = json.loads(discovery.snapshot_json())
    assert {item['name'] for item in payload} == {'fs.read', 'proc.run'}


def test_snapshot_reports_the_source_of_each_tool():
    registry = ManagedToolRegistry()
    registry.register(read_tool(), source='builtin')
    registry.register(shell_tool(), source='mcp:fetch')
    discovery = ToolDiscovery(registry)
    by_name = {e.name: e for e in discovery.snapshot()}
    assert by_name['fs.read'].source == 'builtin'
    assert by_name['proc.run'].source == 'mcp:fetch'


def test_undeclared_tool_snapshots_as_strictest():
    """没声明 spec 的工具在目录里按最严格档展示（策划案 §4.4.1）。"""
    registry = ToolRegistry()
    registry.register(Tool(name='mystery', description='',
                           handler=lambda: ToolResult.ok('')))
    discovery = ToolDiscovery(registry)
    entry = discovery.snapshot()[0]
    assert entry.effect == 'effectful'
    assert entry.sandbox == 'isolated'
    assert entry.version == '1.0'   # Tool 的默认版本


def test_plain_registry_accepts_an_explicit_source_map():
    registry = ToolRegistry()
    registry.register(read_tool())
    discovery = ToolDiscovery(registry, source_of={'fs.read': 'skill:core'})
    assert discovery.snapshot()[0].source == 'skill:core'


# ── 版本解析 ─────────────────────────────────────────────
def test_resolve_refuses_silent_version_switch():
    """策划案 §4.4.2：版本引用宁缺毋滥 —— 静默换版本 = 上游升级打断线上。"""
    tool = read_tool()
    registry = ToolRegistry()
    registry.register(tool)
    discovery = ToolDiscovery(registry)
    assert discovery.resolve('fs.read@1.0') is tool
    assert discovery.resolve('fs.read') is tool            # 裸名字放行
    assert discovery.resolve('fs.read@2.0') is None        # 版本不符 → None
    assert discovery.resolve('ghost@1.0') is None
    assert discovery.versions('fs.read') == ['1.0']
    assert discovery.versions('ghost') == []


# ── 文件扫描 ─────────────────────────────────────────────
def test_scan_directory_imports_and_registers_tools(tmp_path):
    (tmp_path / 'custom_tools.py').write_text(
        "from harness.tools.base import Tool, ToolResult\n"
        "def _handler(**kw):\n"
        "    return ToolResult.ok('custom')\n"
        "custom = Tool(name='demo.custom', description='自定义',\n"
        "              handler=_handler)\n",
        encoding='utf-8')
    (tmp_path / '_private.py').write_text('raise RuntimeError("should not load")',
                                          encoding='utf-8')
    (tmp_path / 'broken.py').write_text('this is not python', encoding='utf-8')
    registry = ManagedToolRegistry()
    discovery = ToolDiscovery(registry)
    found = discovery.scan_directory(tmp_path)
    names = [t.name for t in found]
    assert 'demo.custom' in names
    assert all(not n.startswith('_') for n in names)  # 下划线开头跳过
    assert registry.get('demo.custom') is not None
    # 来源记录为扫描目录
    assert registry.source_of('demo.custom').startswith('file:')
    # 重复扫描不覆盖已注册的
    discovery.scan_directory(tmp_path)
    assert registry.source_of('demo.custom') == registry.source_of('demo.custom')


def test_scan_directory_namespaces_the_discovered_tools(tmp_path):
    (tmp_path / 'more.py').write_text(
        "from harness.tools.base import Tool, ToolResult\n"
        "t = Tool(name='demo.thing', description='',\n"
        "         handler=lambda: ToolResult.ok(1))\n",
        encoding='utf-8')
    registry = ToolRegistry()
    discovery = ToolDiscovery(registry)
    found = discovery.scan_directory(tmp_path, namespace='ext', register=False)
    assert [t.name for t in found] == ['ext.demo.thing']


def test_scan_directory_handles_missing_dir(tmp_path):
    discovery = ToolDiscovery(ToolRegistry())
    assert discovery.scan_directory(tmp_path / 'nope') == []


# ── MCP 清单 ─────────────────────────────────────────────
def test_mcp_servers_lists_namespaces_without_connecting(tmp_path):
    config = tmp_path / 'mcp_servers.yaml'
    config.write_text(
        'servers:\n'
        '  - name: fetch\n'
        '    transport: stdio\n'
        '    enabled: false\n'
        '  - name: search\n'
        '    transport: http\n'
        '    url: http://127.0.0.1:9999\n',
        encoding='utf-8')
    discovery = ToolDiscovery(ToolRegistry())
    servers = discovery.mcp_servers(config)
    assert [s['name'] for s in servers] == ['fetch', 'search']
    assert servers[0]['namespace'] == 'mcp.fetch'
    assert servers[0]['enabled'] is False


def test_mcp_servers_tolerates_missing_or_broken_config(tmp_path):
    discovery = ToolDiscovery(ToolRegistry())
    assert discovery.mcp_servers(tmp_path / 'nope.yaml') == []
    bad = tmp_path / 'mcp_servers.yaml'
    bad.write_text('servers: {not: a list}\n', encoding='utf-8')
    assert discovery.mcp_servers(bad) == []
