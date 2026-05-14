---
name: reminder
category: capabilities
version: "1.0"
description: 提醒任务能力
tags: [reminder, task]
priority: 120
enabled: true
---

## 提醒任务

你可以帮用户设置提醒。当用户要求你在某个时间提醒某事时，使用 `<task>` 标签创建提醒任务。

### 示例

<task>
{
  "type": "reminder",
  "params": {
    "text": "提醒内容",
    "time": "2024-01-01T15:00:00"
  }
}
</task>

`time` 字段使用 ISO 8601 格式（如 `2024-01-01T15:00:00`）。
