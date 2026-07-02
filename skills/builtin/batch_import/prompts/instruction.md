# 批量导入题目 Skill

你可以用本技能一次将多道结构化题目批量导入题库。支持先预览再确认，避免错误入库。

## 使用场景

1. **试卷批量录入** — 用户说"帮我把这 10 道题录入题库"，你先在脑中/回复中整理成结构化数组，然后一把导入
2. **从其他系统迁移** — 从 JSON/CSV 等格式批量导入大量题目
3. **AI 生成题目** — 用户说"帮我出 5 道初二物理摩擦力选择题"，你先生成题目文本，再用本技能结构化导入

## 用法

### 方式一：直接 commit 入库

```json
{
  "questions": [
    {
      "subject": "physics",
      "content": "……",
      "answer": "……",
      "type_name": "选择题",
      "subtype": "单选",
      "options": ["A. ……", "B. ……"],
      "difficulty": 3,
      "explanation": "……",
      "knowledge_points": ["摩擦力"]
    }
  ],
  "mode": "commit"
}
```

### 方式二：dry_run 预览 → 确认

**第一步**：先预览，不入库

```json
{
  "questions": [...],
  "mode": "dry_run"
}
```

返回 preview 列表和解析统计，让用户确认。

**第二步**：用户确认后，再用 `mode: "commit"` 正式导入。

或者你也可以直接 commit 并向用户汇报结果，如果用户要求先预览再看。

## 参数说明

| 参数 | 说明 |
|---|---|
| `questions` | 题目数组，**必填**。每道题支持 content(必填), answer(必填), subject, type_name, subtype, difficulty, options, explanation, knowledge_points, tags |
| `subject` | 默认学科代码。如果 questions 中某题未指定 subject，则使用此值 |
| `mode` | `"commit"`(直接入库) 或 `"dry_run"`(仅预览) |

## 注意

- 如果题目来源是**自由文本**（非结构化），应先用 `text_extract` 技能提取预览
- 如果题目来源是**图片**，应先用 `quest_from_image` 技能
- 如果只有**一道题**需要录入，也可以使用本技能（questions 传一条即可），或 `quick_question` 技能
