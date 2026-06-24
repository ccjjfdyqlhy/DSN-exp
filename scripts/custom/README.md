# 自定义剧本

在此目录下创建 `.md` 文件即可添加自定义剧本。

## 文件格式

剧本文件使用 Markdown + YAML frontmatter：

```markdown
---
name: "my_script"
display_name: "我的剧本"
description: "剧本描述"
version: "1.0"
mode: "guide"

settings:
  ooc_strictness: 0.8
  recordable: true

chapters:
  - id: "step1"
    name: "第一步"
    guidance: |
      引导文本...
    key_points:
      - id: "done"
        condition: "user_affirms()"
        weight: 1.0
    transitions:
      - to: "step2"
        condition: "done >= 1.0"

  - id: "step2"
    name: "第二步"
    is_ending: true
---

正文内容（注入 AI 的 system prompt 前部）
```

## 可用条件函数

- `ai_mentions(text)` — AI 回复中包含指定文本
- `user_mentions(text)` — 用户输入中包含指定文本
- `user_affirms()` — 用户表示肯定
- `user_declines()` — 用户表示否定
- `user_requests_action()` — 用户请求执行操作
- `tool_used(name)` — AI 调用了指定工具
- `config.check(key)` — 检查配置项
- `true` / `false` — 常量