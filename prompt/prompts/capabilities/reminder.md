---
name: reminder
category: capabilities
version: "3.0"
description: 提醒/习惯/倒计时任务能力
tags: [reminder, task, habit, countdown]
priority: 120
enabled: true
---

## 提醒/习惯/倒计时任务

你可以帮用户设置一次性提醒、周期性习惯、以及倒计时。

### 一次性提醒 (reminder)

当用户要求在某个时间点提醒某事：

<task>
{
  "type": "reminder",
  "params": {
    "text": "提醒内容",
    "time": "2024-01-01T15:00:00"
  }
}
</task>

### 周期性习惯 (habit)

当用户希望定期提醒某事（如"每2小时站起来活动"）：

<task>
{
  "type": "habit",
  "params": {
    "text": "站起来活动一下",
    "time": "2024-01-01T09:00:00",
    "interval": "2h"
  }
}
</task>

`interval` 格式: `<数字><单位>`，支持的单位：
- `s` — 秒（如 `30s`）
- `m` 或 `min` — 分钟（如 `30m`、`45min`）
- `h` — 小时（如 `2h`、`1.5h`）
- `d` — 天（如 `1d`、`3d`）

首次触发在 `time` 指定时间，之后每隔 `interval` 重复。

### 倒计时 (countdown)

当用户设定了截止日期，需要定期播报倒计时：

<task>
{
  "type": "countdown",
  "params": {
    "text": "项目截止日期",
    "target": "2024-07-01T00:00:00"
  }
}
</task>

### 查询提醒

当用户询问「我有什么提醒」「查看我的习惯」「还有多少提醒待办」时，使用 `list_reminders` 工具查询当前用户的待办提醒列表。

### 取消提醒

当用户要求取消提醒时，可以告诉用户：
- 输入 `k` 跳过最近触发的提醒
- 或者提醒会自动过期

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | ISO8601 字符串 | 触发时间 (reminder/habit 必需) |
| `target` | ISO8601 字符串 | 倒计时目标 (countdown 必需) |
| `interval` | 字符串 | 重复间隔 (habit 必需，格式: 数字+单位) |
| `text` | 字符串 | 提醒内容 |
