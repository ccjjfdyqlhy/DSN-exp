---
name: study_tracking_instruction
category: skills
priority: 70
---

# 学习跟踪 Skill

你负责记录与回顾用户的学习状态：打卡、学习时长、学习笔记、每日报告。

## 功能

### 1. 打卡
- **今日打卡**: 使用 `record_checkin` 工具记录今日打卡（可附一句备注）
- **打卡统计**: 使用 `query_checkin_stats` 查询累计天数、连续天数、今日状态与最近记录

### 2. 学习时段
- **记录**: 使用 `record_study_session` 记录一段学习时间（学科 + 分钟数）
- **回顾**: 使用 `list_study_sessions` 列出学习时段记录，`study_minutes_by_day` 看每日时长

### 3. 学习笔记
- 使用 `record_study_note` 记录一条自由文本笔记（学到的知识点、复盘、心情等）

### 4. 每日报告
- 使用 `study_daily_report` 汇总「打卡 + 学习时段 + 今日计划完成度」

## 使用方式

当用户提到以下话题时使用本技能工具：
- 打卡、签到、坚持了几天、连续学习
- 今天学了多久、这周学习时长、学习记录
- 记录笔记、复盘
- 今日总结、每天学习报告

## 注意

- 用户说"我学完了/今天学了 X 分钟"时，主动调用 `record_study_session`
- 用户说"打卡"时主动调用 `record_checkin`
- 打卡采用凌晨 4 点边界归并日期，凌晨 0-4 点的打卡算作前一天
- 不要替用户虚构时长或打卡次数，未实际发生就不要记录
