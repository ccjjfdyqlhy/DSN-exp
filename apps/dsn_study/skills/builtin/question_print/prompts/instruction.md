# 出题打印 Skill

你可以在用户要求「出题打印」「打一份卷子」「打印练习题」等时，使用 `question_print.print_paper` 工具。

## 使用流程

1. **确认需求**：学科、题数、难度、是否要答案。未指定时用默认值（数学、10 题、难度 3、不带答案）。
2. **选择题目来源**：
   - 直接组卷：只需传 `subject` + `count`，工具会从题库自动挑选题目。
   - AI 自出题：先自己在对话里拟好题目，再以 `questions` 列表传入（每题含 content/options/answer/explanation/type_name）。此时忽略 count/difficulty。
   - 题库检索 + 打印：先用 `question_bank.search_questions` 查题，把结果对象列表传给 `questions`。
3. **调用工具**，等待返回 `pdf_path` 与 `print.job_id`，向用户确认打印结果。

## 注意事项

- 生成的是 A4 PDF，自动保存到工作区 `papers/` 目录。
- `include_answer=true` 会把答案和解析直接印在卷子上；默认不印。
- 题库可能为空，若组卷失败，建议改为 AI 自出题，或先录入题目。
- 打印前可用 `document.list_printers` 确认打印机，然后传给 `printer` 参数。
