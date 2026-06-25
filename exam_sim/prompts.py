# exam_sim/prompts.py
# 考试流程提示词模板

EXAM_START_PROMPT = """
📝 考试开始！

你即将开始 {subject} 考试。
- 题目数量: {question_count}
- 考试时间: {time_limit} 分钟
- 满分: {total_score}

请按顺序作答，每题完成后系统会自动保存答案。
考试时间结束后系统将自动提交。

祝你好运！
"""

EXAM_RESULT_PROMPT = """
📊 考试成绩报告

总分: {score}/{max_score}
正确: {correct_count}/{total_count}
用时: {duration} 分钟
正确率: {accuracy}%

{weak_analysis}

建议:
- 针对薄弱知识点进行巩固练习
- 关注 {weak_kps} 相关题目
"""

EXAM_TIMEOUT_WARNING = """
⏰ 考试时间还剩 {minutes} 分钟！
"""
