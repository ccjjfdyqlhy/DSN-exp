# harness/cli/initcmd.py
# `aicf init` —— 空白脚手架（roadmap 段 2）。
#
# 目标：新建一个空文件夹 → `aicf init` → 得到一批**写好了接入点、
# 但没有业务**的骨架，用户自己往里填肉。
#
# 骨架里每个接入点都是「带注释的空位」，不是 TODO 列表 ——
# 生成后立刻能跑：`python agent.py` 起得来（离线用桩模型），
# `aicf tool list` 看得见自己注册的工具（tools/local.py 的目录约定）。
#
# 模板参数（--template）按 roadmap 预留：目前只有 default。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TEMPLATES = ("default",)

# ── 骨架文件内容 ─────────────────────────────────────────────
# 每份文件都是「能直接跑的最小接线」：跑得起来，但没有任何业务逻辑。
# 注释回答「往哪填」，正文回答「怎么跑」。

_AGENT_PY = '''#!/usr/bin/env python3
# 这个文件是你的 Agent 入口 —— 已经接好，直接能跑。
#
#   python agent.py              # 离线跑一轮（桩模型回显，不需要 API key）
#   OPENAI_API_KEY=sk-... python agent.py   # 配上 key，模型会真的调用工具
#
# 接入点（往哪填）：
#   1. 自己的工具      → tools/ 目录（每个 *.py 暴露 TOOLS 列表，见 tools/greet.py）
#   2. 安全策略        → policies/policy.yaml（默认拒绝 + effectful 要审批）
#   3. 系统提示词      → 下面的 SYSTEM_PROMPT
#   4. 技能（可选）    → skills/ 目录（声明式 skill.yaml，见 skills/hello/skill.yaml）

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

MODEL_NAME = os.environ.get("AICF_MODEL", "gpt-4o-mini")
SYSTEM_PROMPT = (
    "你是一个跑在本机的小助手。"
    "需要打招呼时调用 greet 工具；其它事直接回答。"
)

# ── 1. 工具表：从 tools/ 目录装载（约定见 tools/greet.py 的注释）────
from aicf.harness.tools.local import attach_local_tools

from aicf.harness.tools.registry import ManagedToolRegistry

registry = ManagedToolRegistry()
found = attach_local_tools(registry, ROOT / "tools")
print(f"[agent] 已从 tools/ 装载 {found} 个工具", file=sys.stderr)

# ── 2. 模型客户端：有 key 用真模型，没 key 用桩模型（离线可跑）──────
from aicf.harness.sdk import create_agent

client = None
if not os.environ.get("OPENAI_API_KEY"):
    from aicf.infra.orchestrator.base import ChatResponse
    from aicf.infra.orchestrator.stub import StubChatClient

    def _respond(messages, tools):
        # 桩模型：把最后一条用户输入回显出来 —— 离线也有确定的结果。
        text = ""
        for message in reversed(messages or []):
            content = message.get("content") if isinstance(message, dict) else ""
            if content:
                text = str(content)
                break
        return ChatResponse(content=f"[stub] {text}")

    client = StubChatClient(model="stub", respond=_respond)
    print("[agent] 未配置 OPENAI_API_KEY，本轮使用桩模型（只会回显）",
          file=sys.stderr)

agent = create_agent(
    model=MODEL_NAME,
    client=client,            # None → create_agent 自己建 OpenAI 兼容客户端
    system_prompt=SYSTEM_PROMPT,
    tools=list(registry.tools()),
    workspace=str(ROOT),
)

if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "用 greet 打个招呼"
    print(agent.chat(question))
'''

_GREET_PY = '''# tools/greet.py —— 示例工具：照这个样子写你自己的。
#
# 约定：tools/ 下每个 *.py 暴露一个模块级 ``TOOLS`` 列表，
# 元素是普通函数（框架自动从签名 + docstring 生成参数 schema）或 Tool。
#
# 接入点：
#   - 改这个函数，或者新开一个 tools/xxx.py 写自己的工具
#   - 函数要有类型注解和 docstring —— 它们直接变成模型看到的参数 schema 和说明
#   - 工具可以声明契约（spec）：effect / sandbox / network / destructive。
#     未声明的工具按最严格档处理（effectful + 需审批）——
#     「忘写声明」不等于静默放权，这是 aicf 的默认拒绝原则。

from aicf.harness.tools.base import Tool
from aicf.harness.tools.function_tool import tool_from_function
from aicf.harness.tools.spec import ToolSpec


def greet(name: str) -> str:
    """向指定的人打一声招呼。"""
    return f"你好，{name}！这个工具来自你自己的 tools/ 目录。"


# 只读纯工具：声明成 pure + readonly，默认策略会自动放行（不需要人工审批）。
# 有副作用的工具不要这么声明 —— 让策略文件来决定它要不要审批。
GREET = tool_from_function(greet)
GREET.spec = ToolSpec.read_only_default("greet")

TOOLS = [GREET]
'''

_SKILL_YAML = '''# skills/hello/skill.yaml —— 声明式技能的接入点（默认不加载）。
#
# skill.yaml 是 aicf 技能包的公开格式（规格见 docs/skills.md）：
# 一个技能 = skill.yaml（声明）+ prompts/*.md（提示词）+ tools/*.py（工具）。
#
# 想启用它：用 SkillManager 扫描 skills/ 目录并注册进你的 Agent，
# 见 https://github.com/ 模块 aicf.harness.skills 的 yaml_manager。
name: hello
display_name: Hello 技能
description: 演示技能包格式 —— 名字、工具声明、激活词。
version: "1.0"
author: your-name
source: custom
enabled: false            # 改成 true 并接入 SkillManager 后生效
status: active
prompt_priority: 60
tools:
  - name: hello_ping
    display_name: Hello Ping
    description: 返回一句固定的话，验证技能链路通不通。
    module: tools/hello.py        # 相对技能目录；skill.yaml 旁边建 hello.py 即可
    class: HelloTool
    methods:
      - name: ping
        description: 返回 pong。
        parameters: {}
activation:
  keywords: ["hello", "你好"]
  auto_activate: false
dependencies: []
tags: [example]
'''

_SKILL_HELLO_PY = '''# skills/hello/hello.py —— 技能工具的最小实现。
#
# 三条硬规则（docs/skills.md）：
#   1. 工具名 == 实例方法名（下面的 ping）
#   2. 参数名 == 方法签名的参数名
#   3. 返回 {"success": bool, ...}，异常也吞成 success=False


class HelloTool:
    def ping(self) -> dict:
        """返回 pong。"""
        return {"success": True, "reply": "pong"}
'''

_POLICY_YAML = '''# policies/policy.yaml —— 默认策略：默认拒绝 + effectful 要审批。
#
# 这份文件用 aicf 的策略格式（aicf/infra/policy/loader.py 加载，
# 字段拼错会直接报错 —— 一条被忽略的 deny 规则就是一次静默放权）。
#
# 当前语义：
#   - auto_approve_risk: low    只读 / 纯计算工具自动放行
#   - 其余（有副作用 / 有网络 / 破坏性）→ 需要人工审批
#
# 接入点：
#   - 给某个工具显式放行 → 加一条 {action: allow, tool: <工具名>}
#   - 显式封禁某个工具   → 加一条 {action: deny,  tool: <工具名>}（deny 永远赢）
#   - 全部自动放行（不推荐）→ auto_approve_risk: high
auto_approve_risk: low
allow_readonly: true
rules: []
'''

_README_MD = '''# {name}

`aicf init` 生成的 Agent 骨架 —— 接入点都接好了，里面没有业务，往里填肉就行。

## 三十秒跑通

```bash
aicf tool list                      # 看得见你自己的工具（tools/ 目录约定）
aicf tool exec greet --args '{{"name":"世界"}}'   # 离线调通第一个工具
python agent.py                     # 起一个 Agent 跑一轮（无 API key 用桩模型）
```

配上真模型后（`OPENAI_API_KEY=... python agent.py`），模型会自己决定调用 `greet`。

## 目录里是什么

| 路径 | 是什么 | 往哪填 |
|---|---|---|
| `agent.py` | Agent 入口，已接好 | 改系统提示词、换模型 |
| `tools/` | 你的工具目录（`.aicf_tools` 标记让 CLI 认识它） | 每个文件暴露 `TOOLS` 列表，函数签名即参数 schema |
| `policies/policy.yaml` | 默认策略：默认拒绝 + effectful 要审批 | 加 allow/deny 规则 |
| `skills/hello/` | 声明式技能包接入点（默认不加载） | 照 `skill.yaml` 写自己的技能 |
| `traces/` | trace 落盘处 | `aicf run "..." --trace traces/run.jsonl` |

## 安全模型（默认就生效）

- 工具没声明契约 = 最严格档（effectful + 需审批）—— 忘写声明不会静默放权
- `policies/policy.yaml` 里 deny 规则永远赢过 allow
- 每次工具调用都留审计；`aicf tool exec` 也走同一条守卫链路

## 下一步

- 文档：<https://github.com/>（docs/ 目录：getting-started / security / skills）
- 把 `pyproject.toml` 里的名字、作者改成你自己的 —— 这个骨架就是一个正常的 Python 项目。
'''

_PYPROJECT_TOML = '''[project]
name = "{name}"
version = "0.1.0"
description = "aicf-core 骨架项目 —— 接入点已接好，填入你的业务"
requires-python = ">=3.10"
dependencies = ["aicf-core"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = []
py-modules = ["agent"]
'''

_GITIGNORE = '''__pycache__/
*.pyc
traces/*.jsonl
.env
'''


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def create_skeleton(target: Path, *, name: str, template: str = "default",
                    force: bool = False) -> list[Path]:
    """在 ``target`` 目录生成骨架，返回创建的文件列表。

    目录非空且未给 force → 抛 FileExistsError（CLI 层转成友好报错）。
    """
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"目录非空: {target}（--force 覆盖）")

    files = [
        ("agent.py", _AGENT_PY),
        ("tools/.aicf_tools",
         "# 这个标记声明「本目录是 aicf 项目本地工具目录」。\n"
         "# 有它，`aicf tool list` / `aicf run` 才会扫描本目录里的 *.py；\n"
         "# 没有它，任何 CLI 命令都不会执行这里的代码。\n"),
        ("tools/greet.py", _GREET_PY),
        ("tools/.gitkeep", ""),
        ("skills/hello/skill.yaml", _SKILL_YAML),
        ("skills/hello/hello.py", _SKILL_HELLO_PY),
        ("policies/policy.yaml", _POLICY_YAML),
        ("traces/.gitkeep", ""),
        (".gitignore", _GITIGNORE),
        ("README.md", _README_MD.format(name=name)),
        ("pyproject.toml", _PYPROJECT_TOML.format(name=name)),
    ]
    if template not in _TEMPLATES:
        raise ValueError(
            f"未知模板: {template}（可用: {', '.join(_TEMPLATES)}；"
            "voice/agent 模板规划中）")

    created: list[Path] = []
    for rel, content in files:
        created.append(_write(target / rel, content))
    return created


def cmd_init(args: Any) -> int:
    from .common import eprint

    name = args.name
    target = Path(args.dir or name).resolve()

    try:
        created = create_skeleton(
            target, name=name, template=args.template, force=args.force)
    except FileExistsError as error:
        eprint(f"拒绝覆盖：{error}")
        eprint("换一个目录名，或加 --force 覆盖已有文件。")
        return 2
    except ValueError as error:
        eprint(str(error))
        return 2

    if args.json:
        print(json.dumps({
            "project": name,
            "path": str(target),
            "template": args.template,
            "files": [str(p.relative_to(target)) for p in created],
        }, ensure_ascii=False, indent=2))
        return 0

    rel = target
    try:
        rel = target.relative_to(Path.cwd())
    except ValueError:
        pass
    print(f"骨架已生成: {rel}/")
    print("下一步：")
    print(f"  cd {rel}")
    print("  aicf tool list                                   # 看见你的工具")
    print('  aicf tool exec greet --args \'{"name":"世界"}\'     # 离线调通第一个工具')
    print("  python agent.py                                  # 起一个 Agent（离线可跑）")
    print("填肉位置见 README.md —— 每个接入点都是一段带注释的空位。")
    return 0


def register(sub: Any) -> None:
    """把 init 子命令挂到主解析器上（与 artifactcmd 同款模式）。"""
    init = sub.add_parser("init", help="生成空白 Agent 骨架（接入点已接好）")
    init.add_argument("name", nargs="?", default="my-agent",
                      help="项目名（也是目录名，默认 my-agent）")
    init.add_argument("--dir", default="",
                      help="生成目标目录（默认与项目名同名）")
    init.add_argument("--template", default="default",
                      help=f"模板（预留参数，当前可用: {', '.join(_TEMPLATES)}）")
    init.add_argument("--force", action="store_true",
                      help="目标目录非空时也生成（覆盖同名文件）")
    init.add_argument("--json", action="store_true", help="输出 JSON")
    init.set_defaults(func=cmd_init)


__all__ = ["cmd_init", "create_skeleton", "register"]
