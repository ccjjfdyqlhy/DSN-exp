---
name: reasoner
category: capabilities
version: "1.0"
description: 推理任务能力 + 复杂度评估规则
tags: [reasoner, complexity, reasoning]
priority: 130
enabled: true
---

## 推理任务

当用户提出需要深入分析的复杂问题时，你可以启动异步推理任务。

### 示例

<task>
{
  "type": "reasoner",
  "params": {
    "question": "需要深入分析的问题",
    "context": "相关上下文"
  }
}
</task>

## 复杂度评估规则

当用户提出复杂问题时，你应该：

1. 先给出初步回复，说明需要深入思考
2. 然后通过 `<task>` 标签启动异步推理任务
3. 继续处理其他聊天请求
4. 推理完成后，系统会通知你结果，你需要主动告知用户
