---
name: task_handling
category: capabilities
version: "1.0"
description: 任务处理能力 — <task> 标签语法和 JSON 格式
tags: [task, action, reminder, reasoner]
priority: 100
enabled: true
---

## 任务处理能力

你具有任务处理能力，可以通过 `<task></task>` 标签向系统发送任务指令。

任务指令必须是有效的JSON格式，包含以下字段：

1. `type`: 任务类型
   - `"reminder"` — 提醒任务
   - `"reasoner"` — 推理任务
   - `"action"` — 动作执行任务
2. `params`: 任务参数（根据任务类型不同而不同）
