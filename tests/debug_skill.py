#!/usr/bin/env python3
"""交互式技能调试器 — 模拟 AI 发起 <tool> 请求并查看技能回复。

用法:  python tests/debug_skill.py

无需额外依赖 — 使用系统 readline 提供输入历史与 Tab 补全。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEEPSEEK_API_KEY", "debug-key")

try:
    import readline
except ImportError:
    readline = None

try:
    from skills.registry import SkillRegistry
    from skills.manager import SkillManager
except Exception:
    print("无法导入技能系统，请从项目根目录运行")
    sys.exit(1)


class _Completer:
    def __init__(self, words: list[str]):
        self._words = sorted(words, key=str.lower)

    def complete(self, text, state):
        matches = [w for w in self._words if w.lower().startswith(text.lower())]
        try:
            return matches[state]
        except IndexError:
            return None


def _read_line(prompt: str, completer: _Completer | None = None) -> str:
    if readline and completer:
        old = readline.get_completer()
        readline.set_completer(completer.complete)
        readline.parse_and_bind("tab: complete")
        try:
            return input(prompt).strip()
        finally:
            readline.set_completer(old)
    return input(prompt).strip()


class SkillDebugger:
    def __init__(self):
        self.registry = SkillRegistry()
        skill_dirs = [
            str(PROJECT_ROOT / "skills" / "builtin"),
            str(PROJECT_ROOT / "skills" / "custom"),
        ]
        self.manager = SkillManager(skill_dirs=skill_dirs, registry=self.registry)
        loaded = self.manager.scan_and_load()
        print(f"已加载 {loaded} 个技能\n")

        self._skill_list = self.registry.list_skills()
        self._tool_list = self.registry.get_all_tool_specs()

    def run(self):
        print("=" * 60)
        print("  DSN-exp 技能调试器")
        print("  模拟 AI 发起工具请求，查看技能原始回复")
        print("=" * 60)

        tools_by_skill: dict[str, list[dict]] = {}
        for t in self._tool_list:
            tools_by_skill.setdefault(t["skill"], []).append(t)

        for s in self._skill_list:
            name = s["name"]
            disp = s["display_name"]
            desc = s.get("description", "")
            tools = tools_by_skill.get(name, [])
            tool_names = [t["name"] for t in tools]
            print(f"\n  [{name}] {disp}")
            if desc:
                print(f"    {desc}")
            if tool_names:
                print(f"    工具: {', '.join(tool_names)}")

        skill_names = [s["name"] for s in self._skill_list if s["has_tools"]]
        if not skill_names:
            print("\n没有可用技能（无工具）。")
            return

        while True:
            print("\n" + "-" * 60)
            try:
                skill_name = _read_line(
                    f"技能名称 ({', '.join(skill_names)}) / q=退出\n> ",
                    _Completer(skill_names),
                )
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if skill_name.lower() in ("q", "quit", "exit"):
                break
            if not skill_name:
                continue
            if not self.registry.has_skill(skill_name):
                print(f"  技能 '{skill_name}' 不存在，请重新输入")
                continue

            self._debug_skill(skill_name, tools_by_skill.get(skill_name, []))

    def _debug_skill(self, skill_name: str, tools: list[dict]):
        if not tools:
            print(f"  技能 [{skill_name}] 没有注册工具")
            return

        tool_map = {t["name"]: t for t in tools}
        tool_names = list(tool_map)

        while True:
            print(f"\n  [{skill_name}] 可用工具:")
            for t in tools:
                print(f"    {t['name']} — {t.get('display_name', '')}")

            try:
                tool_name = _read_line(
                    f"\n  工具名 ({'/'.join(tool_names)} / b=返回 / q=退出)\n> ",
                    _Completer(tool_names),
                )
            except (EOFError, KeyboardInterrupt):
                return

            if tool_name.lower() in ("q", "quit", "exit"):
                sys.exit(0)
            if tool_name.lower() in ("b", "back", ""):
                return
            if tool_name not in tool_map:
                print(f"  工具 '{tool_name}' 不存在")
                continue

            spec = tool_map[tool_name]
            params = self._build_params(spec)
            if params is None:
                continue

            print(f"\n  ── 执行 {skill_name}.{tool_name} ──")
            print(f"  参数: {json.dumps(params, ensure_ascii=False)}")

            try:
                result = self.registry.call_tool(skill_name, tool_name, params)
                print(f"\n  结果:")
                self._print_result(result)
            except Exception as e:
                print(f"  [错误] {e}")

    def _build_params(self, spec: dict) -> dict | None:
        methods = spec.get("methods", [])
        params_spec = methods[0].get("parameters", {}) if methods else {}

        if not params_spec:
            print("  此工具无参数，直接调用")
            return {}

        print(f"\n  工具 [{spec['name']}] 参数定义:")
        required_params = []
        optional_params = []

        for pname, pdef in params_spec.items():
            required = pdef.get("required", False)
            desc = pdef.get("description", "")
            ptype = pdef.get("type", "string")
            (required_params if required else optional_params).append((pname, desc, ptype))

        if required_params:
            print("\n  必填参数:")
            for pname, desc, ptype in required_params:
                print(f"    {pname} ({ptype}): {desc}")
        if optional_params:
            print("\n  可选参数:")
            for pname, desc, ptype in optional_params:
                print(f"    {pname} ({ptype}): {desc}")

        print("\n  输入参数值（回车跳过可选参数，输入 s=跳过此工具）:")
        params: dict = {}

        for pname, desc, ptype in required_params + optional_params:
            is_required = (pname, desc, ptype) in required_params
            marker = " *" if is_required else ""

            try:
                value = input(f"  {pname} ({ptype}){marker}: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None

            if value.lower() in ("s", "skip"):
                return None
            if not value:
                if is_required:
                    print(f"    {pname} 是必填参数，请重新选择工具")
                    return None
                continue

            params[pname] = self._cast(value, ptype)

        return params

    @staticmethod
    def _cast(value: str, ptype: str):
        if ptype in ("int", "integer", "number"):
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value
        if ptype in ("float", "double"):
            try:
                return float(value)
            except ValueError:
                return value
        if ptype in ("bool", "boolean"):
            return value.lower() in ("true", "1", "yes", "y")
        if ptype in ("list", "array"):
            try:
                return json.loads(value)
            except Exception:
                return [x.strip() for x in value.split(",")]
        return value

    @staticmethod
    def _print_result(result):
        if isinstance(result, dict):
            for k, v in result.items():
                if k == "content" and isinstance(v, str) and len(v) > 200:
                    print(f"    {k}: {v[:200]}...")
                elif k == "images" and isinstance(v, list):
                    print(f"    {k}: [{len(v)} 张图片]")
                elif isinstance(v, list) and len(v) > 10:
                    print(f"    {k}: [{len(v)} 项]")
                else:
                    print(f"    {k}: {v}")
        elif isinstance(result, (list, tuple)):
            print(f"    [{len(result)} 项]")
            for item in result[:10]:
                print(f"      {item}")
            if len(result) > 10:
                print(f"      ... 共 {len(result)} 项")
        elif isinstance(result, str) and len(result) > 300:
            print(f"    {result[:300]}...")
        else:
            print(f"    {result}")


if __name__ == "__main__":
    SkillDebugger().run()
