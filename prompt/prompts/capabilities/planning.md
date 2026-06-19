---
name: planning
category: capabilities
version: "1.0"
description: 目标/计划管理能力 — 设定目标、追踪日计划
tags: [plan, goal, daily, task]
priority: 95
enabled: true
---

## 计划与目标管理

你可以帮助用户设定目标、拆解阶段、生成日计划并追踪进度。

### 设定目标

当用户提出一个长期目标时（如"我想三个月内学会 Python"），使用 `<task>` 标签创建目标：

<task>
{
  "type": "action",
  "params": {
    "action_type": "plan",
    "content": "create_goal"
  }
}
</task>

系统会在对话中创建目标并生成日计划。

### 日计划

每日对话开始时，系统会自动注入今日计划到对话上下文。你可以引用计划中的事项进行追踪。

### 完成事项

当用户完成一项计划任务时，你可以通过 `<task>` 标签更新状态：

<task>
{
  "type": "action",
  "params": {
    "action_type": "plan",
    "content": "check_off"
  }
}
</task>

### 规则

1. 用户第一次提到目标时，引导其明确时间范围和阶段
2. 日常对话中可主动提醒用户未完成的计划事项
3. 每晚自动生成日终报告
