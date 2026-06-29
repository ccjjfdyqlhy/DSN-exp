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
| **糟糕指数** | **79.01/100** |
| 屎山等级 | 😐 微臭青年 |

> 略带清香，偶尔飘过一丝酸爽

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 198 |
| 已跳过 | 537 |
| 耗时 | 1013ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 32529 |
| 总注释行数 | 1407 |
| 整体注释比例 | 4.3% |
| 平均文件大小 | 203 行 |
| 最大文件 | `main.py` (2165) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 195 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 10.00% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 13.74% | 0.0% | 70.0% | 8.5% | ✓✓ |
| 嵌套深度 | 4.17% | 0.0% | 55.0% | 0.0% | ✓✓ |
| 函数长度 | 6.08% | 0.0% | 55.9% | 0.0% | ✓✓ |
| 文件长度 | 2.75% | 0.0% | 91.7% | 0.0% | ✓✓ |
| 参数数量 | 13.70% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.66% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.98% | 0.0% | 82.5% | 0.0% | ✓✓ |
| 错误处理 | 33.12% | 0.0% | 98.8% | 7.5% | ✓ |
| 注释比例 | 42.65% | 0.0% | 100.0% | 40.2% | ○ |
| 命名规范 | 26.93% | 0.0% | 95.7% | 21.7% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. plugins/pipeline.py

**糟糕指数: 50.52**

> 行数: 1051 总计, 857 代码, 45 注释 | 函数: 27 | 类: 1

**问题**: 🔄 复杂度问题: 19, ⚠️ 其他问题: 7, 🏗️ 结构问题: 11, ❌ 错误处理问题: 27, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L778-1050 | 273 | 57 | 7 | 3 | ✓ |
| `_poll_pending_tasks` | L644-766 | 123 | 38 | 6 | 4 | ✓ |
| `_synthesize_lines_sync` | L525-606 | 82 | 23 | 4 | 4 | ✓ |
| `_run_agent_loop` | L276-387 | 112 | 22 | 3 | 2 | ✗ |
| `process` | L144-227 | 84 | 16 | 3 | 2 | ✗ |
| `_run_rest` | L244-268 | 25 | 11 | 4 | 0 | ✗ |
| `_print_timing` | L389-414 | 26 | 9 | 4 | 3 | ✗ |
| `_format_tag_results` | L425-442 | 18 | 8 | 3 | 1 | ✗ |
| `_run_all_plugins` | L617-642 | 26 | 8 | 2 | 5 | ✗ |
| `_dispatch_pre_process` | L466-503 | 38 | 7 | 1 | 2 | ✓ |
| `_call_llm_with_msgs` | L45-71 | 18 | 5 | 2 | 2 | ✓ |
| `_extract_narrations` | L74-89 | 16 | 4 | 3 | 1 | ✓ |
| `_print_plugin_timing` | L416-422 | 7 | 4 | 2 | 2 | ✗ |
| `_assemble_prompt` | L444-462 | 19 | 4 | 1 | 2 | ✓ |
| `_invoke` | L61-69 | 9 | 3 | 2 | 0 | ✗ |
| `_bridge_progress` | L609-615 | 7 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L92-97 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L100-107 | 8 | 2 | 1 | 1 | ✗ |
| `_run_async_background` | L232-274 | 18 | 2 | 0 | 2 | ✗ |
| `timer_enabled` | L25-26 | 2 | 1 | 0 | 0 | ✗ |
| `enable_timer` | L29-31 | 3 | 1 | 0 | 0 | ✗ |
| `disable_timer` | L34-36 | 3 | 1 | 0 | 0 | ✗ |
| `toggle_timer` | L39-42 | 4 | 1 | 0 | 0 | ✗ |
| `__init__` | L124-140 | 17 | 1 | 0 | 8 | ✗ |
| `_dispatch_post_process` | L229-230 | 2 | 1 | 0 | 2 | ✗ |
| `_synthesize_lines` | L507-513 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L515-523 | 9 | 1 | 0 | 3 | ✓ |

**全部问题 (73)**

- 🔄 `process()` L144: 复杂度: 16
- 🔄 `_run_rest()` L244: 复杂度: 11
- 🔄 `_run_agent_loop()` L276: 复杂度: 22
- 🔄 `_synthesize_lines_sync()` L525: 复杂度: 23
- 🔄 `_poll_pending_tasks()` L644: 复杂度: 38
- 🔄 `process_stream()` L778: 复杂度: 57
- 🔄 `process()` L144: 认知复杂度: 22
- 🔄 `_run_rest()` L244: 认知复杂度: 19
- 🔄 `_run_agent_loop()` L276: 认知复杂度: 28
- 🔄 `_print_timing()` L389: 认知复杂度: 17
- 🔄 `_format_tag_results()` L425: 认知复杂度: 14
- 🔄 `_synthesize_lines_sync()` L525: 认知复杂度: 31
- 🔄 `_poll_pending_tasks()` L644: 认知复杂度: 50
- 🔄 `process_stream()` L778: 认知复杂度: 71
- 🔄 `_run_rest()` L244: 嵌套深度: 4
- 🔄 `_print_timing()` L389: 嵌套深度: 4
- 🔄 `_synthesize_lines_sync()` L525: 嵌套深度: 4
- 🔄 `_poll_pending_tasks()` L644: 嵌套深度: 6
- 🔄 `process_stream()` L778: 嵌套深度: 7
- 📏 `process()` L144: 84 代码量
- 📏 `_run_agent_loop()` L276: 112 代码量
- 📏 `_synthesize_lines_sync()` L525: 82 代码量
- 📏 `_poll_pending_tasks()` L644: 123 代码量
- 📏 `process_stream()` L778: 273 代码量
- 📏 `__init__()` L124: 8 参数数量
- 🏗️ `_extract_narrations()` L74: 中等嵌套: 3
- 🏗️ `process()` L144: 中等嵌套: 3
- 🏗️ `_run_rest()` L244: 中等嵌套: 4
- 🏗️ `_run_agent_loop()` L276: 中等嵌套: 3
- 🏗️ `_print_timing()` L389: 中等嵌套: 4
- 🏗️ `_format_tag_results()` L425: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L525: 中等嵌套: 4
- 🏗️ `_poll_pending_tasks()` L644: 嵌套过深: 6
- 🏗️ `process_stream()` L778: 嵌套过深: 7
- 🏗️ L1: 文件过大: 1051 行
- 🏗️ L1: 导入过多: 29
- ❌ L181: 未处理的易出错调用
- ❌ L197: 未处理的易出错调用
- ❌ L213: 未处理的易出错调用
- ❌ L238: 未处理的易出错调用
- ❌ L249: 未处理的易出错调用
- ❌ L256: 未处理的易出错调用
- ❌ L268: 未处理的易出错调用
- ❌ L296: 未处理的易出错调用
- ❌ L318: 未处理的易出错调用
- ❌ L440: 未处理的易出错调用
- ❌ L551: 未处理的易出错调用
- ❌ L599: 未处理的易出错调用
- ❌ L602: 未处理的易出错调用
- ❌ L605: 未处理的易出错调用
- ❌ L615: 未处理的易出错调用
- ❌ L621: 未处理的易出错调用
- ❌ L641: 未处理的易出错调用
- ❌ L642: 未处理的易出错调用
- ❌ L676: 未处理的易出错调用
- ❌ L701: 未处理的易出错调用
- ❌ L738: 未处理的易出错调用
- ❌ L838: 未处理的易出错调用
- ❌ L960: 未处理的易出错调用
- ❌ L974: 未处理的易出错调用
- ❌ L987: 未处理的易出错调用
- ❌ L1007: 未处理的易出错调用
- ❌ L1045: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L45: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L61: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L74: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L92: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L100: "_desc_task" - snake_case
- 🏷️ `__init__()` L124: "__init__" - snake_case
- 🏷️ `_dispatch_post_process()` L229: "_dispatch_post_process" - snake_case
- 🏷️ `_run_async_background()` L232: "_run_async_background" - snake_case
- 🏷️ `_run_rest()` L244: "_run_rest" - snake_case
- 🏷️ `_run_agent_loop()` L276: "_run_agent_loop" - snake_case

**详情**:
- 循环复杂度: 平均: 8.7, 最大: 57
- 认知复杂度: 平均: 12.5, 最大: 71
- 嵌套深度: 平均: 1.9, 最大: 7
- 函数长度: 平均: 35.6 行, 最大: 273 行
- 文件长度: 857 代码量 (1051 总计)
- 参数数量: 平均: 2.0, 最大: 8
- 代码重复: 3.7% 重复 (1/27)
- 结构分析: 11 个结构问题
- 错误处理: 27/61 个错误被忽略 (44.3%)
- 注释比例: 5.3% (45/857)
- 命名规范: 发现 21 个违规

### 2. main.py

**糟糕指数: 48.11**

> 行数: 2165 总计, 1796 代码, 31 注释 | 函数: 71 | 类: 1

**问题**: 🔄 复杂度问题: 36, ⚠️ 其他问题: 28, 🏗️ 结构问题: 13, ❌ 错误处理问题: 13, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_reminder` | L682-810 | 129 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L1058-1198 | 141 | 31 | 3 | 2 | ✓ |
| `_cmd_plan` | L813-875 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1201-1329 | 121 | 21 | 3 | 2 | ✓ |
| `main` | L2029-2160 | 122 | 21 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L1404-1488 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L1922-1988 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_export` | L516-605 | 90 | 13 | 2 | 2 | ✓ |
| `_cmd_memory` | L981-1012 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L608-679 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L925-978 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1671-1710 | 40 | 11 | 2 | 2 | ✓ |
| `_check_port_available` | L123-171 | 49 | 10 | 5 | 2 | ✗ |
| `_env_write` | L174-201 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L1812-1837 | 26 | 10 | 2 | 2 | ✗ |
| `_is_env_configured` | L24-39 | 16 | 9 | 4 | 0 | ✗ |
| `_cmd_users` | L287-325 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L328-364 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_detail` | L1538-1567 | 30 | 9 | 2 | 1 | ✓ |
| `_cmd_memory_reindex` | L1015-1055 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1713-1747 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L1891-1919 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L405-437 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1332-1365 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1368-1401 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1491-1517 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1570-1589 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L1991-2019 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L85-95 | 11 | 5 | 3 | 0 | ✓ |
| `_enable_console_logging` | L235-248 | 14 | 5 | 2 | 0 | ✗ |
| `_try_convert` | L390-402 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L440-459 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L462-489 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L1042-1051 | 10 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1778-1809 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L1840-1866 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L98-112 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L379-387 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1317-1324 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L2117-2126 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L115-120 | 6 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L251-256 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L270-284 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L492-508 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1760-1771 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L1876-1888 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L204-207 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L210-212 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L215-228 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1601-1602 | 2 | 2 | 0 | 7 | ✗ |
| `_h_timer` | L1643-1648 | 6 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1750-1774 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L2022-2026 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L222-223 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L511-513 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L878-922 | 45 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1520-1535 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1592-1593 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1595-1596 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1598-1599 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1604-1605 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1607-1608 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1610-1611 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1613-1614 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1616-1617 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1619-1620 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1623-1624 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1627-1628 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L1631-1632 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L1635-1636 | 2 | 1 | 0 | 7 | ✗ |
| `_h_detail` | L1639-1640 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (99)**

- 🔄 `_cmd_export()` L516: 复杂度: 13
- 🔄 `_cmd_import()` L608: 复杂度: 11
- 🔄 `_cmd_reminder()` L682: 复杂度: 31
- 🔄 `_cmd_plan()` L813: 复杂度: 21
- 🔄 `_cmd_plugin()` L925: 复杂度: 11
- 🔄 `_cmd_memory()` L981: 复杂度: 12
- 🔄 `_cmd_memory_query()` L1058: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1201: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1404: 复杂度: 17
- 🔄 `_cmd_persona()` L1671: 复杂度: 11
- 🔄 `_cmd_hibernate_check()` L1922: 复杂度: 14
- 🔄 `main()` L2029: 复杂度: 21
- 🔄 `_is_env_configured()` L24: 认知复杂度: 17
- 🔄 `_check_port_available()` L123: 认知复杂度: 20
- 🔄 `_env_write()` L174: 认知复杂度: 20
- 🔄 `_cmd_users()` L287: 认知复杂度: 13
- 🔄 `_cmd_status()` L328: 认知复杂度: 13
- 🔄 `_cmd_export()` L516: 认知复杂度: 17
- 🔄 `_cmd_import()` L608: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L682: 认知复杂度: 39
- 🔄 `_cmd_plan()` L813: 认知复杂度: 25
- 🔄 `_cmd_plugin()` L925: 认知复杂度: 15
- 🔄 `_cmd_memory()` L981: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L1058: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1201: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1404: 认知复杂度: 21
- 🔄 `_cmd_detail()` L1538: 认知复杂度: 13
- 🔄 `_cmd_persona()` L1671: 认知复杂度: 15
- 🔄 `_persona_status()` L1713: 认知复杂度: 14
- 🔄 `_persona_materials()` L1812: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L1922: 认知复杂度: 20
- 🔄 `main()` L2029: 认知复杂度: 27
- 🔄 `_is_env_configured()` L24: 嵌套深度: 4
- 🔄 `_check_port_available()` L123: 嵌套深度: 5
- 🔄 `_env_write()` L174: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L682: 嵌套深度: 4
- 📏 `_cmd_export()` L516: 90 代码量
- 📏 `_cmd_import()` L608: 72 代码量
- 📏 `_cmd_reminder()` L682: 129 代码量
- 📏 `_cmd_plan()` L813: 63 代码量
- 📏 `_cmd_plugin()` L925: 54 代码量
- 📏 `_cmd_memory_query()` L1058: 141 代码量
- 📏 `_cmd_memory_rebuild()` L1201: 121 代码量
- 📏 `_cmd_memory_list()` L1404: 85 代码量
- 📏 `_cmd_hibernate_check()` L1922: 67 代码量
- 📏 `main()` L2029: 122 代码量
- 📏 `_execute_command()` L1570: 9 参数数量
- 📏 `_h_newbind()` L1592: 7 参数数量
- 📏 `_h_users()` L1595: 7 参数数量
- 📏 `_h_status()` L1598: 7 参数数量
- 📏 `_h_plugin()` L1601: 7 参数数量
- 📏 `_h_memory()` L1604: 7 参数数量
- 📏 `_h_prompt()` L1607: 7 参数数量
- 📏 `_h_config()` L1610: 7 参数数量
- 📏 `_h_listconfig()` L1613: 7 参数数量
- 📏 `_h_persona()` L1616: 7 参数数量
- 📏 `_h_help()` L1619: 7 参数数量
- 📏 `_h_export()` L1623: 7 参数数量
- 📏 `_h_import()` L1627: 7 参数数量
- 📏 `_h_reminder()` L1631: 7 参数数量
- 📏 `_h_plan()` L1635: 7 参数数量
- 📏 `_h_detail()` L1639: 7 参数数量
- 📏 `_h_timer()` L1643: 7 参数数量
- 🏗️ `_is_env_configured()` L24: 中等嵌套: 4
- 🏗️ `_env_backup_rotate()` L85: 中等嵌套: 3
- 🏗️ `_check_port_available()` L123: 嵌套过深: 5
- 🏗️ `_env_write()` L174: 嵌套过深: 5
- 🏗️ `_cmd_reminder()` L682: 中等嵌套: 4
- 🏗️ `_cmd_memory_query()` L1058: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1201: 中等嵌套: 3
- 🏗️ `_persona_status()` L1713: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L1922: 中等嵌套: 3
- 🏗️ `main()` L2029: 中等嵌套: 3
- 🏗️ L1: 文件过大: 2165 行
- 🏗️ L1: 函数过多: 71
- 🏗️ L1: 导入过多: 51
- ❌ L130: 未处理的易出错调用
- ❌ L313: 未处理的易出错调用
- ❌ L321: 未处理的易出错调用
- ❌ L650: 未处理的易出错调用
- ❌ L656: 未处理的易出错调用
- ❌ L670: 未处理的易出错调用
- ❌ L676: 未处理的易出错调用
- ❌ L973: 未处理的易出错调用
- ❌ L1485: 未处理的易出错调用
- ❌ L1745: 未处理的易出错调用
- ❌ L1800: 未处理的易出错调用
- ❌ L1801: 未处理的易出错调用
- ❌ L1802: 未处理的易出错调用
- 🏷️ `_is_env_configured()` L24: "_is_env_configured" - snake_case
- 🏷️ `_env_backup_rotate()` L85: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L98: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L115: "_env_backup_count" - snake_case
- 🏷️ `_check_port_available()` L123: "_check_port_available" - snake_case
- 🏷️ `_env_write()` L174: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L215: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L235: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L251: "_disable_console_logging" - snake_case
- 🏷️ `_cmd_newbind()` L270: "_cmd_newbind" - snake_case

**详情**:
- 循环复杂度: 平均: 6.3, 最大: 31
- 认知复杂度: 平均: 9.1, 最大: 39
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 27.0 行, 最大: 141 行
- 文件长度: 1796 代码量 (2165 总计)
- 参数数量: 平均: 2.7, 最大: 9
- 代码重复: 1.4% 重复 (1/71)
- 结构分析: 13 个结构问题
- 错误处理: 13/54 个错误被忽略 (24.1%)
- 注释比例: 1.7% (31/1796)
- 命名规范: 发现 68 个违规

### 3. engine.py

**糟糕指数: 44.81**

> 行数: 1139 总计, 978 代码, 24 注释 | 函数: 41 | 类: 2

**问题**: 🔄 复杂度问题: 12, ⚠️ 其他问题: 6, 📋 重复问题: 5, 🏗️ 结构问题: 8, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L900-1138 | 239 | 44 | 2 | 12 | ✓ |
| `_init_prompt` | L480-527 | 48 | 17 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L624-662 | 39 | 15 | 2 | 1 | ✗ |
| `build_context` | L702-735 | 34 | 11 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L602-622 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L664-687 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L737-773 | 37 | 9 | 2 | 8 | ✓ |
| `_generate_result_message` | L264-311 | 48 | 8 | 2 | 3 | ✗ |
| `_register_context_plugins` | L581-600 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L775-794 | 20 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L219-237 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L313-334 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L336-364 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L366-391 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L411-431 | 21 | 6 | 2 | 1 | ✗ |
| `_inject_system_skill_deps` | L433-464 | 32 | 6 | 3 | 1 | ✓ |
| `_inject_v3_to_exa_evolution` | L466-478 | 13 | 6 | 3 | 1 | ✓ |
| `index_prompts_for_chat` | L802-822 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L826-874 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L878-886 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L191-205 | 15 | 5 | 3 | 1 | ✗ |
| `_dispatch_task_completion` | L207-217 | 11 | 5 | 2 | 3 | ✗ |
| `_init_plugins` | L529-546 | 18 | 5 | 1 | 1 | ✗ |
| `from_subapp` | L75-92 | 18 | 3 | 0 | 1 | ✗ |
| `__init__` | L106-138 | 33 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L168-187 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L250-262 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L393-409 | 17 | 3 | 2 | 1 | ✗ |
| `_plugin_enabled` | L548-553 | 6 | 3 | 1 | 2 | ✗ |
| `_init_database` | L159-166 | 8 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L239-248 | 10 | 2 | 1 | 3 | ✗ |
| `_register_filter_plugins` | L555-562 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L564-579 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L796-797 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L799-800 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L838-844 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L848-857 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L142-157 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L689-698 | 10 | 1 | 0 | 1 | ✗ |
| `create_engine` | L891-897 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (44)**

- 🔄 `_init_prompt()` L480: 复杂度: 17
- 🔄 `_register_execution_plugins()` L624: 复杂度: 15
- 🔄 `build_context()` L702: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L900: 复杂度: 44
- 🔄 `_init_prompt()` L480: 认知复杂度: 25
- 🔄 `_register_personality_plugins()` L602: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L624: 认知复杂度: 19
- 🔄 `_register_output_plugins()` L664: 认知复杂度: 13
- 🔄 `build_context()` L702: 认知复杂度: 13
- 🔄 `chat()` L737: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L900: 认知复杂度: 48
- 🔄 `_init_prompt()` L480: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L900: 239 代码量
- 📏 `build_context()` L702: 8 参数数量
- 📏 `chat()` L737: 8 参数数量
- 📏 `chat_stream()` L775: 8 参数数量
- 📏 `create_engine_with_defaults()` L900: 12 参数数量
- 📋 `from_subapp()` L75: 重复模式: from_subapp, _init_memory
- 📋 `_init_database()` L159: 重复模式: _init_database, _handle_reminder_completion
- 📋 `_process_task_completion()` L191: 重复模式: _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L250: 重复模式: _handle_reasoner_completion, _register_context_plugins
- 📋 `_register_execution_plugins()` L624: 重复模式: _register_execution_plugins, chat_stream
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L191: 中等嵌套: 3
- 🏗️ `_init_memory()` L336: 中等嵌套: 3
- 🏗️ `_inject_system_skill_deps()` L433: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L466: 中等嵌套: 3
- 🏗️ `_init_prompt()` L480: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1139 行
- 🏗️ L1: 导入过多: 90
- ❌ L220: 未处理的易出错调用
- ❌ L234: 未处理的易出错调用
- ❌ L280: 未处理的易出错调用
- ❌ L842: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L42: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L106: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L142: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L159: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L168: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L191: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L207: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L219: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L239: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L250: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 6.3, 最大: 44
- 认知复杂度: 平均: 9.2, 最大: 48
- 嵌套深度: 平均: 1.5, 最大: 4
- 函数长度: 平均: 24.6 行, 最大: 239 行
- 文件长度: 978 代码量 (1139 总计)
- 参数数量: 平均: 2.2, 最大: 12
- 代码重复: 12.2% 重复 (5/41)
- 结构分析: 8 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.5% (24/978)
- 命名规范: 发现 28 个违规

### 4. memory/core.py

**糟糕指数: 44.10**

> 行数: 770 总计, 633 代码, 42 注释 | 函数: 26 | 类: 1

**问题**: 🔄 复杂度问题: 14, ⚠️ 其他问题: 8, 📋 重复问题: 2, 🏗️ 结构问题: 5, ❌ 错误处理问题: 15, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L245-373 | 129 | 38 | 7 | 8 | ✓ |
| `_format_detail_results` | L732-769 | 38 | 13 | 4 | 2 | ✗ |
| `reindex_embeddings` | L384-463 | 80 | 11 | 3 | 3 | ✓ |
| `_format_search_results` | L699-729 | 31 | 11 | 2 | 3 | ✗ |
| `handle_tags` | L572-599 | 28 | 9 | 2 | 4 | ✗ |
| `_handle_recall` | L601-626 | 26 | 9 | 3 | 4 | ✗ |
| `_format_timedelta` | L674-696 | 23 | 9 | 2 | 1 | ✗ |
| `rebuild_summaries` | L469-529 | 61 | 8 | 3 | 2 | ✓ |
| `_cosine_similarity` | L201-209 | 9 | 6 | 1 | 2 | ✗ |
| `summarize_turn` | L92-117 | 26 | 5 | 1 | 7 | ✓ |
| `_do_summarize` | L119-148 | 30 | 5 | 2 | 6 | ✗ |
| `assemble_context` | L215-239 | 25 | 5 | 1 | 4 | ✗ |
| `_build_round_text` | L531-545 | 15 | 5 | 2 | 4 | ✓ |
| `_build_round_messages` | L547-566 | 20 | 5 | 2 | 4 | ✓ |
| `_embed_raw_round` | L171-190 | 20 | 4 | 2 | 6 | ✓ |
| `__init__` | L29-42 | 14 | 3 | 0 | 4 | ✗ |
| `_decrypt` | L83-86 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L632-642 | 11 | 2 | 1 | 4 | ✗ |
| `delete_memo` | L660-667 | 8 | 2 | 1 | 2 | ✗ |
| `_init_table` | L44-76 | 33 | 1 | 0 | 1 | ✗ |
| `_encrypt` | L80-81 | 2 | 1 | 0 | 3 | ✗ |
| `_get_exp_memories` | L150-165 | 16 | 1 | 0 | 3 | ✗ |
| `_pack_embedding` | L193-194 | 2 | 1 | 0 | 1 | ✗ |
| `_unpack_embedding` | L197-198 | 2 | 1 | 0 | 1 | ✗ |
| `get_detail` | L375-378 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L644-658 | 15 | 1 | 0 | 3 | ✗ |

**全部问题 (53)**

- 🔄 `search()` L245: 复杂度: 38
- 🔄 `reindex_embeddings()` L384: 复杂度: 11
- 🔄 `_format_search_results()` L699: 复杂度: 11
- 🔄 `_format_detail_results()` L732: 复杂度: 13
- 🔄 `search()` L245: 认知复杂度: 52
- 🔄 `reindex_embeddings()` L384: 认知复杂度: 17
- 🔄 `rebuild_summaries()` L469: 认知复杂度: 14
- 🔄 `handle_tags()` L572: 认知复杂度: 13
- 🔄 `_handle_recall()` L601: 认知复杂度: 15
- 🔄 `_format_timedelta()` L674: 认知复杂度: 13
- 🔄 `_format_search_results()` L699: 认知复杂度: 15
- 🔄 `_format_detail_results()` L732: 认知复杂度: 21
- 🔄 `search()` L245: 嵌套深度: 7
- 🔄 `_format_detail_results()` L732: 嵌套深度: 4
- 📏 `search()` L245: 129 代码量
- 📏 `reindex_embeddings()` L384: 80 代码量
- 📏 `rebuild_summaries()` L469: 61 代码量
- 📏 `summarize_turn()` L92: 7 参数数量
- 📏 `_do_summarize()` L119: 6 参数数量
- 📏 `_embed_raw_round()` L171: 6 参数数量
- 📏 `search()` L245: 8 参数数量
- 📋 `_get_exp_memories()` L150: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L632: 重复模式: add_memo, delete_memo
- 🏗️ `search()` L245: 嵌套过深: 7
- 🏗️ `reindex_embeddings()` L384: 中等嵌套: 3
- 🏗️ `rebuild_summaries()` L469: 中等嵌套: 3
- 🏗️ `_handle_recall()` L601: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L732: 中等嵌套: 4
- ❌ L46: 未处理的易出错调用
- ❌ L57: 未处理的易出错调用
- ❌ L61: 未处理的易出错调用
- ❌ L72: 未处理的易出错调用
- ❌ L76: 未处理的易出错调用
- ❌ L140: 未处理的易出错调用
- ❌ L182: 未处理的易出错调用
- ❌ L187: 未处理的易出错调用
- ❌ L450: 未处理的易出错调用
- ❌ L455: 未处理的易出错调用
- ❌ L516: 未处理的易出错调用
- ❌ L520: 未处理的易出错调用
- ❌ L641: 未处理的易出错调用
- ❌ L666: 未处理的易出错调用
- ❌ L746: 未处理的易出错调用
- 🏷️ `__init__()` L29: "__init__" - snake_case
- 🏷️ `_init_table()` L44: "_init_table" - snake_case
- 🏷️ `_encrypt()` L80: "_encrypt" - snake_case
- 🏷️ `_decrypt()` L83: "_decrypt" - snake_case
- 🏷️ `_do_summarize()` L119: "_do_summarize" - snake_case
- 🏷️ `_get_exp_memories()` L150: "_get_exp_memories" - snake_case
- 🏷️ `_embed_raw_round()` L171: "_embed_raw_round" - snake_case
- 🏷️ `_pack_embedding()` L193: "_pack_embedding" - snake_case
- 🏷️ `_unpack_embedding()` L197: "_unpack_embedding" - snake_case
- 🏷️ `_cosine_similarity()` L201: "_cosine_similarity" - snake_case

**详情**:
- 循环复杂度: 平均: 6.1, 最大: 38
- 认知复杂度: 平均: 9.2, 最大: 52
- 嵌套深度: 平均: 1.5, 最大: 7
- 函数长度: 平均: 25.8 行, 最大: 129 行
- 文件长度: 633 代码量 (770 总计)
- 参数数量: 平均: 3.4, 最大: 8
- 代码重复: 7.7% 重复 (2/26)
- 结构分析: 5 个结构问题
- 错误处理: 15/36 个错误被忽略 (41.7%)
- 注释比例: 6.6% (42/633)
- 命名规范: 发现 17 个违规

### 5. psychoscope/minimal.py

**糟糕指数: 42.09**

> 行数: 1149 总计, 986 代码, 12 注释 | 函数: 50 | 类: 5

**问题**: 🔄 复杂度问题: 25, ⚠️ 其他问题: 5, 📋 重复问题: 2, 🏗️ 结构问题: 15, ❌ 错误处理问题: 18, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L935-1146 | 203 | 47 | 6 | 0 | ✗ |
| `_loop` | L454-514 | 61 | 23 | 6 | 1 | ✗ |
| `_handle_sse_stream` | L371-416 | 46 | 17 | 4 | 5 | ✗ |
| `authenticate` | L194-275 | 82 | 14 | 2 | 3 | ✗ |
| `_loop` | L607-636 | 30 | 10 | 5 | 1 | ✗ |
| `stop_and_send` | L711-743 | 33 | 10 | 2 | 1 | ✗ |
| `print_system_info` | L897-933 | 37 | 10 | 4 | 1 | ✓ |
| `_capture_loop` | L745-775 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L801-827 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L125-142 | 18 | 8 | 3 | 1 | ✗ |
| `_tts_worker` | L172-192 | 21 | 8 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L71-84 | 14 | 6 | 5 | 0 | ✓ |
| `send_audio` | L331-369 | 39 | 6 | 2 | 2 | ✗ |
| `_trigger` | L638-662 | 25 | 6 | 4 | 2 | ✓ |
| `_verify_api_key` | L277-294 | 18 | 5 | 3 | 1 | ✗ |
| `send_async` | L313-329 | 17 | 5 | 2 | 2 | ✓ |
| `skip_latest` | L541-559 | 19 | 5 | 2 | 1 | ✓ |
| `_sync` | L561-587 | 27 | 5 | 3 | 1 | ✓ |
| `_play_beep` | L98-112 | 15 | 4 | 1 | 2 | ✓ |
| `__init__` | L156-170 | 15 | 4 | 1 | 3 | ✗ |
| `start` | L689-709 | 21 | 4 | 1 | 1 | ✗ |
| `print_header` | L829-859 | 31 | 4 | 1 | 3 | ✗ |
| `load_config` | L144-150 | 7 | 3 | 2 | 0 | ✗ |
| `add_task` | L446-452 | 7 | 3 | 2 | 2 | ✓ |
| `_load_local` | L589-595 | 7 | 3 | 2 | 1 | ✗ |
| `print_personality` | L861-886 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L46-66 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L115-123 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L296-299 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L433-439 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L441-444 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L526-532 | 7 | 2 | 1 | 1 | ✗ |
| `_save_local` | L597-605 | 9 | 2 | 1 | 2 | ✗ |
| `start` | L783-788 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L790-793 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L795-799 | 5 | 2 | 1 | 2 | ✗ |
| `toggle_standby` | L888-894 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L996-1004 | 9 | 2 | 1 | 2 | ✗ |
| `save_config` | L152-153 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L301-303 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L305-307 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L309-311 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L425-431 | 7 | 1 | 0 | 3 | ✗ |
| `__init__` | L520-524 | 5 | 1 | 0 | 2 | ✗ |
| `stop` | L534-535 | 2 | 1 | 0 | 1 | ✗ |
| `sync_now` | L537-539 | 3 | 1 | 0 | 1 | ✓ |
| `_type_label` | L665-670 | 6 | 1 | 0 | 1 | ✗ |
| `__init__` | L674-683 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L686-687 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L778-781 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (73)**

- 🔄 `authenticate()` L194: 复杂度: 14
- 🔄 `_handle_sse_stream()` L371: 复杂度: 17
- 🔄 `_loop()` L454: 复杂度: 23
- 🔄 `main()` L935: 复杂度: 47
- 🔄 `_detect_tts_sample_rate()` L71: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L125: 认知复杂度: 14
- 🔄 `_tts_worker()` L172: 认知复杂度: 14
- 🔄 `authenticate()` L194: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L371: 认知复杂度: 25
- 🔄 `_loop()` L454: 认知复杂度: 35
- 🔄 `_loop()` L607: 认知复杂度: 20
- 🔄 `_trigger()` L638: 认知复杂度: 14
- 🔄 `stop_and_send()` L711: 认知复杂度: 14
- 🔄 `_capture_loop()` L745: 认知复杂度: 15
- 🔄 `_loop()` L801: 认知复杂度: 19
- 🔄 `print_system_info()` L897: 认知复杂度: 18
- 🔄 `main()` L935: 认知复杂度: 59
- 🔄 `_detect_tts_sample_rate()` L71: 嵌套深度: 5
- 🔄 `_handle_sse_stream()` L371: 嵌套深度: 4
- 🔄 `_loop()` L454: 嵌套深度: 6
- 🔄 `_loop()` L607: 嵌套深度: 5
- 🔄 `_trigger()` L638: 嵌套深度: 4
- 🔄 `_loop()` L801: 嵌套深度: 5
- 🔄 `print_system_info()` L897: 嵌套深度: 4
- 🔄 `main()` L935: 嵌套深度: 6
- 📏 `authenticate()` L194: 82 代码量
- 📏 `_loop()` L454: 61 代码量
- 📏 `main()` L935: 203 代码量
- 📋 `_tts_worker()` L172: 重复模式: _tts_worker, __init__, _loop
- 📋 `_trigger()` L638: 重复模式: _trigger, __init__
- 🏗️ `_detect_tts_sample_rate()` L71: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L125: 中等嵌套: 3
- 🏗️ `_tts_worker()` L172: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L277: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L371: 中等嵌套: 4
- 🏗️ `_loop()` L454: 嵌套过深: 6
- 🏗️ `_sync()` L561: 中等嵌套: 3
- 🏗️ `_loop()` L607: 嵌套过深: 5
- 🏗️ `_trigger()` L638: 中等嵌套: 4
- 🏗️ `_capture_loop()` L745: 中等嵌套: 3
- 🏗️ `_loop()` L801: 嵌套过深: 5
- 🏗️ `print_system_info()` L897: 中等嵌套: 4
- 🏗️ `main()` L935: 嵌套过深: 6
- 🏗️ L1: 文件过大: 1149 行
- 🏗️ L1: 导入过多: 25
- ❌ L76: 未处理的易出错调用
- ❌ L118: 未处理的易出错调用
- ❌ L411: 未处理的易出错调用
- ❌ L477: 未处理的易出错调用
- ❌ L491: 未处理的易出错调用
- ❌ L506: 未处理的易出错调用
- ❌ L555: 未处理的易出错调用
- ❌ L583: 未处理的易出错调用
- ❌ L652: 未处理的易出错调用
- ❌ L657: 未处理的易出错调用
- ❌ L660: 未处理的易出错调用
- ❌ L729: 未处理的易出错调用
- ❌ L814: 未处理的易出错调用
- ❌ L823: 未处理的易出错调用
- ❌ L882: 未处理的易出错调用
- ❌ L904: 未处理的易出错调用
- ❌ L929: 未处理的易出错调用
- ❌ L1088: 未处理的易出错调用
- 🏷️ `_detect_tts_sample_rate()` L71: "_detect_tts_sample_rate" - snake_case
- 🏷️ `_play_beep()` L98: "_play_beep" - snake_case
- 🏷️ `__init__()` L156: "__init__" - snake_case
- 🏷️ `_tts_worker()` L172: "_tts_worker" - snake_case
- 🏷️ `_verify_api_key()` L277: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L296: "_headers" - snake_case
- 🏷️ `_http_get()` L301: "_http_get" - snake_case
- 🏷️ `_http_post()` L305: "_http_post" - snake_case
- 🏷️ `_http_post_stream()` L309: "_http_post_stream" - snake_case
- 🏷️ `_handle_sse_stream()` L371: "_handle_sse_stream" - snake_case

**详情**:
- 循环复杂度: 平均: 5.3, 最大: 47
- 认知复杂度: 平均: 8.9, 最大: 59
- 嵌套深度: 平均: 1.8, 最大: 6
- 函数长度: 平均: 20.4 行, 最大: 203 行
- 文件长度: 986 代码量 (1149 总计)
- 参数数量: 平均: 1.4, 最大: 5
- 代码重复: 6.0% 重复 (3/50)
- 结构分析: 15 个结构问题
- 错误处理: 18/101 个错误被忽略 (17.8%)
- 注释比例: 1.2% (12/986)
- 命名规范: 发现 23 个违规

### 6. plugins/builtin/models_plugin.py

**糟糕指数: 37.58**

> 行数: 227 总计, 193 代码, 4 注释 | 函数: 9 | 类: 1

**问题**: 🔄 复杂度问题: 3, ⚠️ 其他问题: 2, 🏗️ 结构问题: 2, ❌ 错误处理问题: 3, 📝 注释问题: 1, 🏷️ 命名问题: 4

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `on_hook` | L55-135 | 81 | 21 | 6 | 3 | ✗ |
| `invoke` | L199-214 | 16 | 7 | 1 | 4 | ✗ |
| `_build_tools_schema` | L137-157 | 21 | 6 | 3 | 1 | ✗ |
| `set_skill_registry` | L46-49 | 4 | 2 | 0 | 2 | ✗ |
| `_create_chat` | L159-173 | 15 | 2 | 1 | 2 | ✗ |
| `_clean_reply` | L176-197 | 22 | 2 | 1 | 1 | ✗ |
| `__init__` | L22-44 | 23 | 1 | 0 | 10 | ✗ |
| `on_load` | L51-53 | 3 | 1 | 0 | 1 | ✗ |
| `describe_image` | L216-226 | 11 | 1 | 0 | 3 | ✗ |

**全部问题 (14)**

- 🔄 `on_hook()` L55: 复杂度: 21
- 🔄 `on_hook()` L55: 认知复杂度: 33
- 🔄 `on_hook()` L55: 嵌套深度: 6
- 📏 `on_hook()` L55: 81 代码量
- 📏 `__init__()` L22: 10 参数数量
- 🏗️ `on_hook()` L55: 嵌套过深: 6
- 🏗️ `_build_tools_schema()` L137: 中等嵌套: 3
- ❌ L96: 未处理的易出错调用
- ❌ L97: 未处理的易出错调用
- ❌ L105: 未处理的易出错调用
- 🏷️ `__init__()` L22: "__init__" - snake_case
- 🏷️ `_build_tools_schema()` L137: "_build_tools_schema" - snake_case
- 🏷️ `_create_chat()` L159: "_create_chat" - snake_case
- 🏷️ `_clean_reply()` L176: "_clean_reply" - snake_case

**详情**:
- 循环复杂度: 平均: 4.8, 最大: 21
- 认知复杂度: 平均: 7.4, 最大: 33
- 嵌套深度: 平均: 1.3, 最大: 6
- 函数长度: 平均: 21.8 行, 最大: 81 行
- 文件长度: 193 代码量 (227 总计)
- 参数数量: 平均: 3.0, 最大: 10
- 代码重复: 0.0% 重复 (0/9)
- 结构分析: 2 个结构问题
- 错误处理: 3/5 个错误被忽略 (60.0%)
- 注释比例: 2.1% (4/193)
- 命名规范: 发现 4 个违规

### 7. models/clients.py

**糟糕指数: 35.04**

> 行数: 1024 总计, 847 代码, 21 注释 | 函数: 51 | 类: 5

**问题**: 🔄 复杂度问题: 14, ⚠️ 其他问题: 9, 🏗️ 结构问题: 7, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_and_append` | L158-250 | 93 | 20 | 3 | 3 | ✗ |
| `_call_llm` | L743-815 | 60 | 17 | 5 | 7 | ✓ |
| `_ocr_single` | L950-1013 | 57 | 13 | 5 | 3 | ✗ |
| `_call_embed_api` | L631-684 | 41 | 11 | 5 | 2 | ✓ |
| `describe_images` | L485-530 | 46 | 9 | 2 | 5 | ✓ |
| `classify_image` | L532-579 | 48 | 8 | 2 | 4 | ✓ |
| `__init__` | L895-921 | 27 | 8 | 1 | 5 | ✗ |
| `__init__` | L709-741 | 33 | 7 | 1 | 8 | ✗ |
| `summarize_dialog` | L843-876 | 34 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L33-41 | 9 | 6 | 1 | 1 | ✓ |
| `__init__` | L289-338 | 50 | 6 | 1 | 8 | ✓ |
| `_do_call_chat_api` | L352-370 | 19 | 6 | 4 | 2 | ✓ |
| `_call_and_append` | L385-422 | 38 | 6 | 2 | 1 | ✗ |
| `describe_image` | L451-483 | 33 | 6 | 1 | 5 | ✓ |
| `_unload_lmstudio_model` | L66-87 | 22 | 5 | 2 | 2 | ✓ |
| `__init__` | L104-138 | 35 | 5 | 1 | 8 | ✗ |
| `_do_request` | L765-777 | 13 | 5 | 2 | 0 | ✗ |
| `summarize_text` | L817-838 | 22 | 5 | 1 | 3 | ✓ |
| `send_message` | L372-379 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L594-614 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L616-623 | 8 | 4 | 1 | 2 | ✓ |
| `ocr_batch` | L928-948 | 21 | 4 | 1 | 3 | ✓ |
| `_load_lmstudio_model` | L44-63 | 20 | 3 | 1 | 4 | ✓ |
| `send_message` | L140-145 | 6 | 3 | 1 | 4 | ✗ |
| `last_tool_calls` | L152-156 | 5 | 3 | 1 | 1 | ✗ |
| `_call_chat_api` | L345-350 | 6 | 3 | 2 | 2 | ✓ |
| `_do_request` | L636-648 | 13 | 3 | 1 | 0 | ✗ |
| `_do_request` | L970-976 | 7 | 3 | 1 | 0 | ✗ |
| `embed_batch` | L625-629 | 5 | 2 | 1 | 2 | ✓ |
| `ocr` | L923-926 | 4 | 2 | 0 | 3 | ✓ |
| `toggle_detail_chats` | L19-23 | 5 | 1 | 0 | 0 | ✓ |
| `toggle_detail_actions` | L26-30 | 5 | 1 | 0 | 0 | ✓ |
| `continue_conversation` | L147-149 | 3 | 1 | 0 | 3 | ✗ |
| `reset_conversation` | L252-255 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L257-263 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L265-272 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L274-277 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L279-280 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L340-341 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L381-383 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L424-427 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L429-435 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L437-444 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L446-449 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L581-582 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L686-687 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L689-690 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L840-841 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_loaded` | L1015-1016 | 2 | 1 | 0 | 1 | ✗ |
| `unload` | L1018-1020 | 3 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1022-1023 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (43)**

- 🔄 `_call_and_append()` L158: 复杂度: 20
- 🔄 `_call_embed_api()` L631: 复杂度: 11
- 🔄 `_call_llm()` L743: 复杂度: 17
- 🔄 `_ocr_single()` L950: 复杂度: 13
- 🔄 `_call_and_append()` L158: 认知复杂度: 26
- 🔄 `_do_call_chat_api()` L352: 认知复杂度: 14
- 🔄 `describe_images()` L485: 认知复杂度: 13
- 🔄 `_call_embed_api()` L631: 认知复杂度: 21
- 🔄 `_call_llm()` L743: 认知复杂度: 27
- 🔄 `_ocr_single()` L950: 认知复杂度: 23
- 🔄 `_do_call_chat_api()` L352: 嵌套深度: 4
- 🔄 `_call_embed_api()` L631: 嵌套深度: 5
- 🔄 `_call_llm()` L743: 嵌套深度: 5
- 🔄 `_ocr_single()` L950: 嵌套深度: 5
- 📏 `_call_and_append()` L158: 93 代码量
- 📏 `_call_llm()` L743: 60 代码量
- 📏 `_ocr_single()` L950: 57 代码量
- 📏 `__init__()` L104: 8 参数数量
- 📏 `__init__()` L289: 8 参数数量
- 📏 `__init__()` L594: 6 参数数量
- 📏 `__init__()` L709: 8 参数数量
- 📏 `_call_llm()` L743: 7 参数数量
- 🏗️ `_call_and_append()` L158: 中等嵌套: 3
- 🏗️ `_do_call_chat_api()` L352: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L631: 嵌套过深: 5
- 🏗️ `_call_llm()` L743: 嵌套过深: 5
- 🏗️ `_ocr_single()` L950: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1024 行
- 🏗️ L1: 函数过多: 51
- ❌ L59: 未处理的易出错调用
- ❌ L154: 未处理的易出错调用
- ❌ L208: 未处理的易出错调用
- ❌ L211: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L33: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L44: "_load_lmstudio_model" - snake_case
- 🏷️ `_unload_lmstudio_model()` L66: "_unload_lmstudio_model" - snake_case
- 🏷️ `__init__()` L104: "__init__" - snake_case
- 🏷️ `_call_and_append()` L158: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L279: "__repr__" - snake_case
- 🏷️ `__init__()` L289: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L340: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L345: "_call_chat_api" - snake_case
- 🏷️ `_do_call_chat_api()` L352: "_do_call_chat_api" - snake_case

**详情**:
- 循环复杂度: 平均: 4.1, 最大: 20
- 认知复杂度: 平均: 6.1, 最大: 27
- 嵌套深度: 平均: 1.0, 最大: 5
- 函数长度: 平均: 17.4 行, 最大: 93 行
- 文件长度: 847 代码量 (1024 总计)
- 参数数量: 平均: 2.4, 最大: 8
- 代码重复: 2.0% 重复 (1/51)
- 结构分析: 7 个结构问题
- 错误处理: 4/30 个错误被忽略 (13.3%)
- 注释比例: 2.5% (21/847)
- 命名规范: 发现 26 个违规

### 8. psychoscope/static/js/app.js

**糟糕指数: 34.49**

> 行数: 1506 总计, 1371 代码, 45 注释 | 函数: 57 | 类: 0

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 35, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `msgFlow` | L756-886 | 131 | 38 | 4 | 1 | ✗ |
| `sendRecording` | L646-750 | 105 | 36 | 4 | 2 | ✗ |
| `init` | L1473-1503 | 31 | 10 | 2 | 0 | ✓ |
| `openMaintenanceSSE` | L1027-1087 | 61 | 9 | 2 | 0 | ✗ |
| `selectChat` | L428-471 | 44 | 8 | 4 | 1 | ✗ |
| `tryPairLogin` | L353-372 | 20 | 7 | 1 | 0 | ✗ |
| `showTimingLine` | L982-1000 | 19 | 7 | 2 | 2 | ✗ |
| `showKeyHints` | L1326-1380 | 55 | 7 | 1 | 0 | ✗ |
| `describeAction` | L194-208 | 15 | 6 | 1 | 2 | ✗ |
| `addMessage` | L273-311 | 39 | 6 | 2 | 3 | ✗ |
| `processLineQueue` | L954-980 | 27 | 6 | 2 | 0 | ✗ |
| `parseControlTags` | L172-192 | 21 | 5 | 4 | 1 | ✗ |
| `startRecording` | L529-550 | 22 | 5 | 1 | 0 | ✗ |
| `stopRecording` | L552-571 | 20 | 5 | 2 | 1 | ✗ |
| `startWaveform` | L593-623 | 31 | 5 | 1 | 0 | ✗ |
| `getAuthHeader` | L314-319 | 6 | 4 | 1 | 0 | ✓ |
| `tryRecoverLogin` | L374-393 | 20 | 4 | 1 | 0 | ✗ |
| `abortStream` | L902-918 | 17 | 4 | 1 | 0 | ✗ |
| `playAudioBase64Wait` | L938-952 | 15 | 4 | 1 | 1 | ✗ |
| `showConfirm` | L1416-1441 | 26 | 4 | 1 | 0 | ✗ |
| `detectTheme` | L10-14 | 5 | 3 | 1 | 0 | ✓ |
| `apiCall` | L320-325 | 6 | 3 | 1 | 3 | ✗ |
| `apiGet` | L326-334 | 9 | 3 | 1 | 1 | ✗ |
| `apiPost` | L337-342 | 6 | 3 | 1 | 2 | ✓ |
| `apiPostJson` | L343-351 | 9 | 3 | 1 | 2 | ✗ |
| `renderChatList` | L413-427 | 15 | 3 | 1 | 0 | ✗ |
| `handleImageSelected` | L486-498 | 13 | 3 | 1 | 1 | ✗ |
| `switchInputMode` | L510-527 | 18 | 3 | 1 | 1 | ✓ |
| `stopWaveform` | L625-633 | 9 | 3 | 1 | 0 | ✗ |
| `playAudioBase64` | L926-936 | 11 | 3 | 1 | 1 | ✗ |
| `renderMaintTasks` | L1089-1097 | 9 | 3 | 0 | 0 | ✗ |
| `updateMaintProgress` | L1099-1111 | 13 | 3 | 1 | 0 | ✗ |
| `hideConfirm` | L1443-1458 | 16 | 3 | 1 | 0 | ✗ |
| `toggleTheme` | L19-21 | 3 | 2 | 0 | 0 | ✗ |
| `addLineStatic` | L238-253 | 16 | 2 | 1 | 3 | ✗ |
| `newChat` | L472-479 | 8 | 2 | 1 | 0 | ✗ |
| `removeImage` | L500-507 | 8 | 2 | 1 | 0 | ✗ |
| `cancelRecording` | L573-581 | 9 | 2 | 1 | 0 | ✗ |
| `uncancelRecording` | L583-591 | 9 | 2 | 1 | 0 | ✗ |
| `sendMessage` | L888-900 | 13 | 2 | 1 | 0 | ✗ |
| `toggleTTS` | L921-925 | 5 | 2 | 0 | 0 | ✓ |
| `checkMaintStatus` | L1113-1122 | 10 | 2 | 1 | 0 | ✗ |
| `hideKeyHints` | L1382-1390 | 9 | 2 | 1 | 0 | ✗ |
| `applyTheme` | L15-18 | 4 | 1 | 0 | 1 | ✗ |
| `archiveActiveLines` | L211-217 | 7 | 1 | 0 | 0 | ✓ |
| `addNarrationLine` | L219-226 | 8 | 1 | 0 | 1 | ✗ |
| `addNarratorLine` | L228-236 | 9 | 1 | 0 | 1 | ✗ |
| `addSystemLine` | L255-262 | 8 | 1 | 0 | 1 | ✗ |
| `addErrorLine` | L264-271 | 8 | 1 | 0 | 1 | ✗ |
| `logout` | L395-406 | 12 | 1 | 0 | 0 | ✗ |
| `loadChats` | L409-412 | 4 | 1 | 0 | 0 | ✓ |
| `selectImage` | L482-484 | 3 | 1 | 0 | 0 | ✓ |
| `blobToBase64` | L635-644 | 10 | 1 | 0 | 1 | ✗ |
| `updateStatusBar` | L1003-1006 | 4 | 1 | 0 | 0 | ✓ |
| `updateStatusBarText` | L1007-1009 | 3 | 1 | 0 | 1 | ✗ |
| `createKeyCapSVG` | L1310-1320 | 11 | 1 | 0 | 1 | ✓ |
| `doConfirm` | L1460-1464 | 5 | 1 | 0 | 0 | ✗ |

**全部问题 (52)**

- 🔄 `sendRecording()` L646: 复杂度: 36
- 🔄 `msgFlow()` L756: 复杂度: 38
- 🔄 `selectChat()` L428: 认知复杂度: 16
- 🔄 `sendRecording()` L646: 认知复杂度: 44
- 🔄 `msgFlow()` L756: 认知复杂度: 46
- 🔄 `parseControlTags()` L172: 嵌套深度: 4
- 🔄 `selectChat()` L428: 嵌套深度: 4
- 🔄 `sendRecording()` L646: 嵌套深度: 4
- 🔄 `msgFlow()` L756: 嵌套深度: 4
- 📏 `sendRecording()` L646: 105 代码量
- 📏 `msgFlow()` L756: 131 代码量
- 🏗️ `parseControlTags()` L172: 中等嵌套: 4
- 🏗️ `selectChat()` L428: 中等嵌套: 4
- 🏗️ `sendRecording()` L646: 中等嵌套: 4
- 🏗️ `msgFlow()` L756: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1506 行
- 🏗️ L1: 函数过多: 57
- ❌ L152: 未处理的易出错调用
- ❌ L214: 未处理的易出错调用
- ❌ L401: 未处理的易出错调用
- ❌ L404: 未处理的易出错调用
- ❌ L433: 未处理的易出错调用
- ❌ L457: 未处理的易出错调用
- ❌ L476: 未处理的易出错调用
- ❌ L493: 未处理的易出错调用
- ❌ L504: 未处理的易出错调用
- ❌ L515: 未处理的易出错调用
- ❌ L521: 未处理的易出错调用
- ❌ L522: 未处理的易出错调用
- ❌ L568: 未处理的易出错调用
- ❌ L569: 未处理的易出错调用
- ❌ L577: 未处理的易出错调用
- ❌ L579: 未处理的易出错调用
- ❌ L586: 未处理的易出错调用
- ❌ L588: 未处理的易出错调用
- ❌ L671: 未处理的易出错调用
- ❌ L745: 未处理的易出错调用
- ❌ L784: 未处理的易出错调用
- ❌ L882: 未处理的易出错调用
- ❌ L914: 未处理的易出错调用
- ❌ L1114: 未处理的易出错调用
- ❌ L1132: 未处理的易出错调用
- ❌ L1142: 未处理的易出错调用
- ❌ L1143: 未处理的易出错调用
- ❌ L1162: 未处理的易出错调用
- ❌ L1387: 未处理的易出错调用
- ❌ L1388: 未处理的易出错调用
- ❌ L1419: 未处理的易出错调用
- ❌ L1422: 未处理的易出错调用
- ❌ L1446: 未处理的易出错调用
- ❌ L1448: 未处理的易出错调用
- ❌ L1453: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 4.4, 最大: 38
- 认知复杂度: 平均: 6.5, 最大: 46
- 嵌套深度: 平均: 1.0, 最大: 4
- 函数长度: 平均: 18.4 行, 最大: 131 行
- 文件长度: 1371 代码量 (1506 总计)
- 参数数量: 平均: 0.6, 最大: 3
- 代码重复: 3.5% 重复 (2/57)
- 结构分析: 6 个结构问题
- 错误处理: 35/59 个错误被忽略 (59.3%)
- 注释比例: 3.3% (45/1371)
- 命名规范: 无命名违规

### 9. boot.py

**糟糕指数: 32.07**

> 行数: 702 总计, 582 代码, 38 注释 | 函数: 13 | 类: 0

**问题**: 🔄 复杂度问题: 7, ⚠️ 其他问题: 3, 📋 重复问题: 1, 🏗️ 结构问题: 3, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 9

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_application` | L346-701 | 356 | 38 | 4 | 0 | ✓ |
| `_preload_models` | L249-320 | 72 | 13 | 2 | 1 | ✓ |
| `_synthesize_tts_lines` | L128-150 | 23 | 10 | 2 | 1 | ✗ |
| `process_task_completion` | L177-195 | 19 | 8 | 3 | 0 | ✗ |
| `_handle_action_completion` | L219-244 | 26 | 8 | 2 | 3 | ✗ |
| `_convert_audio_to_wav` | L109-125 | 17 | 5 | 2 | 1 | ✗ |
| `_process_image_input` | L81-96 | 16 | 4 | 1 | 2 | ✗ |
| `create_chat_client` | L67-78 | 12 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L209-216 | 8 | 3 | 1 | 2 | ✗ |
| `_save_debug_audio` | L99-106 | 8 | 2 | 1 | 1 | ✗ |
| `setup_logging` | L153-174 | 22 | 2 | 1 | 1 | ✗ |
| `_handle_reminder_completion` | L198-206 | 9 | 2 | 1 | 2 | ✗ |
| `_t` | L330-341 | 12 | 2 | 1 | 1 | ✗ |

**全部问题 (29)**

- 🔄 `_preload_models()` L249: 复杂度: 13
- 🔄 `create_application()` L346: 复杂度: 38
- 🔄 `_synthesize_tts_lines()` L128: 认知复杂度: 14
- 🔄 `process_task_completion()` L177: 认知复杂度: 14
- 🔄 `_preload_models()` L249: 认知复杂度: 17
- 🔄 `create_application()` L346: 认知复杂度: 46
- 🔄 `create_application()` L346: 嵌套深度: 4
- 📏 `_preload_models()` L249: 72 代码量
- 📏 `create_application()` L346: 356 代码量
- 📋 `_save_debug_audio()` L99: 重复模式: _save_debug_audio, _handle_reminder_completion
- 🏗️ `process_task_completion()` L177: 中等嵌套: 3
- 🏗️ `create_application()` L346: 中等嵌套: 4
- 🏗️ L1: 导入过多: 55
- ❌ L104: 未处理的易出错调用
- ❌ L105: 未处理的易出错调用
- ❌ L146: 未处理的易出错调用
- ❌ L392: 未处理的易出错调用
- ❌ L408: 未处理的易出错调用
- ❌ L439: 未处理的易出错调用
- ❌ L679: 未处理的易出错调用
- 🏷️ `_process_image_input()` L81: "_process_image_input" - snake_case
- 🏷️ `_save_debug_audio()` L99: "_save_debug_audio" - snake_case
- 🏷️ `_convert_audio_to_wav()` L109: "_convert_audio_to_wav" - snake_case
- 🏷️ `_synthesize_tts_lines()` L128: "_synthesize_tts_lines" - snake_case
- 🏷️ `_handle_reminder_completion()` L198: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L209: "_handle_reasoner_completion" - snake_case
- 🏷️ `_handle_action_completion()` L219: "_handle_action_completion" - snake_case
- 🏷️ `_preload_models()` L249: "_preload_models" - snake_case
- 🏷️ `_t()` L330: "_t" - snake_case

**详情**:
- 循环复杂度: 平均: 7.7, 最大: 38
- 认知复杂度: 平均: 11.1, 最大: 46
- 嵌套深度: 平均: 1.7, 最大: 4
- 函数长度: 平均: 46.2 行, 最大: 356 行
- 文件长度: 582 代码量 (702 总计)
- 参数数量: 平均: 1.2, 最大: 3
- 代码重复: 7.7% 重复 (1/13)
- 结构分析: 3 个结构问题
- 错误处理: 7/33 个错误被忽略 (21.2%)
- 注释比例: 6.5% (38/582)
- 命名规范: 发现 9 个违规

### 10. tests/test_ncm_music.py

**糟糕指数: 31.96**

> 行数: 113 总计, 87 代码, 7 注释 | 函数: 1 | 类: 0

**问题**: 🔄 复杂度问题: 2, ⚠️ 其他问题: 1, 🏗️ 结构问题: 1, ❌ 错误处理问题: 11, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L12-108 | 97 | 18 | 3 | 0 | ✗ |

**全部问题 (15)**

- 🔄 `main()` L12: 复杂度: 18
- 🔄 `main()` L12: 认知复杂度: 24
- 📏 `main()` L12: 97 代码量
- 🏗️ `main()` L12: 中等嵌套: 3
- ❌ L29: 未处理的易出错调用
- ❌ L70: 未处理的易出错调用
- ❌ L73: 未处理的易出错调用
- ❌ L74: 未处理的易出错调用
- ❌ L80: 未处理的易出错调用
- ❌ L85: 未处理的易出错调用
- ❌ L86: 未处理的易出错调用
- ❌ L87: 未处理的易出错调用
- ❌ L89: 未处理的易出错调用
- ❌ L96: 未处理的易出错调用
- ❌ L101: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 18.0, 最大: 18
- 认知复杂度: 平均: 24.0, 最大: 24
- 嵌套深度: 平均: 3.0, 最大: 3
- 函数长度: 平均: 97.0 行, 最大: 97 行
- 文件长度: 87 代码量 (113 总计)
- 参数数量: 平均: 0.0, 最大: 0
- 代码重复: 未发现函数
- 结构分析: 1 个结构问题
- 错误处理: 11/18 个错误被忽略 (61.1%)
- 注释比例: 8.0% (7/87)
- 命名规范: 无命名违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `process_stream` | plugins/pipeline.py | 57 | 7 | 273 |
| `main` | psychoscope/minimal.py | 47 | 6 | 203 |
| `create_engine_with_defaults` | engine.py | 44 | 2 | 239 |
| `create_application` | boot.py | 38 | 4 | 356 |
| `_poll_pending_tasks` | plugins/pipeline.py | 38 | 6 | 123 |
| `search` | memory/core.py | 38 | 7 | 129 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `_cmd_reminder` | main.py | 31 | 4 | 129 |
| `_cmd_memory_query` | main.py | 31 | 3 | 141 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*