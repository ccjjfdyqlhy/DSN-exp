#!/usr/bin/env python3
# agent_send.py — DSN-exp AI Agent 消息发送接口
#
# 供 OpenClaw 等本地 AI Agent 通过单一 Parsed 指令与 DSN-exp 主 AI 对话。
# 消息直接写在命令行参数中，Agent 框架解析后执行即可。
#
# 密钥来源（优先级）:
#   1. ~/.dsn/agent.key             文件权限 chmod 600（推荐，最安全）
#   2. DSN_AGENT_API_KEY 环境变量   兼容 CI/CD 场景
#
# 环境变量:
#   DSN_BASE_URL         DSN-exp 服务地址（默认 http://localhost:5000）
#   DSN_AGENT_TIMEOUT    请求超时秒数（默认 300）
#
# 用法 (消息来源优先级: 参数 > 环境变量 > stdin):
#   方式1 — Parsed 指令（推荐，适合 AI Agent 框架）：
#     python agent_send.py "你好，帮我查一下darkstar的日程"
#
#   方式2 — 环境变量：
#     DSN_MESSAGE="你好" python agent_send.py
#
#   方式3 — 管道：
#     echo "你好" | python agent_send.py
#
#   OpenClaw / Claude Code / CodeAct 等 Agent 配置示例：
#     AI 生成指令 → 框架执行 → stdout 返回回复
#     python agent_send.py "{{你想对DSN-exp主AI说的话}}"
#
# 密钥配置（首次使用）:
#   mkdir -p ~/.dsn && chmod 700 ~/.dsn
#   echo "dsn_apk_your_key_here" > ~/.dsn/agent.key
#   chmod 600 ~/.dsn/agent.key

import os
import sys
import json

# ── 密钥来源: 文件(安全) > 环境变量 ──
_KEY_FILE = os.path.expanduser("~/.dsn/agent.key")
API_KEY = ""

if os.path.isfile(_KEY_FILE):
    try:
        with open(_KEY_FILE) as f:
            API_KEY = f.read().strip()
    except (OSError, IOError):
        pass

if not API_KEY:
    API_KEY = os.environ.get("DSN_AGENT_API_KEY", "")

BASE_URL = os.environ.get("DSN_BASE_URL", "http://localhost:5000").rstrip("/")
TIMEOUT = int(os.environ.get("DSN_AGENT_TIMEOUT", "300"))

# ── 消息来源: 优先级 参数 > 环境变量 > stdin ──
if len(sys.argv) > 1:
    MESSAGE = " ".join(sys.argv[1:])
elif os.environ.get("DSN_MESSAGE"):
    MESSAGE = os.environ["DSN_MESSAGE"]
else:
    MESSAGE = sys.stdin.read().strip()

if not API_KEY:
    print("错误: 未找到 API Key", file=sys.stderr)
    print("请将密钥写入 ~/.dsn/agent.key (推荐) 或设置 DSN_AGENT_API_KEY 环境变量", file=sys.stderr)
    sys.exit(1)

if not MESSAGE:
    print("错误: 未提供消息内容", file=sys.stderr)
    print("用法: python agent_send.py \"你的消息\"", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    import urllib.request
    req = urllib.request.Request(
        f"{BASE_URL}/api/agent/send",
        data=json.dumps({"message": MESSAGE}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-DSN-API-Key": API_KEY,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"错误: 请求失败 — {e}", file=sys.stderr)
        sys.exit(1)
else:
    try:
        resp = requests.post(
            f"{BASE_URL}/api/agent/send",
            headers={
                "Content-Type": "application/json",
                "X-DSN-API-Key": API_KEY,
            },
            json={"message": MESSAGE},
            timeout=TIMEOUT,
        )
        data = resp.json()
    except Exception as e:
        print(f"错误: 请求失败 — {e}", file=sys.stderr)
        sys.exit(1)

if "error" in data:
    print(f"错误: {data['error']}", file=sys.stderr)
    sys.exit(1)

print(data.get("reply", ""))
