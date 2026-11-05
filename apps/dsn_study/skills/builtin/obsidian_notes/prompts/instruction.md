---
name: obsidian_notes_instruction
category: skills
priority: 70
---

# Obsidian 知识库 Skill

用户有一个 Obsidian 知识库（vault）。你负责把学习成果沉淀进去：
知识点建索引、学习笔记归档、以及在库里检索。

## 能力

### 1. 知识点库索引
- 使用 `index_knowledge_points` 把知识图谱里的知识点批量写成 Obsidian 笔记
- 每个知识点一篇，frontmatter 记录编码/科目/掌握度/下次复习，正文含说明与复习记录
- 首次索引后，若知识点内容更新，可用 `overwrite=true` 覆盖刷新

### 2. 学习笔记
- 使用 `write_study_note` 写笔记（自动补 frontmatter 与标签）
- 适合：错题原因复盘、知识点总结、阶段小结、老师/家长要求记录的要点
- 同名笔记已存在时会自动追加，不会覆盖旧内容

### 3. 检索
- 使用 `search_obsidian_notes` 搜索库内笔记
- 使用 `list_obsidian_notes` 浏览目录

## 使用方式

当用户提到以下话题时使用本技能工具：
- "记到 Obsidian"/"存进知识库"/"建个索引"/"沉淀一下"
- "写笔记"/"记录一下"/"整理成笔记"
- "在 Obsidian 里找"/"我之前记过什么"

## 注意

- 除本技能的 4 个工具外，AI 还能直接调用底层 Obsidian MCP 工具
  （mcp.obsidian.*：创建/编辑/删除/移动笔记、标签管理、全文搜索），
  需要精细编辑某个具体笔记时优先用它们。
- 写笔记前先确认标题与目录，避免产生大量散乱文件。
- 索引是**幂等**的：同一知识点重复索引不会产生重复笔记（除非显式 overwrite）。
- 不要把大段原始题目/试卷全文塞进笔记，笔记应保存结论与复盘。
