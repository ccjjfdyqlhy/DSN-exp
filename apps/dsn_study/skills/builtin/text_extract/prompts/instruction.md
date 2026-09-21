# 文本提取题目 Skill

你可以用本技能从一段自由文本中自动识别所有题目。支持"先预览再入库"的两步流程，避免误入库。

## 使用场景

1. **粘贴文本** — 用户从网页/文档复制了一段包含题目的文本，说"帮我把这些题录入"
2. **OCR 结果处理** — 用户从 document 技能拿到 OCR 文本，想提取其中的题目
3. **整理笔记** — 用户手写的题目笔记，想结构化存入题库

## 推荐流程

### 两步走（预览 → 确认）

**第一步：`extract_preview` — 提取题目，返回预览**

```json
{
  "text": "1. 地球绕太阳运动的轨道是？\nA. 圆形 B. 椭圆形 C. 抛物线 D. 双曲线\n答案: B",
  "subject": "physics"
}
```

返回 `raw_questions` 数组和 `questions` 摘要。

**第二步：`confirm_import` — 确认入库**

```json
{
  "questions": <直接传入上一步的 raw_questions>,
  "subject": "physics"
}
```

### 也可一步到位

如果用户明确要求直接入库，你也可以直接先用 `extract_preview` 提取，得到结果后立即调 `confirm_import`。但建议至少让用户看一眼预览结果。

## 参数说明

### extract_preview

| 参数 | 说明 |
|---|---|
| `text` | 包含题目的文本内容，**必填** |
| `subject` | 学科代码，默认 `math` |

### confirm_import

| 参数 | 说明 |
|---|---|
| `questions` | 从 `extract_preview` 返回的 `raw_questions`，**必填** |
| `subject` | 学科代码，默认 `math` |

## 注意

- 本技能依赖 LLM 提取题目，文本越长提取越慢。超大文本建议分段处理
- 提取结果中的 content/answer 会被原样入库，建议用户确认内容完整性
- 如果用户提供的是**结构化 JSON 数据**（非自由文本），应改用 `batch_import` 技能
- 如果用户提供的是**图片**，应改用 `quest_from_image` 技能
