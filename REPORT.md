# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-79%25-green)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **78.59/100** |
| 屎山等级 | 😐 微臭青年 |

> 略带清香，偶尔飘过一丝酸爽

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 246 |
| 已跳过 | 940 |
| 耗时 | 1218ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 42160 |
| 总注释行数 | 2096 |
| 整体注释比例 | 5.0% |
| 平均文件大小 | 214 行 |
| 最大文件 | `main.py` (2476) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 243 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 9.93% | 0.0% | 80.0% | 2.0% | ✓✓ |
| 认知复杂度 | 13.20% | 0.0% | 70.0% | 8.0% | ✓✓ |
| 嵌套深度 | 4.26% | 0.0% | 75.0% | 0.0% | ✓✓ |
| 函数长度 | 6.03% | 0.0% | 56.8% | 0.0% | ✓✓ |
| 文件长度 | 3.08% | 0.0% | 94.1% | 0.0% | ✓✓ |
| 参数数量 | 12.90% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.55% | 0.0% | 67.6% | 0.0% | ✓✓ |
| 结构分析 | 5.06% | 0.0% | 87.5% | 0.0% | ✓✓ |
| 错误处理 | 31.35% | 0.0% | 98.8% | 5.1% | ✓ |
| 注释比例 | 43.11% | 0.0% | 100.0% | 39.0% | ○ |
| 命名规范 | 31.23% | 0.0% | 100.0% | 25.0% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. plugins/pipeline.py

**糟糕指数: 55.85**

> 行数: 1382 总计, 1121 代码, 81 注释 | 函数: 35 | 类: 1

**问题**: 🔄 复杂度问题: 24, ⚠️ 其他问题: 9, 🏗️ 结构问题: 13, ❌ 错误处理问题: 36, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L975-1381 | 376 | 77 | 9 | 3 | ✓ |
| `_poll_pending_tasks` | L841-963 | 123 | 38 | 6 | 4 | ✓ |
| `_run_agent_loop` | L426-568 | 143 | 28 | 4 | 2 | ✗ |
| `_synthesize_lines_sync` | L709-799 | 91 | 23 | 4 | 4 | ✓ |
| `process` | L215-305 | 91 | 16 | 3 | 2 | ✗ |
| `_run_async_background` | L311-402 | 51 | 11 | 2 | 2 | ✗ |
| `_run_tool` | L356-396 | 41 | 9 | 4 | 0 | ✓ |
| `_print_timing` | L570-596 | 27 | 9 | 4 | 3 | ✗ |
| `_run_all_plugins` | L811-839 | 29 | 9 | 2 | 5 | ✗ |
| `_format_tag_results` | L608-626 | 19 | 8 | 3 | 1 | ✗ |
| `_dispatch_pre_process` | L650-687 | 38 | 7 | 1 | 2 | ✓ |
| `_concat_wav` | L155-178 | 24 | 6 | 2 | 1 | ✓ |
| `process_tts` | L180-194 | 15 | 6 | 4 | 2 | ✓ |
| `_call_llm_with_msgs` | L47-74 | 18 | 5 | 2 | 2 | ✓ |
| `_report_agent_progress` | L405-424 | 20 | 5 | 1 | 6 | ✓ |
| `_drain_q` | L1172-1193 | 22 | 5 | 3 | 0 | ✓ |
| `_extract_narrations` | L77-92 | 16 | 4 | 3 | 1 | ✓ |
| `process_post_process` | L205-211 | 7 | 4 | 1 | 3 | ✓ |
| `_print_plugin_timing` | L598-605 | 8 | 4 | 2 | 2 | ✗ |
| `_assemble_prompt` | L628-646 | 19 | 4 | 1 | 2 | ✓ |
| `_invoke` | L63-72 | 10 | 3 | 2 | 0 | ✗ |
| `_bridge_progress` | L802-809 | 8 | 3 | 2 | 2 | ✗ |
| `_consume_agent_progress` | L1155-1163 | 9 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L95-100 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L103-110 | 8 | 2 | 1 | 1 | ✗ |
| `_log_stage_timing` | L113-116 | 4 | 2 | 1 | 2 | ✗ |
| `process_pre_process` | L196-203 | 8 | 2 | 1 | 2 | ✓ |
| `timer_enabled` | L25-27 | 3 | 1 | 0 | 0 | ✗ |
| `enable_timer` | L30-32 | 3 | 1 | 0 | 0 | ✗ |
| `disable_timer` | L35-37 | 3 | 1 | 0 | 0 | ✗ |
| `toggle_timer` | L40-44 | 5 | 1 | 0 | 0 | ✗ |
| `__init__` | L133-150 | 18 | 1 | 0 | 8 | ✗ |
| `_dispatch_post_process` | L307-309 | 3 | 1 | 0 | 2 | ✗ |
| `_synthesize_lines` | L691-697 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L699-707 | 9 | 1 | 0 | 3 | ✓ |

**全部问题 (91)**

- 🔄 `process()` L215: 复杂度: 16
- 🔄 `_run_async_background()` L311: 复杂度: 11
- 🔄 `_run_agent_loop()` L426: 复杂度: 28
- 🔄 `_synthesize_lines_sync()` L709: 复杂度: 23
- 🔄 `_poll_pending_tasks()` L841: 复杂度: 38
- 🔄 `process_stream()` L975: 复杂度: 77
- 🔄 `process_tts()` L180: 认知复杂度: 14
- 🔄 `process()` L215: 认知复杂度: 22
- 🔄 `_run_async_background()` L311: 认知复杂度: 15
- 🔄 `_run_tool()` L356: 认知复杂度: 17
- 🔄 `_run_agent_loop()` L426: 认知复杂度: 36
- 🔄 `_print_timing()` L570: 认知复杂度: 17
- 🔄 `_format_tag_results()` L608: 认知复杂度: 14
- 🔄 `_synthesize_lines_sync()` L709: 认知复杂度: 31
- 🔄 `_run_all_plugins()` L811: 认知复杂度: 13
- 🔄 `_poll_pending_tasks()` L841: 认知复杂度: 50
- 🔄 `process_stream()` L975: 认知复杂度: 95
- 🔄 `process_tts()` L180: 嵌套深度: 4
- 🔄 `_run_tool()` L356: 嵌套深度: 4
- 🔄 `_run_agent_loop()` L426: 嵌套深度: 4
- 🔄 `_print_timing()` L570: 嵌套深度: 4
- 🔄 `_synthesize_lines_sync()` L709: 嵌套深度: 4
- 🔄 `_poll_pending_tasks()` L841: 嵌套深度: 6
- 🔄 `process_stream()` L975: 嵌套深度: 9
- 📏 `process()` L215: 91 代码量
- 📏 `_run_async_background()` L311: 51 代码量
- 📏 `_run_agent_loop()` L426: 143 代码量
- 📏 `_synthesize_lines_sync()` L709: 91 代码量
- 📏 `_poll_pending_tasks()` L841: 123 代码量
- 📏 `process_stream()` L975: 376 代码量
- 📏 `__init__()` L133: 8 参数数量
- 📏 `_report_agent_progress()` L405: 6 参数数量
- 🏗️ `_extract_narrations()` L77: 中等嵌套: 3
- 🏗️ `process_tts()` L180: 中等嵌套: 4
- 🏗️ `process()` L215: 中等嵌套: 3
- 🏗️ `_run_tool()` L356: 中等嵌套: 4
- 🏗️ `_run_agent_loop()` L426: 中等嵌套: 4
- 🏗️ `_print_timing()` L570: 中等嵌套: 4
- 🏗️ `_format_tag_results()` L608: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L709: 中等嵌套: 4
- 🏗️ `_poll_pending_tasks()` L841: 嵌套过深: 6
- 🏗️ `process_stream()` L975: 嵌套过深: 9
- 🏗️ `_drain_q()` L1172: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1382 行
- 🏗️ L1: 导入过多: 29
- ❌ L187: 未处理的易出错调用
- ❌ L209: 未处理的易出错调用
- ❌ L256: 未处理的易出错调用
- ❌ L273: 未处理的易出错调用
- ❌ L290: 未处理的易出错调用
- ❌ L318: 未处理的易出错调用
- ❌ L373: 未处理的易出错调用
- ❌ L374: 未处理的易出错调用
- ❌ L375: 未处理的易出错调用
- ❌ L396: 未处理的易出错调用
- ❌ L413: 未处理的易出错调用
- ❌ L424: 未处理的易出错调用
- ❌ L457: 未处理的易出错调用
- ❌ L479: 未处理的易出错调用
- ❌ L503: 未处理的易出错调用
- ❌ L623: 未处理的易出错调用
- ❌ L735: 未处理的易出错调用
- ❌ L791: 未处理的易出错调用
- ❌ L795: 未处理的易出错调用
- ❌ L798: 未处理的易出错调用
- ❌ L809: 未处理的易出错调用
- ❌ L816: 未处理的易出错调用
- ❌ L838: 未处理的易出错调用
- ❌ L839: 未处理的易出错调用
- ❌ L873: 未处理的易出错调用
- ❌ L898: 未处理的易出错调用
- ❌ L935: 未处理的易出错调用
- ❌ L1025: 未处理的易出错调用
- ❌ L1042: 未处理的易出错调用
- ❌ L1163: 未处理的易出错调用
- ❌ L1283: 未处理的易出错调用
- ❌ L1297: 未处理的易出错调用
- ❌ L1314: 未处理的易出错调用
- ❌ L1334: 未处理的易出错调用
- ❌ L1374: 未处理的易出错调用
- ❌ L1376: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L47: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L63: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L77: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L95: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L103: "_desc_task" - snake_case
- 🏷️ `_log_stage_timing()` L113: "_log_stage_timing" - snake_case
- 🏷️ `__init__()` L133: "__init__" - snake_case
- 🏷️ `_concat_wav()` L155: "_concat_wav" - snake_case
- 🏷️ `_dispatch_post_process()` L307: "_dispatch_post_process" - snake_case
- 🏷️ `_run_async_background()` L311: "_run_async_background" - snake_case

**详情**:
- 循环复杂度: 平均: 8.7, 最大: 77
- 认知复杂度: 平均: 12.7, 最大: 95
- 嵌套深度: 平均: 2.0, 最大: 9
- 函数长度: 平均: 36.6 行, 最大: 376 行
- 文件长度: 1121 代码量 (1382 总计)
- 参数数量: 平均: 2.1, 最大: 8
- 代码重复: 2.9% 重复 (1/35)
- 结构分析: 13 个结构问题
- 错误处理: 36/82 个错误被忽略 (43.9%)
- 注释比例: 7.2% (81/1121)
- 命名规范: 发现 26 个违规

### 2. main.py

**糟糕指数: 48.76**

> 行数: 2476 总计, 1970 代码, 60 注释 | 函数: 73 | 类: 1

**问题**: 🔄 复杂度问题: 38, ⚠️ 其他问题: 31, 🏗️ 结构问题: 14, ❌ 错误处理问题: 14, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_agent` | L1850-1994 | 145 | 34 | 3 | 3 | ✓ |
| `_cmd_reminder` | L733-861 | 129 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L1117-1257 | 141 | 31 | 3 | 2 | ✓ |
| `main` | L2285-2471 | 173 | 29 | 3 | 0 | ✗ |
| `_cmd_plan` | L864-926 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1260-1388 | 121 | 21 | 3 | 2 | ✓ |
| `_cmd_memory_list` | L1463-1547 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L2163-2234 | 72 | 14 | 3 | 1 | ✗ |
| `_cmd_export` | L567-656 | 90 | 13 | 2 | 2 | ✓ |
| `_cmd_memory` | L1036-1067 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L659-730 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L980-1033 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1739-1778 | 40 | 11 | 2 | 2 | ✓ |
| `_check_port_available` | L143-197 | 55 | 10 | 5 | 2 | ✗ |
| `_env_write` | L200-232 | 33 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L2038-2068 | 31 | 10 | 2 | 2 | ✗ |
| `_is_env_configured` | L24-44 | 21 | 9 | 4 | 0 | ✗ |
| `_cmd_users` | L333-371 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L374-410 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_detail` | L1597-1626 | 30 | 9 | 2 | 1 | ✓ |
| `_cmd_memory_reindex` | L1070-1114 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1781-1820 | 40 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L2127-2160 | 34 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L456-488 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1391-1424 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1427-1460 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1550-1576 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1629-1653 | 25 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L2237-2270 | 34 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L90-105 | 16 | 5 | 3 | 0 | ✓ |
| `_enable_console_logging` | L271-289 | 19 | 5 | 2 | 0 | ✗ |
| `_try_convert` | L436-453 | 18 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L491-510 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L513-540 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L1097-1110 | 14 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1998-2035 | 38 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L2071-2102 | 32 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L108-127 | 20 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L425-433 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1376-1383 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L2414-2427 | 14 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L130-140 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L292-302 | 11 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L316-330 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L543-559 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1833-1844 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L2112-2124 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L235-238 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L241-243 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L246-264 | 17 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1665-1666 | 2 | 2 | 0 | 7 | ✗ |
| `_h_timer` | L1710-1715 | 6 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1823-1847 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L2273-2282 | 10 | 2 | 1 | 1 | ✗ |
| `emit` | L258-259 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L562-564 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L929-977 | 49 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1579-1594 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1656-1657 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1659-1660 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1662-1663 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1668-1669 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1671-1672 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1674-1675 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1677-1678 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1680-1681 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1683-1684 | 2 | 1 | 0 | 7 | ✗ |
| `_h_agent` | L1686-1687 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1690-1691 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1694-1695 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L1698-1699 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L1702-1703 | 2 | 1 | 0 | 7 | ✗ |
| `_h_detail` | L1706-1707 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (106)**

- 🔄 `_cmd_export()` L567: 复杂度: 13
- 🔄 `_cmd_import()` L659: 复杂度: 11
- 🔄 `_cmd_reminder()` L733: 复杂度: 31
- 🔄 `_cmd_plan()` L864: 复杂度: 21
- 🔄 `_cmd_plugin()` L980: 复杂度: 11
- 🔄 `_cmd_memory()` L1036: 复杂度: 12
- 🔄 `_cmd_memory_query()` L1117: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1260: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1463: 复杂度: 17
- 🔄 `_cmd_persona()` L1739: 复杂度: 11
- 🔄 `_cmd_agent()` L1850: 复杂度: 34
- 🔄 `_cmd_hibernate_check()` L2163: 复杂度: 14
- 🔄 `main()` L2285: 复杂度: 29
- 🔄 `_is_env_configured()` L24: 认知复杂度: 17
- 🔄 `_check_port_available()` L143: 认知复杂度: 20
- 🔄 `_env_write()` L200: 认知复杂度: 20
- 🔄 `_cmd_users()` L333: 认知复杂度: 13
- 🔄 `_cmd_status()` L374: 认知复杂度: 13
- 🔄 `_cmd_export()` L567: 认知复杂度: 17
- 🔄 `_cmd_import()` L659: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L733: 认知复杂度: 39
- 🔄 `_cmd_plan()` L864: 认知复杂度: 25
- 🔄 `_cmd_plugin()` L980: 认知复杂度: 15
- 🔄 `_cmd_memory()` L1036: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L1117: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1260: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1463: 认知复杂度: 21
- 🔄 `_cmd_detail()` L1597: 认知复杂度: 13
- 🔄 `_cmd_persona()` L1739: 认知复杂度: 15
- 🔄 `_persona_status()` L1781: 认知复杂度: 14
- 🔄 `_cmd_agent()` L1850: 认知复杂度: 40
- 🔄 `_persona_materials()` L2038: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L2163: 认知复杂度: 20
- 🔄 `main()` L2285: 认知复杂度: 35
- 🔄 `_is_env_configured()` L24: 嵌套深度: 4
- 🔄 `_check_port_available()` L143: 嵌套深度: 5
- 🔄 `_env_write()` L200: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L733: 嵌套深度: 4
- 📏 `_check_port_available()` L143: 55 代码量
- 📏 `_cmd_export()` L567: 90 代码量
- 📏 `_cmd_import()` L659: 72 代码量
- 📏 `_cmd_reminder()` L733: 129 代码量
- 📏 `_cmd_plan()` L864: 63 代码量
- 📏 `_cmd_plugin()` L980: 54 代码量
- 📏 `_cmd_memory_query()` L1117: 141 代码量
- 📏 `_cmd_memory_rebuild()` L1260: 121 代码量
- 📏 `_cmd_memory_list()` L1463: 85 代码量
- 📏 `_cmd_agent()` L1850: 145 代码量
- 📏 `_cmd_hibernate_check()` L2163: 72 代码量
- 📏 `main()` L2285: 173 代码量
- 📏 `_execute_command()` L1629: 9 参数数量
- 📏 `_h_newbind()` L1656: 7 参数数量
- 📏 `_h_users()` L1659: 7 参数数量
- 📏 `_h_status()` L1662: 7 参数数量
- 📏 `_h_plugin()` L1665: 7 参数数量
- 📏 `_h_memory()` L1668: 7 参数数量
- 📏 `_h_prompt()` L1671: 7 参数数量
- 📏 `_h_config()` L1674: 7 参数数量
- 📏 `_h_listconfig()` L1677: 7 参数数量
- 📏 `_h_persona()` L1680: 7 参数数量
- 📏 `_h_help()` L1683: 7 参数数量
- 📏 `_h_agent()` L1686: 7 参数数量
- 📏 `_h_export()` L1690: 7 参数数量
- 📏 `_h_import()` L1694: 7 参数数量
- 📏 `_h_reminder()` L1698: 7 参数数量
- 📏 `_h_plan()` L1702: 7 参数数量
- 📏 `_h_detail()` L1706: 7 参数数量
- 📏 `_h_timer()` L1710: 7 参数数量
- 🏗️ `_is_env_configured()` L24: 中等嵌套: 4
- 🏗️ `_env_backup_rotate()` L90: 中等嵌套: 3
- 🏗️ `_check_port_available()` L143: 嵌套过深: 5
- 🏗️ `_env_write()` L200: 嵌套过深: 5
- 🏗️ `_cmd_reminder()` L733: 中等嵌套: 4
- 🏗️ `_cmd_memory_query()` L1117: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1260: 中等嵌套: 3
- 🏗️ `_persona_status()` L1781: 中等嵌套: 3
- 🏗️ `_cmd_agent()` L1850: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L2163: 中等嵌套: 3
- 🏗️ `main()` L2285: 中等嵌套: 3
- 🏗️ L1: 文件过大: 2476 行
- 🏗️ L1: 函数过多: 73
- 🏗️ L1: 导入过多: 54
- ❌ L156: 未处理的易出错调用
- ❌ L359: 未处理的易出错调用
- ❌ L367: 未处理的易出错调用
- ❌ L701: 未处理的易出错调用
- ❌ L707: 未处理的易出错调用
- ❌ L721: 未处理的易出错调用
- ❌ L727: 未处理的易出错调用
- ❌ L1028: 未处理的易出错调用
- ❌ L1544: 未处理的易出错调用
- ❌ L1818: 未处理的易出错调用
- ❌ L1993: 未处理的易出错调用
- ❌ L2026: 未处理的易出错调用
- ❌ L2027: 未处理的易出错调用
- ❌ L2028: 未处理的易出错调用
- 🏷️ `_is_env_configured()` L24: "_is_env_configured" - snake_case
- 🏷️ `_env_backup_rotate()` L90: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L108: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L130: "_env_backup_count" - snake_case
- 🏷️ `_check_port_available()` L143: "_check_port_available" - snake_case
- 🏷️ `_env_write()` L200: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L246: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L271: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L292: "_disable_console_logging" - snake_case
- 🏷️ `_cmd_newbind()` L316: "_cmd_newbind" - snake_case

**详情**:
- 循环复杂度: 平均: 6.7, 最大: 34
- 认知复杂度: 平均: 9.6, 最大: 40
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 30.5 行, 最大: 173 行
- 文件长度: 1970 代码量 (2476 总计)
- 参数数量: 平均: 2.8, 最大: 9
- 代码重复: 1.4% 重复 (1/73)
- 结构分析: 14 个结构问题
- 错误处理: 14/62 个错误被忽略 (22.6%)
- 注释比例: 3.0% (60/1970)
- 命名规范: 发现 70 个违规

### 3. psychoscope/minimal.py

**糟糕指数: 48.45**

> 行数: 1698 总计, 1315 代码, 75 注释 | 函数: 62 | 类: 6

**问题**: 🔄 复杂度问题: 28, ⚠️ 其他问题: 8, 📋 重复问题: 4, 🏗️ 结构问题: 16, ❌ 错误处理问题: 26, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L1340-1695 | 343 | 99 | 8 | 0 | ✗ |
| `_loop` | L817-887 | 71 | 24 | 6 | 1 | ✗ |
| `_poll_loop` | L288-328 | 41 | 18 | 5 | 1 | ✗ |
| `_handle_sse_stream` | L715-768 | 54 | 18 | 4 | 5 | ✗ |
| `_beat` | L974-1037 | 64 | 15 | 1 | 1 | ✓ |
| `authenticate` | L524-614 | 91 | 14 | 2 | 3 | ✗ |
| `_tts_worker` | L464-522 | 59 | 11 | 5 | 1 | ✗ |
| `stop_and_send` | L1093-1129 | 37 | 10 | 2 | 1 | ✗ |
| `print_system_info` | L1297-1338 | 42 | 10 | 4 | 1 | ✓ |
| `iter_sse_lines` | L382-412 | 31 | 9 | 4 | 1 | ✗ |
| `_capture_loop` | L1131-1165 | 35 | 9 | 3 | 1 | ✗ |
| `_loop` | L1191-1221 | 31 | 9 | 5 | 1 | ✗ |
| `play_index` | L119-149 | 31 | 7 | 3 | 2 | ✗ |
| `toggle` | L151-167 | 17 | 7 | 2 | 1 | ✗ |
| `_play_beep` | L331-369 | 39 | 6 | 3 | 2 | ✗ |
| `send_audio` | L673-713 | 41 | 6 | 2 | 2 | ✗ |
| `_verify_api_key` | L615-632 | 18 | 5 | 3 | 1 | ✗ |
| `send_async` | L651-672 | 22 | 5 | 2 | 2 | ✓ |
| `skip_latest` | L940-958 | 19 | 5 | 2 | 1 | ✓ |
| `_loop` | L960-972 | 13 | 5 | 3 | 1 | ✗ |
| `duck` | L215-225 | 11 | 4 | 2 | 1 | ✗ |
| `unduck` | L227-236 | 10 | 4 | 2 | 1 | ✗ |
| `cleanup` | L256-271 | 16 | 4 | 2 | 1 | ✗ |
| `start` | L1068-1091 | 24 | 4 | 1 | 1 | ✗ |
| `load_playlist` | L105-117 | 13 | 3 | 2 | 1 | ✗ |
| `stop` | L169-180 | 12 | 3 | 2 | 1 | ✗ |
| `next` | L182-190 | 9 | 3 | 1 | 1 | ✗ |
| `prev` | L192-200 | 9 | 3 | 1 | 1 | ✗ |
| `audio_set_volume` | L202-213 | 12 | 3 | 2 | 2 | ✗ |
| `_report_state` | L273-286 | 14 | 3 | 1 | 1 | ✗ |
| `load_config` | L414-424 | 11 | 3 | 2 | 0 | ✗ |
| `stop_tts` | L449-462 | 14 | 3 | 2 | 1 | ✓ |
| `add_task` | L804-815 | 12 | 3 | 2 | 2 | ✓ |
| `print_personality` | L1253-1282 | 30 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L53-77 | 25 | 2 | 1 | 0 | ✗ |
| `__init__` | L90-103 | 14 | 2 | 1 | 3 | ✗ |
| `stop_poll` | L247-254 | 8 | 2 | 1 | 1 | ✗ |
| `raw_pcm_to_wav_b64` | L372-380 | 9 | 2 | 1 | 2 | ✗ |
| `__init__` | L434-447 | 14 | 2 | 1 | 3 | ✗ |
| `_headers` | L634-637 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L786-796 | 11 | 2 | 1 | 1 | ✗ |
| `stop` | L798-802 | 5 | 2 | 1 | 1 | ✗ |
| `start` | L915-921 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L923-926 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L1173-1178 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L1180-1183 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L1185-1189 | 5 | 2 | 1 | 2 | ✗ |
| `print_header` | L1223-1251 | 29 | 2 | 1 | 3 | ✗ |
| `toggle_standby` | L1284-1294 | 11 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L1405-1417 | 13 | 2 | 1 | 2 | ✗ |
| `start_poll` | L238-245 | 8 | 1 | 0 | 1 | ✗ |
| `save_config` | L426-431 | 6 | 1 | 0 | 1 | ✗ |
| `_http_get` | L639-641 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L643-645 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L647-649 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L777-784 | 8 | 1 | 0 | 3 | ✗ |
| `__init__` | L907-913 | 7 | 1 | 0 | 3 | ✗ |
| `sync_now` | L928-939 | 12 | 1 | 0 | 1 | ✓ |
| `_type_label` | L1040-1045 | 6 | 1 | 0 | 1 | ✗ |
| `__init__` | L1053-1062 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L1065-1066 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L1168-1171 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (90)**

- 🔄 `_poll_loop()` L288: 复杂度: 18
- 🔄 `_tts_worker()` L464: 复杂度: 11
- 🔄 `authenticate()` L524: 复杂度: 14
- 🔄 `_handle_sse_stream()` L715: 复杂度: 18
- 🔄 `_loop()` L817: 复杂度: 24
- 🔄 `_beat()` L974: 复杂度: 15
- 🔄 `main()` L1340: 复杂度: 99
- 🔄 `play_index()` L119: 认知复杂度: 13
- 🔄 `_poll_loop()` L288: 认知复杂度: 28
- 🔄 `iter_sse_lines()` L382: 认知复杂度: 17
- 🔄 `_tts_worker()` L464: 认知复杂度: 21
- 🔄 `authenticate()` L524: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L715: 认知复杂度: 26
- 🔄 `_loop()` L817: 认知复杂度: 36
- 🔄 `_beat()` L974: 认知复杂度: 17
- 🔄 `stop_and_send()` L1093: 认知复杂度: 14
- 🔄 `_capture_loop()` L1131: 认知复杂度: 15
- 🔄 `_loop()` L1191: 认知复杂度: 19
- 🔄 `print_system_info()` L1297: 认知复杂度: 18
- 🔄 `main()` L1340: 认知复杂度: 115
- 🔄 `_poll_loop()` L288: 嵌套深度: 5
- 🔄 `iter_sse_lines()` L382: 嵌套深度: 4
- 🔄 `_tts_worker()` L464: 嵌套深度: 5
- 🔄 `_handle_sse_stream()` L715: 嵌套深度: 4
- 🔄 `_loop()` L817: 嵌套深度: 6
- 🔄 `_loop()` L1191: 嵌套深度: 5
- 🔄 `print_system_info()` L1297: 嵌套深度: 4
- 🔄 `main()` L1340: 嵌套深度: 8
- 📏 `_tts_worker()` L464: 59 代码量
- 📏 `authenticate()` L524: 91 代码量
- 📏 `_handle_sse_stream()` L715: 54 代码量
- 📏 `_loop()` L817: 71 代码量
- 📏 `_beat()` L974: 64 代码量
- 📏 `main()` L1340: 343 代码量
- 📋 `_report_state()` L273: 重复模式: _report_state, _loop
- 📋 `__init__()` L434: 重复模式: __init__, _capture_loop
- 📋 `__init__()` L777: 重复模式: __init__, print_header
- 📋 `start()` L786: 重复模式: start, start
- 🏗️ `play_index()` L119: 中等嵌套: 3
- 🏗️ `_poll_loop()` L288: 嵌套过深: 5
- 🏗️ `_play_beep()` L331: 中等嵌套: 3
- 🏗️ `iter_sse_lines()` L382: 中等嵌套: 4
- 🏗️ `_tts_worker()` L464: 嵌套过深: 5
- 🏗️ `_verify_api_key()` L615: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L715: 中等嵌套: 4
- 🏗️ `_loop()` L817: 嵌套过深: 6
- 🏗️ `_loop()` L960: 中等嵌套: 3
- 🏗️ `_capture_loop()` L1131: 中等嵌套: 3
- 🏗️ `_loop()` L1191: 嵌套过深: 5
- 🏗️ `print_system_info()` L1297: 中等嵌套: 4
- 🏗️ `main()` L1340: 嵌套过深: 8
- 🏗️ L1: 文件过大: 1698 行
- 🏗️ L1: 函数过多: 62
- 🏗️ L1: 导入过多: 29
- ❌ L139: 未处理的易出错调用
- ❌ L140: 未处理的易出错调用
- ❌ L283: 未处理的易出错调用
- ❌ L348: 未处理的易出错调用
- ❌ L355: 未处理的易出错调用
- ❌ L356: 未处理的易出错调用
- ❌ L375: 未处理的易出错调用
- ❌ L488: 未处理的易出错调用
- ❌ L489: 未处理的易出错调用
- ❌ L494: 未处理的易出错调用
- ❌ L762: 未处理的易出错调用
- ❌ L846: 未处理的易出错调用
- ❌ L860: 未处理的易出错调用
- ❌ L878: 未处理的易出错调用
- ❌ L954: 未处理的易出错调用
- ❌ L995: 未处理的易出错调用
- ❌ L1022: 未处理的易出错调用
- ❌ L1115: 未处理的易出错调用
- ❌ L1208: 未处理的易出错调用
- ❌ L1217: 未处理的易出错调用
- ❌ L1278: 未处理的易出错调用
- ❌ L1309: 未处理的易出错调用
- ❌ L1334: 未处理的易出错调用
- ❌ L1543: 未处理的易出错调用
- ❌ L1591: 未处理的易出错调用
- ❌ L1625: 未处理的易出错调用
- 🏷️ `__init__()` L90: "__init__" - snake_case
- 🏷️ `_report_state()` L273: "_report_state" - snake_case
- 🏷️ `_poll_loop()` L288: "_poll_loop" - snake_case
- 🏷️ `_play_beep()` L331: "_play_beep" - snake_case
- 🏷️ `__init__()` L434: "__init__" - snake_case
- 🏷️ `_tts_worker()` L464: "_tts_worker" - snake_case
- 🏷️ `_verify_api_key()` L615: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L634: "_headers" - snake_case
- 🏷️ `_http_get()` L639: "_http_get" - snake_case
- 🏷️ `_http_post()` L643: "_http_post" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 99
- 认知复杂度: 平均: 9.7, 最大: 115
- 嵌套深度: 平均: 1.8, 最大: 8
- 函数长度: 平均: 24.8 行, 最大: 343 行
- 文件长度: 1315 代码量 (1698 总计)
- 参数数量: 平均: 1.4, 最大: 5
- 代码重复: 6.5% 重复 (4/62)
- 结构分析: 16 个结构问题
- 错误处理: 26/132 个错误被忽略 (19.7%)
- 注释比例: 5.7% (75/1315)
- 命名规范: 发现 22 个违规

### 4. engine.py

**糟糕指数: 44.76**

> 行数: 1445 总计, 1140 代码, 60 注释 | 函数: 48 | 类: 2

**问题**: 🔄 复杂度问题: 13, ⚠️ 其他问题: 10, 📋 重复问题: 5, 🏗️ 结构问题: 9, ❌ 错误处理问题: 11, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L1214-1444 | 231 | 41 | 2 | 12 | ✓ |
| `_init_prompt` | L559-610 | 52 | 17 | 4 | 1 | ✗ |
| `build_context` | L821-858 | 38 | 13 | 1 | 8 | ✓ |
| `_register_execution_plugins` | L738-771 | 34 | 12 | 2 | 1 | ✗ |
| `chat_debug_respond` | L986-1059 | 74 | 11 | 2 | 4 | ✓ |
| `_register_context_plugins` | L680-713 | 34 | 9 | 1 | 1 | ✗ |
| `_register_output_plugins` | L772-802 | 31 | 9 | 2 | 1 | ✗ |
| `chat` | L899-935 | 37 | 9 | 2 | 8 | ✓ |
| `_dispatch_task_completion` | L237-251 | 15 | 8 | 2 | 3 | ✗ |
| `_generate_result_message` | L315-366 | 52 | 8 | 2 | 3 | ✗ |
| `_register_personality_plugins` | L715-736 | 22 | 8 | 2 | 1 | ✗ |
| `chat_stream` | L937-956 | 20 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L253-271 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L44-55 | 12 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L368-393 | 26 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L395-427 | 33 | 6 | 3 | 1 | ✗ |
| `_init_world` | L429-458 | 30 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L482-506 | 25 | 6 | 2 | 1 | ✗ |
| `_inject_system_skill_deps` | L508-539 | 32 | 6 | 3 | 1 | ✓ |
| `_inject_v3_to_exa_evolution` | L541-557 | 17 | 6 | 3 | 1 | ✓ |
| `chat_debug` | L960-984 | 25 | 6 | 0 | 6 | ✓ |
| `index_prompts_for_chat` | L1107-1127 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L1131-1179 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L1187-1195 | 9 | 6 | 0 | 1 | ✓ |
| `_process_task_completion` | L217-235 | 19 | 5 | 3 | 1 | ✗ |
| `_init_plugins` | L612-633 | 22 | 5 | 1 | 1 | ✗ |
| `_dump_context_for_session` | L1065-1099 | 35 | 5 | 3 | 2 | ✓ |
| `from_subapp` | L87-104 | 18 | 3 | 0 | 1 | ✓ |
| `__init__` | L118-152 | 35 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L190-213 | 24 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L293-314 | 22 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L460-480 | 21 | 3 | 2 | 1 | ✗ |
| `_plugin_enabled` | L635-640 | 6 | 3 | 1 | 2 | ✗ |
| `_get_skills_info` | L863-884 | 22 | 3 | 2 | 1 | ✗ |
| `_get_tool_parameters` | L885-897 | 13 | 3 | 2 | 2 | ✗ |
| `_init_database` | L177-188 | 12 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L273-291 | 19 | 2 | 1 | 3 | ✓ |
| `_register_filter_plugins` | L642-657 | 16 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L659-678 | 20 | 2 | 1 | 1 | ✗ |
| `create_chat` | L1101-1102 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L1104-1105 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L1143-1149 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L1153-1162 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L156-175 | 20 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L804-817 | 14 | 1 | 0 | 1 | ✗ |
| `_is_debug_mode` | L860-861 | 2 | 1 | 0 | 1 | ✗ |
| `process_tts` | L1061-1063 | 3 | 1 | 0 | 2 | ✓ |
| `create_engine` | L1200-1213 | 14 | 1 | 0 | 1 | ✓ |

**全部问题 (57)**

- 🔄 `_init_prompt()` L559: 复杂度: 17
- 🔄 `_register_execution_plugins()` L738: 复杂度: 12
- 🔄 `build_context()` L821: 复杂度: 13
- 🔄 `chat_debug_respond()` L986: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L1214: 复杂度: 41
- 🔄 `_init_prompt()` L559: 认知复杂度: 25
- 🔄 `_register_execution_plugins()` L738: 认知复杂度: 16
- 🔄 `_register_output_plugins()` L772: 认知复杂度: 13
- 🔄 `build_context()` L821: 认知复杂度: 15
- 🔄 `chat()` L899: 认知复杂度: 13
- 🔄 `chat_debug_respond()` L986: 认知复杂度: 15
- 🔄 `create_engine_with_defaults()` L1214: 认知复杂度: 45
- 🔄 `_init_prompt()` L559: 嵌套深度: 4
- 📏 `_generate_result_message()` L315: 52 代码量
- 📏 `_init_prompt()` L559: 52 代码量
- 📏 `chat_debug_respond()` L986: 74 代码量
- 📏 `create_engine_with_defaults()` L1214: 231 代码量
- 📏 `build_context()` L821: 8 参数数量
- 📏 `chat()` L899: 8 参数数量
- 📏 `chat_stream()` L937: 8 参数数量
- 📏 `chat_debug()` L960: 6 参数数量
- 📏 `create_engine_with_defaults()` L1214: 12 参数数量
- 📋 `from_subapp()` L87: 重复模式: from_subapp, _init_memory
- 📋 `_init_database()` L177: 重复模式: _init_database, _handle_reminder_completion
- 📋 `_process_task_completion()` L217: 重复模式: _process_task_completion, _register_personality_plugins
- 📋 `_register_context_plugins()` L680: 重复模式: _register_context_plugins, chat_stream
- 📋 `_register_execution_plugins()` L738: 重复模式: _register_execution_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L44: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L217: 中等嵌套: 3
- 🏗️ `_init_memory()` L395: 中等嵌套: 3
- 🏗️ `_inject_system_skill_deps()` L508: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L541: 中等嵌套: 3
- 🏗️ `_init_prompt()` L559: 中等嵌套: 4
- 🏗️ `_dump_context_for_session()` L1065: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1445 行
- 🏗️ L1: 导入过多: 91
- ❌ L241: 未处理的易出错调用
- ❌ L254: 未处理的易出错调用
- ❌ L268: 未处理的易出错调用
- ❌ L331: 未处理的易出错调用
- ❌ L872: 未处理的易出错调用
- ❌ L873: 未处理的易出错调用
- ❌ L874: 未处理的易出错调用
- ❌ L875: 未处理的易出错调用
- ❌ L876: 未处理的易出错调用
- ❌ L893: 未处理的易出错调用
- ❌ L1147: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L44: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L118: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L156: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L177: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L190: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L217: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L237: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L253: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L273: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L293: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 6.0, 最大: 41
- 认知复杂度: 平均: 8.8, 最大: 45
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 27.1 行, 最大: 231 行
- 文件长度: 1140 代码量 (1445 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.4% 重复 (5/48)
- 结构分析: 9 个结构问题
- 错误处理: 11/47 个错误被忽略 (23.4%)
- 注释比例: 5.3% (60/1140)
- 命名规范: 发现 32 个违规

### 5. memory/core.py

**糟糕指数: 43.12**

> 行数: 893 总计, 671 代码, 65 注释 | 函数: 28 | 类: 1

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 9, 📋 重复问题: 2, 🏗️ 结构问题: 6, ❌ 错误处理问题: 16, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L302-429 | 128 | 38 | 7 | 7 | ✓ |
| `assemble_context` | L246-296 | 51 | 14 | 3 | 4 | ✓ |
| `_format_detail_results` | L852-892 | 41 | 13 | 4 | 2 | ✗ |
| `_format_search_results` | L816-849 | 34 | 11 | 2 | 3 | ✗ |
| `reindex_embeddings` | L440-514 | 75 | 10 | 3 | 2 | ✓ |
| `_inject_unsynced_agent_chat` | L745-773 | 29 | 10 | 2 | 4 | ✓ |
| `handle_tags` | L635-662 | 28 | 9 | 2 | 4 | ✓ |
| `_handle_recall` | L664-693 | 30 | 9 | 3 | 4 | ✗ |
| `_format_timedelta` | L788-813 | 26 | 9 | 2 | 1 | ✗ |
| `rebuild_summaries` | L520-585 | 66 | 8 | 3 | 2 | ✓ |
| `_cosine_similarity` | L225-236 | 12 | 6 | 1 | 2 | ✗ |
| `summarize_turn` | L104-129 | 26 | 5 | 1 | 7 | ✓ |
| `_do_summarize` | L131-169 | 39 | 5 | 2 | 6 | ✗ |
| `_build_round_text` | L586-605 | 20 | 5 | 2 | 4 | ✓ |
| `_build_round_messages` | L606-625 | 20 | 5 | 2 | 4 | ✓ |
| `_embed_raw_round` | L195-214 | 20 | 4 | 2 | 6 | ✓ |
| `__init__` | L29-42 | 14 | 3 | 0 | 4 | ✗ |
| `_get_bound_agent` | L735-743 | 9 | 3 | 1 | 2 | ✓ |
| `_decrypt` | L95-98 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L703-718 | 16 | 2 | 1 | 4 | ✓ |
| `delete_memo` | L774-781 | 8 | 2 | 1 | 2 | ✗ |
| `_init_table` | L44-80 | 37 | 1 | 0 | 1 | ✗ |
| `_encrypt` | L88-94 | 7 | 1 | 0 | 3 | ✓ |
| `_get_exp_memories` | L170-185 | 16 | 1 | 0 | 2 | ✗ |
| `_pack_embedding` | L217-218 | 2 | 1 | 0 | 1 | ✗ |
| `_unpack_embedding` | L221-222 | 2 | 1 | 0 | 1 | ✗ |
| `get_detail` | L431-434 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L719-733 | 15 | 1 | 0 | 2 | ✗ |

**全部问题 (58)**

- 🔄 `assemble_context()` L246: 复杂度: 14
- 🔄 `search()` L302: 复杂度: 38
- 🔄 `_format_search_results()` L816: 复杂度: 11
- 🔄 `_format_detail_results()` L852: 复杂度: 13
- 🔄 `assemble_context()` L246: 认知复杂度: 20
- 🔄 `search()` L302: 认知复杂度: 52
- 🔄 `reindex_embeddings()` L440: 认知复杂度: 16
- 🔄 `rebuild_summaries()` L520: 认知复杂度: 14
- 🔄 `handle_tags()` L635: 认知复杂度: 13
- 🔄 `_handle_recall()` L664: 认知复杂度: 15
- 🔄 `_inject_unsynced_agent_chat()` L745: 认知复杂度: 14
- 🔄 `_format_timedelta()` L788: 认知复杂度: 13
- 🔄 `_format_search_results()` L816: 认知复杂度: 15
- 🔄 `_format_detail_results()` L852: 认知复杂度: 21
- 🔄 `search()` L302: 嵌套深度: 7
- 🔄 `_format_detail_results()` L852: 嵌套深度: 4
- 📏 `assemble_context()` L246: 51 代码量
- 📏 `search()` L302: 128 代码量
- 📏 `reindex_embeddings()` L440: 75 代码量
- 📏 `rebuild_summaries()` L520: 66 代码量
- 📏 `summarize_turn()` L104: 7 参数数量
- 📏 `_do_summarize()` L131: 6 参数数量
- 📏 `_embed_raw_round()` L195: 6 参数数量
- 📏 `search()` L302: 7 参数数量
- 📋 `_get_exp_memories()` L170: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L703: 重复模式: add_memo, delete_memo
- 🏗️ `assemble_context()` L246: 中等嵌套: 3
- 🏗️ `search()` L302: 嵌套过深: 7
- 🏗️ `reindex_embeddings()` L440: 中等嵌套: 3
- 🏗️ `rebuild_summaries()` L520: 中等嵌套: 3
- 🏗️ `_handle_recall()` L664: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L852: 中等嵌套: 4
- ❌ L50: 未处理的易出错调用
- ❌ L61: 未处理的易出错调用
- ❌ L65: 未处理的易出错调用
- ❌ L76: 未处理的易出错调用
- ❌ L80: 未处理的易出错调用
- ❌ L156: 未处理的易出错调用
- ❌ L206: 未处理的易出错调用
- ❌ L211: 未处理的易出错调用
- ❌ L501: 未处理的易出错调用
- ❌ L506: 未处理的易出错调用
- ❌ L567: 未处理的易出错调用
- ❌ L571: 未处理的易出错调用
- ❌ L712: 未处理的易出错调用
- ❌ L763: 未处理的易出错调用
- ❌ L780: 未处理的易出错调用
- ❌ L869: 未处理的易出错调用
- 🏷️ `__init__()` L29: "__init__" - snake_case
- 🏷️ `_init_table()` L44: "_init_table" - snake_case
- 🏷️ `_encrypt()` L88: "_encrypt" - snake_case
- 🏷️ `_decrypt()` L95: "_decrypt" - snake_case
- 🏷️ `_do_summarize()` L131: "_do_summarize" - snake_case
- 🏷️ `_get_exp_memories()` L170: "_get_exp_memories" - snake_case
- 🏷️ `_embed_raw_round()` L195: "_embed_raw_round" - snake_case
- 🏷️ `_pack_embedding()` L217: "_pack_embedding" - snake_case
- 🏷️ `_unpack_embedding()` L221: "_unpack_embedding" - snake_case
- 🏷️ `_cosine_similarity()` L225: "_cosine_similarity" - snake_case

**详情**:
- 循环复杂度: 平均: 6.4, 最大: 38
- 认知复杂度: 平均: 9.6, 最大: 52
- 嵌套深度: 平均: 1.6, 最大: 7
- 函数长度: 平均: 27.8 行, 最大: 128 行
- 文件长度: 671 代码量 (893 总计)
- 参数数量: 平均: 3.3, 最大: 7
- 代码重复: 7.1% 重复 (2/28)
- 结构分析: 6 个结构问题
- 错误处理: 16/38 个错误被忽略 (42.1%)
- 注释比例: 9.7% (65/671)
- 命名规范: 发现 19 个违规

### 6. models/clients.py

**糟糕指数: 39.55**

> 行数: 1316 总计, 1035 代码, 41 注释 | 函数: 59 | 类: 6

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 11, 📋 重复问题: 3, 🏗️ 结构问题: 7, ❌ 错误处理问题: 5, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_and_append` | L194-300 | 107 | 24 | 3 | 4 | ✗ |
| `_call_llm` | L833-905 | 60 | 17 | 5 | 7 | ✓ |
| `_ocr_single` | L1048-1111 | 57 | 13 | 5 | 3 | ✗ |
| `ask` | L1166-1230 | 65 | 13 | 1 | 6 | ✓ |
| `_call_embed_api` | L709-770 | 41 | 11 | 5 | 2 | ✓ |
| `__init__` | L114-159 | 46 | 9 | 1 | 11 | ✗ |
| `describe_images` | L563-608 | 46 | 9 | 2 | 5 | ✓ |
| `classify_image` | L610-657 | 48 | 8 | 2 | 4 | ✓ |
| `__init__` | L989-1015 | 27 | 8 | 1 | 5 | ✗ |
| `__init__` | L795-832 | 38 | 7 | 1 | 8 | ✗ |
| `summarize_dialog` | L933-970 | 38 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L33-48 | 16 | 6 | 1 | 1 | ✓ |
| `__init__` | L355-404 | 50 | 6 | 1 | 8 | ✓ |
| `_do_call_chat_api` | L422-444 | 23 | 6 | 4 | 2 | ✓ |
| `_call_and_append` | L459-496 | 38 | 6 | 2 | 1 | ✗ |
| `describe_image` | L529-561 | 33 | 6 | 1 | 5 | ✓ |
| `classify_image` | L1262-1281 | 20 | 6 | 2 | 3 | ✓ |
| `_unload_lmstudio_model` | L76-97 | 22 | 5 | 2 | 2 | ✓ |
| `_do_request` | L855-867 | 13 | 5 | 2 | 0 | ✗ |
| `summarize_text` | L907-928 | 22 | 5 | 1 | 3 | ✓ |
| `__init__` | L1143-1154 | 12 | 5 | 1 | 5 | ✗ |
| `send_message` | L446-453 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L672-692 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L694-701 | 8 | 4 | 1 | 2 | ✓ |
| `ocr_batch` | L1022-1047 | 26 | 4 | 1 | 3 | ✓ |
| `_load_lmstudio_model` | L49-75 | 27 | 3 | 1 | 4 | ✓ |
| `send_message` | L161-172 | 12 | 3 | 1 | 5 | ✗ |
| `last_tool_calls` | L181-192 | 12 | 3 | 1 | 1 | ✗ |
| `_call_chat_api` | L411-420 | 10 | 3 | 2 | 2 | ✓ |
| `_do_request` | L714-734 | 21 | 3 | 1 | 0 | ✗ |
| `_do_request` | L1068-1074 | 7 | 3 | 1 | 0 | ✗ |
| `encode_image` | L1157-1164 | 8 | 3 | 1 | 2 | ✓ |
| `ask_raw` | L1232-1258 | 27 | 3 | 1 | 5 | ✓ |
| `ocr_md` | L1283-1297 | 15 | 3 | 1 | 3 | ✓ |
| `embed_batch` | L703-707 | 5 | 2 | 1 | 2 | ✓ |
| `ocr` | L1017-1020 | 4 | 2 | 0 | 3 | ✓ |
| `ocr_md_batch` | L1299-1312 | 14 | 2 | 1 | 3 | ✓ |
| `toggle_detail_chats` | L19-23 | 5 | 1 | 0 | 0 | ✓ |
| `toggle_detail_actions` | L26-30 | 5 | 1 | 0 | 0 | ✓ |
| `continue_conversation` | L174-178 | 5 | 1 | 0 | 4 | ✗ |
| `reset_conversation` | L302-309 | 8 | 1 | 0 | 1 | ✓ |
| `get_history` | L311-317 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L319-334 | 16 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L336-343 | 8 | 1 | 0 | 2 | ✓ |
| `__repr__` | L345-346 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L406-407 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L455-457 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L498-501 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L503-509 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L511-518 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L520-527 | 8 | 1 | 0 | 2 | ✓ |
| `__repr__` | L659-660 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L772-773 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L775-776 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L930-931 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_loaded` | L1113-1114 | 2 | 1 | 0 | 1 | ✗ |
| `unload` | L1116-1118 | 3 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1120-1125 | 6 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1314-1315 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (51)**

- 🔄 `_call_and_append()` L194: 复杂度: 24
- 🔄 `_call_embed_api()` L709: 复杂度: 11
- 🔄 `_call_llm()` L833: 复杂度: 17
- 🔄 `_ocr_single()` L1048: 复杂度: 13
- 🔄 `ask()` L1166: 复杂度: 13
- 🔄 `_call_and_append()` L194: 认知复杂度: 30
- 🔄 `_do_call_chat_api()` L422: 认知复杂度: 14
- 🔄 `describe_images()` L563: 认知复杂度: 13
- 🔄 `_call_embed_api()` L709: 认知复杂度: 21
- 🔄 `_call_llm()` L833: 认知复杂度: 27
- 🔄 `_ocr_single()` L1048: 认知复杂度: 23
- 🔄 `ask()` L1166: 认知复杂度: 15
- 🔄 `_do_call_chat_api()` L422: 嵌套深度: 4
- 🔄 `_call_embed_api()` L709: 嵌套深度: 5
- 🔄 `_call_llm()` L833: 嵌套深度: 5
- 🔄 `_ocr_single()` L1048: 嵌套深度: 5
- 📏 `_call_and_append()` L194: 107 代码量
- 📏 `_call_llm()` L833: 60 代码量
- 📏 `_ocr_single()` L1048: 57 代码量
- 📏 `ask()` L1166: 65 代码量
- 📏 `__init__()` L114: 11 参数数量
- 📏 `__init__()` L355: 8 参数数量
- 📏 `__init__()` L672: 6 参数数量
- 📏 `__init__()` L795: 8 参数数量
- 📏 `_call_llm()` L833: 7 参数数量
- 📏 `ask()` L1166: 6 参数数量
- 📋 `_is_no_model_error()` L33: 重复模式: _is_no_model_error, embed
- 📋 `send_message()` L161: 重复模式: send_message, continue_conversation
- 📋 `describe_image()` L529: 重复模式: describe_image, ask_raw
- 🏗️ `_call_and_append()` L194: 中等嵌套: 3
- 🏗️ `_do_call_chat_api()` L422: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L709: 嵌套过深: 5
- 🏗️ `_call_llm()` L833: 嵌套过深: 5
- 🏗️ `_ocr_single()` L1048: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1316 行
- 🏗️ L1: 函数过多: 59
- ❌ L64: 未处理的易出错调用
- ❌ L183: 未处理的易出错调用
- ❌ L258: 未处理的易出错调用
- ❌ L261: 未处理的易出错调用
- ❌ L1162: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L33: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L49: "_load_lmstudio_model" - snake_case
- 🏷️ `_unload_lmstudio_model()` L76: "_unload_lmstudio_model" - snake_case
- 🏷️ `__init__()` L114: "__init__" - snake_case
- 🏷️ `_call_and_append()` L194: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L345: "__repr__" - snake_case
- 🏷️ `__init__()` L355: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L406: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L411: "_call_chat_api" - snake_case
- 🏷️ `_do_call_chat_api()` L422: "_do_call_chat_api" - snake_case

**详情**:
- 循环复杂度: 平均: 4.3, 最大: 24
- 认知复杂度: 平均: 6.3, 最大: 30
- 嵌套深度: 平均: 1.0, 最大: 5
- 函数长度: 平均: 19.6 行, 最大: 107 行
- 文件长度: 1035 代码量 (1316 总计)
- 参数数量: 平均: 2.7, 最大: 11
- 代码重复: 5.1% 重复 (3/59)
- 结构分析: 7 个结构问题
- 错误处理: 5/36 个错误被忽略 (13.9%)
- 注释比例: 4.0% (41/1035)
- 命名规范: 发现 28 个违规

### 7. skills/builtin/ncm_music/tools/ncm_api.py

**糟糕指数: 38.03**

> 行数: 1234 总计, 1010 代码, 50 注释 | 函数: 51 | 类: 1

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 8, 📋 重复问题: 4, 🏗️ 结构问题: 9, ❌ 错误处理问题: 93, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L433-501 | 69 | 23 | 2 | 5 | ✓ |
| `get_song_url` | L251-312 | 62 | 14 | 2 | 7 | ✓ |
| `_try_restore_session` | L77-110 | 34 | 12 | 4 | 1 | ✓ |
| `_fetch_song_url` | L1052-1107 | 56 | 12 | 2 | 3 | ✓ |
| `search_song` | L193-249 | 57 | 11 | 4 | 7 | ✓ |
| `get_lyrics` | L314-363 | 50 | 9 | 1 | 4 | ✓ |
| `list_downloaded` | L394-427 | 34 | 9 | 3 | 2 | ✓ |
| `login` | L161-191 | 31 | 8 | 2 | 3 | ✓ |
| `music_control` | L365-392 | 28 | 8 | 4 | 4 | ✓ |
| `_download_song_file` | L1135-1173 | 39 | 7 | 2 | 6 | ✓ |
| `_login_by_cookie` | L112-129 | 18 | 6 | 3 | 3 | ✓ |
| `login_logout` | L905-923 | 19 | 6 | 3 | 1 | ✓ |
| `_normalize_song` | L1117-1129 | 13 | 6 | 0 | 2 | ✓ |
| `get_user_detail` | L738-756 | 19 | 5 | 1 | 2 | ✓ |
| `get_track_comments` | L778-813 | 36 | 5 | 1 | 4 | ✓ |
| `get_mv` | L862-884 | 23 | 5 | 1 | 3 | ✓ |
| `get_album` | L503-523 | 21 | 4 | 1 | 2 | ✓ |
| `get_artist` | L525-542 | 18 | 4 | 1 | 2 | ✓ |
| `get_artist_albums` | L544-564 | 21 | 4 | 1 | 4 | ✓ |
| `get_artist_tracks` | L566-590 | 25 | 4 | 1 | 5 | ✓ |
| `get_playlist` | L592-609 | 18 | 4 | 1 | 2 | ✓ |
| `create_playlist` | L635-653 | 19 | 4 | 1 | 3 | ✓ |
| `get_user_playlists` | L696-718 | 23 | 4 | 1 | 4 | ✓ |
| `get_daily_recommend` | L720-736 | 17 | 4 | 1 | 1 | ✓ |
| `daily_signin` | L886-903 | 18 | 4 | 1 | 2 | ✓ |
| `_strip_lrc_timestamps` | L1194-1203 | 10 | 4 | 2 | 1 | ✗ |
| `get_playlist_tracks` | L611-633 | 23 | 3 | 1 | 4 | ✓ |
| `add_to_playlist` | L655-674 | 20 | 3 | 1 | 3 | ✓ |
| `remove_from_playlist` | L676-694 | 19 | 3 | 1 | 3 | ✓ |
| `like_track` | L758-776 | 19 | 3 | 1 | 3 | ✓ |
| `get_personal_fm` | L815-833 | 19 | 3 | 1 | 2 | ✓ |
| `_do_search` | L1033-1050 | 18 | 3 | 1 | 4 | ✓ |
| `_safe_filename` | L1206-1211 | 6 | 3 | 1 | 2 | ✗ |
| `_guess_ext` | L1214-1222 | 9 | 3 | 2 | 1 | ✗ |
| `_format_size` | L1225-1233 | 9 | 3 | 2 | 1 | ✗ |
| `__init__` | L43-53 | 11 | 2 | 0 | 2 | ✗ |
| `_get_music_dir` | L58-68 | 11 | 2 | 1 | 1 | ✓ |
| `_session_path` | L74-75 | 2 | 2 | 0 | 2 | ✗ |
| `_ensure_logged_in` | L131-136 | 6 | 2 | 1 | 1 | ✓ |
| `_save_session` | L138-146 | 9 | 2 | 1 | 2 | ✓ |
| `skip_fm_track` | L835-846 | 12 | 2 | 1 | 2 | ✓ |
| `like_fm_track` | L848-860 | 13 | 2 | 1 | 3 | ✓ |
| `_normalize_album` | L931-944 | 14 | 2 | 0 | 2 | ✓ |
| `_normalize_artist` | L945-960 | 16 | 2 | 0 | 2 | ✗ |
| `_normalize_playlist` | L961-976 | 16 | 2 | 0 | 2 | ✗ |
| `_normalize_user` | L977-990 | 14 | 2 | 0 | 2 | ✗ |
| `_normalize_mv` | L991-1005 | 15 | 2 | 0 | 2 | ✗ |
| `_normalize_video` | L1006-1018 | 13 | 2 | 0 | 2 | ✗ |
| `_normalize_dj` | L1019-1027 | 9 | 2 | 0 | 2 | ✗ |
| `_save_lyrics` | L1174-1187 | 14 | 2 | 1 | 5 | ✗ |
| `_quality_to_pyncm` | L153-155 | 3 | 1 | 0 | 1 | ✓ |

**全部问题 (138)**

- 🔄 `_try_restore_session()` L77: 复杂度: 12
- 🔄 `search_song()` L193: 复杂度: 11
- 🔄 `get_song_url()` L251: 复杂度: 14
- 🔄 `search()` L433: 复杂度: 23
- 🔄 `_fetch_song_url()` L1052: 复杂度: 12
- 🔄 `_try_restore_session()` L77: 认知复杂度: 20
- 🔄 `search_song()` L193: 认知复杂度: 19
- 🔄 `get_song_url()` L251: 认知复杂度: 18
- 🔄 `music_control()` L365: 认知复杂度: 16
- 🔄 `list_downloaded()` L394: 认知复杂度: 15
- 🔄 `search()` L433: 认知复杂度: 27
- 🔄 `_fetch_song_url()` L1052: 认知复杂度: 16
- 🔄 `_try_restore_session()` L77: 嵌套深度: 4
- 🔄 `search_song()` L193: 嵌套深度: 4
- 🔄 `music_control()` L365: 嵌套深度: 4
- 📏 `search_song()` L193: 57 代码量
- 📏 `get_song_url()` L251: 62 代码量
- 📏 `search()` L433: 69 代码量
- 📏 `_fetch_song_url()` L1052: 56 代码量
- 📏 `search_song()` L193: 7 参数数量
- 📏 `get_song_url()` L251: 7 参数数量
- 📏 `_download_song_file()` L1135: 6 参数数量
- 📋 `get_artist()` L525: 重复模式: get_artist, get_playlist, get_daily_recommend
- 📋 `get_artist_albums()` L544: 重复模式: get_artist_albums, get_artist_tracks, get_playlist_tracks, create_playlist, get_personal_fm
- 📋 `add_to_playlist()` L655: 重复模式: add_to_playlist, remove_from_playlist
- 📋 `get_user_playlists()` L696: 重复模式: get_user_playlists, get_user_detail
- 🏗️ `_try_restore_session()` L77: 中等嵌套: 4
- 🏗️ `_login_by_cookie()` L112: 中等嵌套: 3
- 🏗️ `search_song()` L193: 中等嵌套: 4
- 🏗️ `music_control()` L365: 中等嵌套: 4
- 🏗️ `list_downloaded()` L394: 中等嵌套: 3
- 🏗️ `login_logout()` L905: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1234 行
- 🏗️ L1: 函数过多: 51
- 🏗️ L1: 导入过多: 43
- ❌ L234: 未处理的易出错调用
- ❌ L238: 未处理的易出错调用
- ❌ L239: 未处理的易出错调用
- ❌ L240: 未处理的易出错调用
- ❌ L246: 未处理的易出错调用
- ❌ L286: 未处理的易出错调用
- ❌ L304: 未处理的易出错调用
- ❌ L306: 未处理的易出错调用
- ❌ L311: 未处理的易出错调用
- ❌ L387: 未处理的易出错调用
- ❌ L406: 未处理的易出错调用
- ❌ L407: 未处理的易出错调用
- ❌ L467: 未处理的易出错调用
- ❌ L470: 未处理的易出错调用
- ❌ L473: 未处理的易出错调用
- ❌ L476: 未处理的易出错调用
- ❌ L479: 未处理的易出错调用
- ❌ L482: 未处理的易出错调用
- ❌ L485: 未处理的易出错调用
- ❌ L488: 未处理的易出错调用
- ❌ L491: 未处理的易出错调用
- ❌ L492: 未处理的易出错调用
- ❌ L500: 未处理的易出错调用
- ❌ L652: 未处理的易出错调用
- ❌ L794: 未处理的易出错调用
- ❌ L796: 未处理的易出错调用
- ❌ L797: 未处理的易出错调用
- ❌ L798: 未处理的易出错调用
- ❌ L799: 未处理的易出错调用
- ❌ L800: 未处理的易出错调用
- ❌ L801: 未处理的易出错调用
- ❌ L806: 未处理的易出错调用
- ❌ L808: 未处理的易出错调用
- ❌ L809: 未处理的易出错调用
- ❌ L810: 未处理的易出错调用
- ❌ L811: 未处理的易出错调用
- ❌ L812: 未处理的易出错调用
- ❌ L882: 未处理的易出错调用
- ❌ L933: 未处理的易出错调用
- ❌ L934: 未处理的易出错调用
- ❌ L935: 未处理的易出错调用
- ❌ L936: 未处理的易出错调用
- ❌ L937: 未处理的易出错调用
- ❌ L938: 未处理的易出错调用
- ❌ L947: 未处理的易出错调用
- ❌ L948: 未处理的易出错调用
- ❌ L949: 未处理的易出错调用
- ❌ L950: 未处理的易出错调用
- ❌ L951: 未处理的易出错调用
- ❌ L952: 未处理的易出错调用
- ❌ L953: 未处理的易出错调用
- ❌ L954: 未处理的易出错调用
- ❌ L963: 未处理的易出错调用
- ❌ L964: 未处理的易出错调用
- ❌ L965: 未处理的易出错调用
- ❌ L966: 未处理的易出错调用
- ❌ L967: 未处理的易出错调用
- ❌ L968: 未处理的易出错调用
- ❌ L969: 未处理的易出错调用
- ❌ L970: 未处理的易出错调用
- ❌ L979: 未处理的易出错调用
- ❌ L980: 未处理的易出错调用
- ❌ L981: 未处理的易出错调用
- ❌ L982: 未处理的易出错调用
- ❌ L983: 未处理的易出错调用
- ❌ L984: 未处理的易出错调用
- ❌ L993: 未处理的易出错调用
- ❌ L994: 未处理的易出错调用
- ❌ L995: 未处理的易出错调用
- ❌ L996: 未处理的易出错调用
- ❌ L997: 未处理的易出错调用
- ❌ L998: 未处理的易出错调用
- ❌ L999: 未处理的易出错调用
- ❌ L1008: 未处理的易出错调用
- ❌ L1009: 未处理的易出错调用
- ❌ L1010: 未处理的易出错调用
- ❌ L1011: 未处理的易出错调用
- ❌ L1012: 未处理的易出错调用
- ❌ L1021: 未处理的易出错调用
- ❌ L1022: 未处理的易出错调用
- ❌ L1023: 未处理的易出错调用
- ❌ L1024: 未处理的易出错调用
- ❌ L1025: 未处理的易出错调用
- ❌ L1026: 未处理的易出错调用
- ❌ L1088: 未处理的易出错调用
- ❌ L1090: 未处理的易出错调用
- ❌ L1091: 未处理的易出错调用
- ❌ L1092: 未处理的易出错调用
- ❌ L1122: 未处理的易出错调用
- ❌ L1123: 未处理的易出错调用
- ❌ L1125: 未处理的易出错调用
- ❌ L1128: 未处理的易出错调用
- ❌ L1148: 未处理的易出错调用
- 🏷️ `__init__()` L43: "__init__" - snake_case
- 🏷️ `_get_music_dir()` L58: "_get_music_dir" - snake_case
- 🏷️ `_session_path()` L74: "_session_path" - snake_case
- 🏷️ `_try_restore_session()` L77: "_try_restore_session" - snake_case
- 🏷️ `_login_by_cookie()` L112: "_login_by_cookie" - snake_case
- 🏷️ `_ensure_logged_in()` L131: "_ensure_logged_in" - snake_case
- 🏷️ `_save_session()` L138: "_save_session" - snake_case
- 🏷️ `_quality_to_pyncm()` L153: "_quality_to_pyncm" - snake_case
- 🏷️ `_normalize_album()` L931: "_normalize_album" - snake_case
- 🏷️ `_normalize_artist()` L945: "_normalize_artist" - snake_case

**详情**:
- 循环复杂度: 平均: 4.8, 最大: 23
- 认知复杂度: 平均: 7.3, 最大: 27
- 嵌套深度: 平均: 1.2, 最大: 4
- 函数长度: 平均: 21.5 行, 最大: 69 行
- 文件长度: 1010 代码量 (1234 总计)
- 参数数量: 平均: 2.7, 最大: 7
- 代码重复: 15.7% 重复 (8/51)
- 结构分析: 9 个结构问题
- 错误处理: 93/193 个错误被忽略 (48.2%)
- 注释比例: 5.0% (50/1010)
- 命名规范: 发现 24 个违规

### 8. plugins/builtin/models_plugin.py

**糟糕指数: 37.76**

> 行数: 259 总计, 225 代码, 4 注释 | 函数: 9 | 类: 1

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 2, 🏗️ 结构问题: 3, ❌ 错误处理问题: 2, 📝 注释问题: 1, 🏷️ 命名问题: 4

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `on_hook` | L60-150 | 91 | 24 | 6 | 3 | ✗ |
| `invoke` | L218-246 | 29 | 10 | 4 | 4 | ✗ |
| `_build_tools_schema` | L152-172 | 21 | 6 | 3 | 1 | ✗ |
| `_create_chat` | L174-192 | 19 | 3 | 1 | 2 | ✗ |
| `set_skill_registry` | L51-54 | 4 | 2 | 0 | 2 | ✗ |
| `_clean_reply` | L195-216 | 22 | 2 | 1 | 1 | ✗ |
| `__init__` | L23-49 | 27 | 1 | 0 | 12 | ✗ |
| `on_load` | L56-58 | 3 | 1 | 0 | 1 | ✗ |
| `describe_image` | L248-258 | 11 | 1 | 0 | 3 | ✗ |

**全部问题 (16)**

- 🔄 `on_hook()` L60: 复杂度: 24
- 🔄 `on_hook()` L60: 认知复杂度: 36
- 🔄 `invoke()` L218: 认知复杂度: 18
- 🔄 `on_hook()` L60: 嵌套深度: 6
- 🔄 `invoke()` L218: 嵌套深度: 4
- 📏 `on_hook()` L60: 91 代码量
- 📏 `__init__()` L23: 12 参数数量
- 🏗️ `on_hook()` L60: 嵌套过深: 6
- 🏗️ `_build_tools_schema()` L152: 中等嵌套: 3
- 🏗️ `invoke()` L218: 中等嵌套: 4
- ❌ L120: 未处理的易出错调用
- ❌ L137: 未处理的易出错调用
- 🏷️ `__init__()` L23: "__init__" - snake_case
- 🏷️ `_build_tools_schema()` L152: "_build_tools_schema" - snake_case
- 🏷️ `_create_chat()` L174: "_create_chat" - snake_case
- 🏷️ `_clean_reply()` L195: "_clean_reply" - snake_case

**详情**:
- 循环复杂度: 平均: 5.6, 最大: 24
- 认知复杂度: 平均: 8.9, 最大: 36
- 嵌套深度: 平均: 1.7, 最大: 6
- 函数长度: 平均: 25.2 行, 最大: 91 行
- 文件长度: 225 代码量 (259 总计)
- 参数数量: 平均: 3.2, 最大: 12
- 代码重复: 0.0% 重复 (0/9)
- 结构分析: 3 个结构问题
- 错误处理: 2/8 个错误被忽略 (25.0%)
- 注释比例: 1.8% (4/225)
- 命名规范: 发现 4 个违规

### 9. document/doc_processor.py

**糟糕指数: 35.34**

> 行数: 284 总计, 236 代码, 7 注释 | 函数: 9 | 类: 1

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 2, 🏗️ 结构问题: 2, ❌ 错误处理问题: 9, 📝 注释问题: 1, 🏷️ 命名问题: 8

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_scan` | L74-220 | 147 | 32 | 5 | 3 | ✓ |
| `_build_feedback` | L251-283 | 33 | 11 | 3 | 7 | ✗ |
| `_classify_image` | L42-51 | 10 | 4 | 1 | 2 | ✓ |
| `_merge_2md_results` | L223-241 | 19 | 4 | 1 | 1 | ✗ |
| `__init__` | L34-40 | 7 | 2 | 1 | 4 | ✗ |
| `_get_ocr` | L53-58 | 6 | 2 | 1 | 1 | ✗ |
| `_get_vm` | L60-65 | 6 | 2 | 1 | 1 | ✗ |
| `_get_hmd` | L67-72 | 6 | 2 | 1 | 1 | ✗ |
| `_documents_dir` | L243-248 | 6 | 1 | 0 | 2 | ✗ |

**全部问题 (26)**

- 🔄 `process_scan()` L74: 复杂度: 32
- 🔄 `_build_feedback()` L251: 复杂度: 11
- 🔄 `process_scan()` L74: 认知复杂度: 42
- 🔄 `_build_feedback()` L251: 认知复杂度: 17
- 🔄 `process_scan()` L74: 嵌套深度: 5
- 📏 `process_scan()` L74: 147 代码量
- 📏 `_build_feedback()` L251: 7 参数数量
- 🏗️ `process_scan()` L74: 嵌套过深: 5
- 🏗️ `_build_feedback()` L251: 中等嵌套: 3
- ❌ L118: 未处理的易出错调用
- ❌ L180: 未处理的易出错调用
- ❌ L194: 未处理的易出错调用
- ❌ L200: 未处理的易出错调用
- ❌ L233: 未处理的易出错调用
- ❌ L234: 未处理的易出错调用
- ❌ L235: 未处理的易出错调用
- ❌ L273: 未处理的易出错调用
- ❌ L276: 未处理的易出错调用
- 🏷️ `__init__()` L34: "__init__" - snake_case
- 🏷️ `_classify_image()` L42: "_classify_image" - snake_case
- 🏷️ `_get_ocr()` L53: "_get_ocr" - snake_case
- 🏷️ `_get_vm()` L60: "_get_vm" - snake_case
- 🏷️ `_get_hmd()` L67: "_get_hmd" - snake_case
- 🏷️ `_merge_2md_results()` L223: "_merge_2md_results" - snake_case
- 🏷️ `_documents_dir()` L243: "_documents_dir" - snake_case
- 🏷️ `_build_feedback()` L251: "_build_feedback" - snake_case

**详情**:
- 循环复杂度: 平均: 6.7, 最大: 32
- 认知复杂度: 平均: 9.8, 最大: 42
- 嵌套深度: 平均: 1.6, 最大: 5
- 函数长度: 平均: 26.7 行, 最大: 147 行
- 文件长度: 236 代码量 (284 总计)
- 参数数量: 平均: 2.4, 最大: 7
- 代码重复: 0.0% 重复 (0/9)
- 结构分析: 2 个结构问题
- 错误处理: 9/22 个错误被忽略 (40.9%)
- 注释比例: 3.0% (7/236)
- 命名规范: 发现 8 个违规

### 10. psychoscope/static/js/app.js

**糟糕指数: 34.99**

> 行数: 1646 总计, 1499 代码, 50 注释 | 函数: 64 | 类: 0

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 35, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `msgFlow` | L818-963 | 146 | 40 | 4 | 1 | ✗ |
| `sendRecording` | L695-812 | 118 | 38 | 4 | 2 | ✗ |
| `heartbeatPoll` | L1567-1598 | 32 | 11 | 1 | 0 | ✓ |
| `init` | L1612-1643 | 32 | 10 | 2 | 0 | ✓ |
| `openMaintenanceSSE` | L1110-1170 | 61 | 9 | 2 | 0 | ✗ |
| `selectChat` | L477-520 | 44 | 8 | 4 | 1 | ✗ |
| `tryPairLogin` | L401-420 | 20 | 7 | 1 | 0 | ✗ |
| `showTimingLine` | L1065-1083 | 19 | 7 | 2 | 2 | ✗ |
| `showKeyHints` | L1420-1474 | 55 | 7 | 1 | 0 | ✗ |
| `describeAction` | L201-215 | 15 | 6 | 1 | 2 | ✗ |
| `addMessage` | L321-359 | 39 | 6 | 2 | 3 | ✗ |
| `processLineQueue` | L1032-1063 | 32 | 6 | 2 | 0 | ✗ |
| `parseControlTags` | L177-199 | 23 | 5 | 4 | 1 | ✗ |
| `fetchWorldState` | L261-273 | 13 | 5 | 1 | 0 | ✗ |
| `startRecording` | L578-599 | 22 | 5 | 1 | 0 | ✗ |
| `stopRecording` | L601-620 | 20 | 5 | 2 | 1 | ✗ |
| `startWaveform` | L642-672 | 31 | 5 | 1 | 0 | ✗ |
| `getAuthHeader` | L362-367 | 6 | 4 | 1 | 0 | ✓ |
| `tryRecoverLogin` | L422-441 | 20 | 4 | 1 | 0 | ✗ |
| `abortStream` | L979-995 | 17 | 4 | 1 | 0 | ✗ |
| `playAudioBase64Wait` | L1015-1030 | 16 | 4 | 1 | 1 | ✗ |
| `showConfirm` | L1510-1535 | 26 | 4 | 1 | 0 | ✗ |
| `detectTheme` | L10-14 | 5 | 3 | 1 | 0 | ✓ |
| `updateWorldState` | L245-259 | 15 | 3 | 1 | 1 | ✗ |
| `apiCall` | L368-373 | 6 | 3 | 1 | 3 | ✗ |
| `apiGet` | L374-382 | 9 | 3 | 1 | 1 | ✗ |
| `apiPost` | L385-390 | 6 | 3 | 1 | 2 | ✓ |
| `apiPostJson` | L391-399 | 9 | 3 | 1 | 2 | ✗ |
| `renderChatList` | L462-476 | 15 | 3 | 1 | 0 | ✗ |
| `handleImageSelected` | L535-547 | 13 | 3 | 1 | 1 | ✗ |
| `switchInputMode` | L559-576 | 18 | 3 | 1 | 1 | ✓ |
| `stopWaveform` | L674-682 | 9 | 3 | 1 | 0 | ✗ |
| `playAudioBase64` | L1003-1013 | 11 | 3 | 1 | 1 | ✗ |
| `renderMaintTasks` | L1172-1180 | 9 | 3 | 0 | 0 | ✗ |
| `updateMaintProgress` | L1182-1194 | 13 | 3 | 1 | 0 | ✗ |
| `hideConfirm` | L1537-1552 | 16 | 3 | 1 | 0 | ✗ |
| `toggleTheme` | L19-21 | 3 | 2 | 0 | 0 | ✗ |
| `startWorldPolling` | L277-281 | 5 | 2 | 1 | 0 | ✗ |
| `stopWorldPolling` | L282-284 | 3 | 2 | 1 | 0 | ✗ |
| `addLineStatic` | L286-301 | 16 | 2 | 1 | 3 | ✗ |
| `newChat` | L521-528 | 8 | 2 | 1 | 0 | ✗ |
| `removeImage` | L549-556 | 8 | 2 | 1 | 0 | ✗ |
| `cancelRecording` | L622-630 | 9 | 2 | 1 | 0 | ✗ |
| `uncancelRecording` | L632-640 | 9 | 2 | 1 | 0 | ✗ |
| `sendMessage` | L965-977 | 13 | 2 | 1 | 0 | ✗ |
| `toggleTTS` | L998-1002 | 5 | 2 | 0 | 0 | ✓ |
| `checkMaintStatus` | L1196-1205 | 10 | 2 | 1 | 0 | ✗ |
| `hideKeyHints` | L1476-1484 | 9 | 2 | 1 | 0 | ✗ |
| `startHeartbeat` | L1600-1604 | 5 | 2 | 1 | 0 | ✗ |
| `stopHeartbeat` | L1606-1609 | 4 | 2 | 1 | 0 | ✗ |
| `applyTheme` | L15-18 | 4 | 1 | 0 | 1 | ✗ |
| `archiveActiveLines` | L218-224 | 7 | 1 | 0 | 0 | ✓ |
| `addNarrationLine` | L226-233 | 8 | 1 | 0 | 1 | ✗ |
| `addNarratorLine` | L235-243 | 9 | 1 | 0 | 1 | ✗ |
| `addSystemLine` | L303-310 | 8 | 1 | 0 | 1 | ✗ |
| `addErrorLine` | L312-319 | 8 | 1 | 0 | 1 | ✗ |
| `logout` | L443-455 | 13 | 1 | 0 | 0 | ✗ |
| `loadChats` | L458-461 | 4 | 1 | 0 | 0 | ✓ |
| `selectImage` | L531-533 | 3 | 1 | 0 | 0 | ✓ |
| `blobToBase64` | L684-693 | 10 | 1 | 0 | 1 | ✗ |
| `updateStatusBar` | L1086-1089 | 4 | 1 | 0 | 0 | ✓ |
| `updateStatusBarText` | L1090-1092 | 3 | 1 | 0 | 1 | ✗ |
| `createKeyCapSVG` | L1393-1414 | 22 | 1 | 0 | 1 | ✓ |
| `doConfirm` | L1554-1558 | 5 | 1 | 0 | 0 | ✗ |

**全部问题 (53)**

- 🔄 `sendRecording()` L695: 复杂度: 38
- 🔄 `msgFlow()` L818: 复杂度: 40
- 🔄 `heartbeatPoll()` L1567: 复杂度: 11
- 🔄 `selectChat()` L477: 认知复杂度: 16
- 🔄 `sendRecording()` L695: 认知复杂度: 46
- 🔄 `msgFlow()` L818: 认知复杂度: 48
- 🔄 `parseControlTags()` L177: 嵌套深度: 4
- 🔄 `selectChat()` L477: 嵌套深度: 4
- 🔄 `sendRecording()` L695: 嵌套深度: 4
- 🔄 `msgFlow()` L818: 嵌套深度: 4
- 📏 `sendRecording()` L695: 118 代码量
- 📏 `msgFlow()` L818: 146 代码量
- 🏗️ `parseControlTags()` L177: 中等嵌套: 4
- 🏗️ `selectChat()` L477: 中等嵌套: 4
- 🏗️ `sendRecording()` L695: 中等嵌套: 4
- 🏗️ `msgFlow()` L818: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1646 行
- 🏗️ L1: 函数过多: 64
- ❌ L157: 未处理的易出错调用
- ❌ L221: 未处理的易出错调用
- ❌ L450: 未处理的易出错调用
- ❌ L453: 未处理的易出错调用
- ❌ L482: 未处理的易出错调用
- ❌ L506: 未处理的易出错调用
- ❌ L525: 未处理的易出错调用
- ❌ L542: 未处理的易出错调用
- ❌ L553: 未处理的易出错调用
- ❌ L564: 未处理的易出错调用
- ❌ L570: 未处理的易出错调用
- ❌ L571: 未处理的易出错调用
- ❌ L617: 未处理的易出错调用
- ❌ L618: 未处理的易出错调用
- ❌ L626: 未处理的易出错调用
- ❌ L628: 未处理的易出错调用
- ❌ L635: 未处理的易出错调用
- ❌ L637: 未处理的易出错调用
- ❌ L720: 未处理的易出错调用
- ❌ L807: 未处理的易出错调用
- ❌ L846: 未处理的易出错调用
- ❌ L959: 未处理的易出错调用
- ❌ L991: 未处理的易出错调用
- ❌ L1197: 未处理的易出错调用
- ❌ L1215: 未处理的易出错调用
- ❌ L1225: 未处理的易出错调用
- ❌ L1226: 未处理的易出错调用
- ❌ L1245: 未处理的易出错调用
- ❌ L1481: 未处理的易出错调用
- ❌ L1482: 未处理的易出错调用
- ❌ L1513: 未处理的易出错调用
- ❌ L1516: 未处理的易出错调用
- ❌ L1540: 未处理的易出错调用
- ❌ L1542: 未处理的易出错调用
- ❌ L1547: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 4.4, 最大: 40
- 认知复杂度: 平均: 6.5, 最大: 48
- 嵌套深度: 平均: 1.0, 最大: 4
- 函数长度: 平均: 18.4 行, 最大: 146 行
- 文件长度: 1499 代码量 (1646 总计)
- 参数数量: 平均: 0.6, 最大: 3
- 代码重复: 3.1% 重复 (2/64)
- 结构分析: 6 个结构问题
- 错误处理: 35/61 个错误被忽略 (57.4%)
- 注释比例: 3.3% (50/1499)
- 命名规范: 无命名违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `main` | psychoscope/minimal.py | 99 | 8 | 343 |
| `process_stream` | plugins/pipeline.py | 77 | 9 | 376 |
| `create_application` | boot.py | 45 | 4 | 403 |
| `create_engine_with_defaults` | engine.py | 41 | 2 | 231 |
| `msgFlow` | psychoscope/static/js/app.js | 40 | 4 | 146 |
| `_poll_pending_tasks` | plugins/pipeline.py | 38 | 6 | 123 |
| `search` | memory/core.py | 38 | 7 | 128 |
| `sendRecording` | psychoscope/static/js/app.js | 38 | 4 | 118 |
| `_cmd_agent` | main.py | 34 | 3 | 145 |
| `process_scan` | document/doc_processor.py | 32 | 5 | 147 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*