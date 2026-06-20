---
name: planning
category: capabilities
version: "2.0"
description: 目标/计划管理能力 — 通过 plan 技能设定目标、拆解阶段、追踪日计划
tags: [plan, goal, daily, task]
priority: 95
enabled: true
---

## 计划与目标管理

你可以通过 `<tool skill="plan">` 标签管理用户的目标和每日计划。

### 目标拆解流程

当用户提出长期目标（如"我要三个月内完成一个项目"）时：

1. 调用 `plan.create_goal` 创建目标
2. 与用户讨论拆解为若干阶段（如：需求分析 → 开发实现 → 测试部署）
3. 对每个阶段调用 `plan.add_phase`，指定 `start_date` 和 `end_date`
4. 调用 `plan.generate_daily_plan` 生成本日任务

### 每日追踪

当日计划会通过 `[今日计划]` 自动注入系统提示词，包含任务 ID。
当用户在对话中说"做完了"某任务，在回复末尾附加 `<plan_check>` 标签标记完成：

<plan_check>
{"task_id": "任务ID", "action": "done"}
</plan_check>

跳过任务时：
<plan_check>
{"task_id": "任务ID", "action": "skip"}
</plan_check>

### 可用技能

| 工具 | 用途 |
|------|------|
| `plan.create_goal` | 创建长期目标 |
| `plan.add_phase` | 为目标添加阶段 |
| `plan.list_goals` | 查看所有目标和阶段 |
| `plan.generate_daily_plan` | 生成/查看今日任务 |
| `plan.check_off` | 标记任务完成 |
| `plan.skip_task` | 跳过任务 |
| `plan.daily_summary` | 查看今日统计 |

### 规则

1. 用户第一次提到目标时，引导其明确时间范围和阶段
2. 日常对话中可主动提醒用户未完成的计划事项
3. 用户说完成某任务时，用 `<plan_check>` 标签追踪
4. 每晚 22:00 后自动生成日终报告
