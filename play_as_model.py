#!/usr/bin/env python3
"""
play_as_model.py — DEBUG_PLAY_AS_MODEL 交互式 CLI 前端

让开发者/测试者分饰"用户"和"AI模型"两角，完整测试管线流程。
支持交互式技能/工具选择，以及 /skip 等调试指令。

用法:
    python play_as_model.py [--port PORT] [--host HOST]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import uuid
from datetime import datetime


# ── HTTP 请求封装 ──

def _request(method: str, url: str, data: dict = None) -> dict:
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"  [HTTP {e.code}] {err_body}")
        return {"error": str(e)}
    except urllib.error.URLError as e:
        print(f"  [连接失败] {e.reason}")
        return {"error": str(e)}


# ── 交互式前端 ──

BANNER = r"""
╔══════════════════════════════════════════════════╗
║         DEBUG  PLAY-AS-MODEL  MODE              ║
║     分饰两角 · 完整管线流程测试                   ║
╚══════════════════════════════════════════════════╝
"""


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    codes = {
        "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
        "red": "\033[31m", "blue": "\033[34m", "dim": "\033[2m",
        "bold": "\033[1m", "reset": "\033[0m",
    }
    return f"{codes.get(code, '')}{text}{codes['reset']}"


def _print_divider(char: str = "─", color: str = "dim"):
    print(_color(char * 56, color))


def _print_role(role: str, color: str):
    print(f"\n{_color(f'── [{role}] ', color)}{_color(datetime.now().strftime('%H:%M:%S'), 'dim')}")
    _print_divider("─", "dim")


class PlayAsModelCLI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session_id = f"cli_{uuid.uuid4().hex[:16]}"
        self.role: str = "user"
        self.current_reply: list[str] = []
        self.current_tool_calls: list[dict] = []
        self.history: list[dict] = []
        self.chat_id: int | None = None
        self.user_id: int = 1
        self._skills_cache: list[dict] | None = None

    # ── 技能浏览器 ──

    def _load_skills(self) -> list[dict]:
        if self._skills_cache is not None:
            return self._skills_cache
        url = f"{self.base_url}/debug/skills"
        resp = _request("GET", url)
        self._skills_cache = resp.get("skills", [])
        return self._skills_cache

    def _show_skills(self):
        skills = self._load_skills()
        if not skills:
            print("  (无可用技能)")
            return
        by_skill: dict[str, list[dict]] = {}
        for s in skills:
            by_skill.setdefault(s["skill"], []).append(s)

        for skill_name, tools in sorted(by_skill.items()):
            print(f"  {_color(f'■ {skill_name}', 'cyan')} ({len(tools)} 工具)")
            for t in tools:
                extra = _color(" [async]", "yellow") if t.get("async") else ""
                print(f"    {t['name']}{extra} — {t.get('display_name', '')}")
                desc = t.get("description", "")
                if desc:
                    print(f"      {_color(desc[:100], 'dim')}")

    def _show_tool_schema(self, skill: str, tool: str):
        skills = self._load_skills()
        for s in skills:
            if s["skill"] == skill and s["name"] == tool:
                params = s.get("parameters", {})
                required = params.get("required", [])
                props = params.get("properties", {})
                print(f"  {_color('参数:', 'bold')}")
                for pname, pinfo in props.items():
                    req = _color(" (必填)", "red") if pname in required else ""
                    ptype = pinfo.get("type", "string")
                    pdesc = pinfo.get("description", "")
                    print(f"    {pname} [{ptype}]{req}")
                    if pdesc:
                        print(f"      {_color(pdesc[:80], 'dim')}")
                return
        print(f"  {_color(f'工具 {skill}.{tool} 未找到', 'red')}")

    # ── 工具交互选择 ──

    def _interactive_tool_select(self, cmd: str):
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            print(f"  用法: /tool <工具名>")
            print(f"  可用工具: /skills 查看")
            return

        tool_name = parts[1].strip()
        skills = self._load_skills()
        candidates = [s for s in skills if s["name"] == tool_name]

        if not candidates:
            print(f"  {_color(f'未找到工具: {tool_name}', 'red')}")
            return

        if len(candidates) > 1:
            print(f"  找到多个匹配，请选择:")
            for i, c in enumerate(candidates):
                print(f"  [{i}] {c['skill']}.{c['name']}")
            try:
                idx = int(input("  > ").strip())
                selected = candidates[idx]
            except (ValueError, IndexError):
                print(f"  {_color('无效选择', 'red')}")
                return
        else:
            selected = candidates[0]

        skill = selected["skill"]
        name = selected["name"]
        params = selected.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])

        print(f"  {_color(f'工具: {skill}.{name}', 'cyan')}")
        desc = selected.get("description", "")
        if desc:
            print(f"  {_color(desc[:120], 'dim')}")

        args = {}
        for pname, pinfo in props.items():
            is_req = pname in required
            prompt = f"    {pname} ({pinfo.get('type', 'string')})"
            if is_req:
                prompt += _color(" *", "red")
            prompt += ": "
            val = input(prompt).strip()
            if val or is_req:
                ptype = pinfo.get("type", "string")
                try:
                    if ptype == "integer":
                        val = int(val)
                    elif ptype == "number":
                        val = float(val)
                    elif ptype == "boolean":
                        val = val.lower() in ("true", "1", "yes")
                except ValueError:
                    pass
                args[pname] = val

        confirm = input(f"  {_color('确认添加此工具调用? [Y/n] ', 'yellow')}").strip().lower()
        if confirm and confirm not in ("y", "yes", ""):
            print(f"  {_color('已取消', 'dim')}")
            return

        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": f"skill-{skill}-{name}",
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }
        self.current_tool_calls.append(tool_call)
        print(f"  {_color('✓ 已添加到当前回复', 'green')}")

    # ── 上下文预览 ──

    def _show_context(self, context: dict):
        sp = context.get("system_prompt", "")
        msg = context.get("message", "")
        hc = context.get("history_count", 0)
        print(f"\n  {_color('系统提示词:', 'bold')} {len(sp)} 字符")
        print(f"  {_color('用户消息:', 'bold')} {msg[:80]}{'...' if len(msg) > 80 else ''}")
        print(f"  {_color('历史消息:', 'bold')} {hc} 条")
        if sp:
            show = input(f"  显示完整系统提示词? [y/N] ").strip().lower()
            if show in ("y", "yes"):
                print(f"\n{_color('─' * 56, 'dim')}")
                print(sp)
                print(f"{_color('─' * 56, 'dim')}")

    # ── 核心循环 ──

    def run(self):
        print(_color(BANNER, "cyan"))
        print(f"  后端: {self.base_url}")
        print(f"  会话: {self.session_id}")
        print(f"  指令: {_color('/help', 'yellow')} 查看可用命令")
        print()

        while True:
            try:
                if self.role == "user":
                    self._user_turn()
                else:
                    self._model_turn()
            except KeyboardInterrupt:
                print(f"\n{_color('使用 /exit 退出', 'yellow')}")
            except Exception as e:
                print(f"\n{_color(f'错误: {e}', 'red')}")

    def _user_turn(self):
        _print_role("用户", "green")
        line = input("> ").strip()

        if not line:
            return

        if line.startswith("/"):
            self._handle_user_command(line)
            return

        # 发送消息
        self._last_user_msg = line
        self.current_reply = []
        self.current_tool_calls = []
        _print_role("系统", "blue")
        print(f"  {_color('正在处理 PRE_PROCESS...', 'yellow')}")

        url = f"{self.base_url}/debug/chat"
        resp = _request("POST", url, {
            "session_id": self.session_id,
            "message": line,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "history": self.history,
        })

        if resp.get("error"):
            print(f"  {_color(f'请求失败: {resp["error"]}', 'red')}")
            return

        if resp.get("filtered"):
            print(f"  {_color('请求被 PRE_FILTER 拦截', 'red')}")
            self.role = "user"
            return

        context = resp.get("context", {})
        skills = resp.get("skills", [])
        self.chat_id = context.get("chat_id", self.chat_id)
        self.session_id = resp.get("session_id", self.session_id)

        print(f"  {_color('PRE_PROCESS 完成 ✓', 'green')}")
        print(f"  system_prompt: {len(context.get('system_prompt', ''))} 字符")
        print(f"  可用技能: {len(skills)} 个工具")

        # 切换到模型角色
        self.role = "model"
        self._show_context(context)

    def _model_turn(self):
        _print_role("你 = 模型", "cyan")
        print(f"  {_color('可用指令: /skills /tool <名> /context /skip /done /exit', 'dim')}")

        line = input("> ").strip()

        if not line:
            return

        if line.startswith("/"):
            self._handle_model_command(line)
            return

        self.current_reply.append(line)

    def _handle_user_command(self, cmd: str):
        if cmd in ("/exit", "/quit"):
            print(f"\n{_color('退出调试模式。', 'yellow')}")
            sys.exit(0)
        elif cmd == "/help":
            self._print_help()
        elif cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
        else:
            print(f"  {_color(f'未知指令: {cmd} (用户角色)', 'red')}")
            print(f"  可用: /help /clear /exit")

    def _handle_model_command(self, cmd: str):
        if cmd == "/skip":
            print(f"  {_color('跳过模型回复，切换回用户角色', 'yellow')}")
            prev_role = self.role
            self._submit_reply()
            if self.role == prev_role:
                self.role = "user"
        elif cmd == "/done":
            self._submit_reply()
        elif cmd == "/skills":
            self._show_skills()
        elif cmd.startswith("/tool "):
            self._interactive_tool_select(cmd)
        elif cmd.startswith("/tool"):
            print(f"  {_color('用法: /tool <工具名>', 'yellow')}")
        elif cmd == "/context":
            print(f"  {_color('上下文信息在上次 PRE_PROCESS 时已显示', 'dim')}")
        elif cmd == "/help":
            self._print_model_help()
        elif cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
        elif cmd in ("/exit", "/quit"):
            print(f"\n{_color('退出调试模式。', 'yellow')}")
            sys.exit(0)
        elif cmd.startswith("/schema "):
            parts = cmd.split(maxsplit=2)
            if len(parts) >= 3:
                self._show_tool_schema(parts[1], parts[2])
            else:
                print(f"  {_color('用法: /schema <skill> <tool>', 'yellow')}")
        else:
            print(f"  {_color(f'未知指令: {cmd}', 'red')}")

    def _submit_reply(self):
        full_reply = "\n".join(self.current_reply).strip()
        if not full_reply and not self.current_tool_calls:
            print(f"  {_color('回复为空，跳过', 'dim')}")
            return

        _print_role("系统", "blue")
        print(f"  {_color('正在执行 POST_PROCESS...', 'yellow')}")

        url = f"{self.base_url}/debug/respond"
        resp = _request("POST", url, {
            "session_id": self.session_id,
            "reply": full_reply,
            "tool_calls": self.current_tool_calls if self.current_tool_calls else None,
        })

        if resp.get("error"):
            print(f"  {_color(f'请求失败: {resp["error"]}', 'red')}")
            return

        status = resp.get("status", "completed")
        step = resp.get("step", 0)
        max_steps = resp.get("max_steps", 0)
        tool_results = resp.get("tool_results", [])

        if tool_results:
            print(f"\n  {_color('── 工具执行结果 ──', 'yellow')}")
            for r in tool_results:
                func_name = r.get("function", "?")
                ok = r.get("success", False)
                icon = _color("✓", "green") if ok else _color("✗", "red")
                data = r.get("data") or r.get("error") or ""
                data_str = json.dumps(data, ensure_ascii=False, default=str)
                if len(data_str) > 200:
                    data_str = data_str[:200] + "..."
                print(f"  {icon} {func_name}: {data_str}")

        final_reply = resp.get("reply", "")
        filtered = resp.get("filtered", False)

        if filtered:
            print(f"  {_color('请求被管线拦截', 'red')}")
        else:
            print(f"  {_color('POST_PROCESS 完成 ✓', 'green')}")

        if status == "await_agent_step":
            if final_reply:
                print(f"\n  {_color('[当前回复]', 'bold')}")
                for line in final_reply.split("\n"):
                    print(f"  {line}")
            print(f"\n  {_color(f'── Agent Loop 步骤 {step}/{max_steps} —— 需要你提供下一步回复 ──', 'yellow')}")
            print(f"  {_color('工具执行结果已显示在上方。请以模型身份继续回复，或 /done 结束。', 'dim')}")
            self.current_reply = []
            self.current_tool_calls = []
            # 保持 model 角色
            return

        # 处理完成
        if final_reply:
            print(f"\n  {_color('[最终回复]', 'bold')}")
            for line in final_reply.split("\n"):
                print(f"  {line}")

        # 记录历史
        self.history.append({"role": "user", "content": self.current_reply_text or ""})
        self.history.append({"role": "assistant", "content": final_reply or ""})
        if len(self.history) > 100:
            self.history = self.history[-100:]

        self.current_reply = []
        self.current_tool_calls = []
        self.role = "user"

    @property
    def current_reply_text(self) -> str:
        return getattr(self, "_last_user_msg", "")

    @current_reply_text.setter
    def current_reply_text(self, val: str):
        self._last_user_msg = val

    # ── 帮助 ──

    def _print_help(self):
        print(f"""
  {_color('可用命令 (用户角色):', 'bold')}
    /help         显示此帮助
    /clear        清屏
    /exit         退出

  {_color('输入任意消息将发送给系统处理', 'dim')}
  {_color('处理完成后自动切换到模型角色', 'dim')}
""")

    def _print_model_help(self):
        print(f"""
  {_color('可用命令 (模型角色):', 'bold')}
    /skills       浏览所有可用技能和工具
    /tool <名>    选择工具并交互式填写参数
    /schema <s> <t>  查看工具参数定义
    /context      显示当前上下文概览
    /skip         跳过回复，切换回用户角色
    /done         提交回复，切换回用户角色
    /clear        清屏
    /exit         退出

  {_color('直接输入文本将拼接到当前模型回复中', 'dim')}
  {_color('使用多个 /tool 添加多个工具调用', 'dim')}
  {_color('最后用 /done 提交整个回复', 'dim')}
""")


def main():
    parser = argparse.ArgumentParser(description="DSN-exp Play-As-Model CLI")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DEBUG_PLAY_AS_MODEL_PORT", "5050")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    cli = PlayAsModelCLI(base_url)
    cli.run()


if __name__ == "__main__":
    main()
