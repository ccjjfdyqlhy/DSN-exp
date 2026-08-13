#!/usr/bin/env python3
# safe_backup.py — 手动触发系统备份
# 用法: python safe_backup.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apps.dsn.maintenance.tasks.backup import BackupTask

task = BackupTask()
result = task.run(lambda p: None)
print(f"\n✅ 备份完成: {result['stats']['dir']}")
for item in result['stats']['copied']:
    print(f"   📄 {item}")
if result['stats']['compressed']:
    print(f"   📦 {result['stats']['compressed']}")
