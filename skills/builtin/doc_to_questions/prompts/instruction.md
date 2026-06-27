---
name: doc_to_questions_instruction
category: skills
priority: 72
---

## 文档录入题库技能

你可以将已处理的扫描文档或原始文本中的题目批量提取并录入题库系统。

### 使用场景

1. **从扫描文档（.hmd）录入** — 用户扫描试卷后，先用 `document` 技能的 `process_scan` 处理 → 再调 `read_hmd` 获取文本 → 最后用本技能的 `process_hmd` 提取题目入库
2. **从原始文本录入** — 用户直接粘贴题目文本，调用 `process_text` 提取入库

### 录入题库

**从 .hmd 文件提取题目：**
<tool>
{
  "skill": "doc_to_questions",
  "tool": "process_hmd",
  "params": {
    "hmd_path": "/path/to/document.hmd",
    "subject_code": "math"
  }
}
</tool>

**从原始文本提取题目：**
<tool>
{
  "skill": "doc_to_questions",
  "tool": "process_text",
  "params": {
    "text": "1. 题目内容... 2. 题目内容...",
    "subject_code": "physics"
  }
}
</tool>

### 完整流程（扫描 → 录入）

1. 扫描文档 → `document.scan` 获取图片
2. 图片 → `document.process_scan` 获得 .hmd 文件路径
3. .hmd → `doc_to_questions.process_hmd` 提取题目 → 自动入库
4. 或：先用 `document.read_hmd` 读取内容让用户确认，再调 `process_text` 录入

### 注意

- 录入后 AI 会自动调用 LLM 从文本中识别每道题的内容、答案、题型、难度等
- 提取结果包含：找到题目数、成功入库数、失败数
