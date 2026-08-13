#!/usr/bin/env python3
"""一键重置脚本 — 清除所有用户数据"""

import os
import sys
import shutil

_APP = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(_APP)))

TARGETS = [
    ("主数据库", os.path.join(BASE, "DSN_usrdata.db")),
    ("聊天数据库", os.path.join(BASE, "chats.db")),
    (".dsn 目录", os.path.join(BASE, ".dsn")),
    ("客户端密钥", os.path.join(_APP, "psychoscope", ".dsn_client.json")),
]

print("⚠ 即将永久删除以下数据：")
print()
for name, path in TARGETS:
    exists = os.path.isfile(path) or os.path.isdir(path)
    status = "存在" if exists else "不存在"
    print(f"  [{status}] {name}: {os.path.relpath(path, BASE)}")

print()
try:
    reply = input("确认删除？此操作不可恢复 (yes/no): ").strip().lower()
except (EOFError, KeyboardInterrupt):
    print()
    sys.exit(1)

if reply != "yes":
    print("已取消")
    sys.exit(0)

for name, path in TARGETS:
    if not os.path.exists(path):
        print(f"  跳过 {name}：不存在")
        continue
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        print(f"  ✓ 已删除 {name}")
    except Exception as e:
        print(f"  ✗ 删除 {name} 失败: {e}")
        sys.exit(1)

print()
print("重置完成。所有用户数据已清除。")
