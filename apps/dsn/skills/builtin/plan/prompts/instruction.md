---
name: plan_instruction
category: skills
priority: 70
---

## 计划系统技能

你可以通过 `<tool>` 标签管理目标和每日计划。

### 创建目标并拆解

**创建大目标：**
<tool>
{
  "skill": "plan",
  "tool": "create_goal",
  "params": {"title": "完成 XX 项目", "deadline": "2027-06-07"}
}
</tool>

**添加阶段：**
<tool>
{
  "skill": "plan",
  "tool": "add_phase",
  "params": {"goal_id": "xxx", "title": "第一阶段", "start_date": "2026-06-20", "end_date": "2026-08-31"}
}
</tool>

**查看所有目标：**
<tool>
{
  "skill": "plan",
  "tool": "list_goals",
  "params": {}
}
</tool>

### 每日任务

**生成今日计划：**
<tool>
{
  "skill": "plan",
  "tool": "generate_daily_plan",
  "params": {}
}
</tool>

### 追踪进度

**完成任务：**
<tool>
{
  "skill": "plan",
  "tool": "check_off",
  "params": {"task_id": "xxx"}
}
</tool>

**跳过任务：**
<tool>
{
  "skill": "plan",
  "tool": "skip_task",
  "params": {"task_id": "xxx"}
}
</tool>

**查看今日统计：**
<tool>
{
  "skill": "plan",
  "tool": "daily_summary",
  "params": {}
}
</tool>
