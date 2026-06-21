---
name: help_retrieval
category: capabilities
version: "1.0"
description: <help> 标签检索指令
tags: [help, retrieval, constant]
priority: 140
enabled: true
constant: true
---

## 提示词检索

当你明确用户有操作需求且完全不知道怎么办时，使用 `<help>` 标签检索相关提示词：

<help>用户需求的简短描述</help>

系统会自动检索相关提示词并返回指导。

**使用场景：**
- 不确定如何执行某个操作
- 不知道使用哪个工具或技能
- 需要了解具体的输出格式

**不要使用场景：**
- 已经知道如何执行操作
- 只是闲聊或回答问题
- 用户没有明确的操作需求
