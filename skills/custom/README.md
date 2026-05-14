# 自定义技能目录

## 如何创建自定义技能

1. 在此目录下创建新的子目录，如 `my_skill/`
2. 在子目录中创建 `skill.yaml`（技能元数据）
3. 创建 `prompts/` 子目录，放入 `.md` 提示词文件
4. （可选）创建 `tools/` 子目录，放入 `.py` 工具代码

## 技能目录结构

```
skills/custom/my_skill/
├── skill.yaml              # 技能元数据 (必需)
├── prompts/
│   ├── instruction.md      # 使用说明 (推荐)
│   └── examples.md         # 使用示例 (可选)
└── tools/                  # 工具代码 (可选)
    └── main.py
```

## skill.yaml 格式

```yaml
name: my_skill
display_name: "我的技能"
description: "技能描述"
version: "1.0"
author: "user"
source: "custom"
enabled: true
status: "active"
prompt_priority: 70

tools:
  - name: my_tool
    display_name: "我的工具"
    description: "工具描述"
    module: "tools.main"
    class: "MyTool"
    methods:
      - name: my_method
        description: "方法描述"
        parameters:
          param1:
            type: string
            description: "参数1"
            required: true

activation:
  keywords: ["关键词1", "关键词2"]
  auto_activate: false

dependencies: []
tags: [custom]
```

## 提示词文件格式

```markdown
---
name: my_skill_instruction
category: skills
priority: 70
---

## 我的技能

技能的具体使用说明...
```
