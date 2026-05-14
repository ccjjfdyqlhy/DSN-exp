# extensions — 用户自建提示词目录

将你自定义的 `.md` 提示词文件放在这里，启动时会被自动加载。

## 文件格式

```markdown
---
name: my_custom_prompt
category: extensions
version: "1.0"
description: 我的自定义提示词
tags: [custom]
priority: 200
enabled: true
---

你的自定义提示词内容...
```

## 示例

- 添加特定的回答风格指引
- 注入领域知识
- 设定特定的对话规则
- 覆盖默认行为

## 管理

- 通过 API `POST /api/prompts/upload` 上传新文件
- 通过 API `POST /api/prompts/<id>/toggle` 启用/禁用
- 通过 API `POST /api/prompts/reload` 热重载
