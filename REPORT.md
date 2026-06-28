# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-80%25-green)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **79.53/100** |
| 屎山等级 | 😐 微臭青年 |

> 略带清香，偶尔飘过一丝酸爽

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 189 |
| 已跳过 | 471 |
| 耗时 | 996ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 31518 |
| 总注释行数 | 1404 |
| 整体注释比例 | 4.5% |
| 平均文件大小 | 207 行 |
| 最大文件 | `main.py` (2165) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 186 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 9.85% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 13.72% | 0.0% | 70.0% | 10.0% | ✓✓ |
| 嵌套深度 | 3.90% | 0.0% | 55.0% | 0.0% | ✓✓ |
| 函数长度 | 6.20% | 0.0% | 55.8% | 0.0% | ✓✓ |
| 文件长度 | 2.77% | 0.0% | 91.7% | 0.0% | ✓✓ |
| 参数数量 | 13.74% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.75% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.88% | 0.0% | 82.5% | 0.0% | ✓✓ |
| 错误处理 | 32.28% | 0.0% | 98.8% | 5.4% | ✓ |
| 注释比例 | 41.73% | 0.0% | 100.0% | 39.8% | ○ |
| 命名规范 | 26.72% | 0.0% | 95.7% | 20.7% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. main.py

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

### 2. plugins/pipeline.py

**糟糕指数: 45.41**

> 行数: 923 总计, 743 代码, 47 注释 | 函数: 25 | 类: 1

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 7, 🏗️ 结构问题: 9, ❌ 错误处理问题: 19, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L666-922 | 257 | 54 | 7 | 3 | ✓ |
| `_poll_pending_tasks` | L532-654 | 123 | 38 | 6 | 4 | ✓ |
| `_synthesize_lines_sync` | L413-494 | 82 | 23 | 4 | 4 | ✓ |
| `process` | L137-210 | 74 | 13 | 3 | 2 | ✗ |
| `_run_agent_loop` | L215-275 | 61 | 9 | 3 | 2 | ✗ |
| `_print_timing` | L277-302 | 26 | 9 | 4 | 3 | ✗ |
| `_format_tag_results` | L313-330 | 18 | 8 | 3 | 1 | ✗ |
| `_run_all_plugins` | L505-530 | 26 | 8 | 2 | 5 | ✗ |
| `_dispatch_pre_process` | L354-391 | 38 | 7 | 1 | 2 | ✓ |
| `_call_llm_with_msgs` | L45-68 | 18 | 5 | 2 | 2 | ✓ |
| `_extract_narrations` | L71-86 | 16 | 4 | 3 | 1 | ✓ |
| `_print_plugin_timing` | L304-310 | 7 | 4 | 2 | 2 | ✗ |
| `_assemble_prompt` | L332-350 | 19 | 4 | 1 | 2 | ✓ |
| `_bridge_progress` | L497-503 | 7 | 3 | 2 | 2 | ✗ |
| `_invoke` | L61-66 | 6 | 2 | 1 | 0 | ✗ |
| `_desc_tool` | L89-94 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L97-104 | 8 | 2 | 1 | 1 | ✗ |
| `timer_enabled` | L25-26 | 2 | 1 | 0 | 0 | ✗ |
| `enable_timer` | L29-31 | 3 | 1 | 0 | 0 | ✗ |
| `disable_timer` | L34-36 | 3 | 1 | 0 | 0 | ✗ |
| `toggle_timer` | L39-42 | 4 | 1 | 0 | 0 | ✗ |
| `__init__` | L121-133 | 13 | 1 | 0 | 6 | ✗ |
| `_dispatch_post_process` | L212-213 | 2 | 1 | 0 | 2 | ✗ |
| `_synthesize_lines` | L395-401 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L403-411 | 9 | 1 | 0 | 3 | ✓ |

**全部问题 (59)**

- 🔄 `process()` L137: 复杂度: 13
- 🔄 `_synthesize_lines_sync()` L413: 复杂度: 23
- 🔄 `_poll_pending_tasks()` L532: 复杂度: 38
- 🔄 `process_stream()` L666: 复杂度: 54
- 🔄 `process()` L137: 认知复杂度: 19
- 🔄 `_run_agent_loop()` L215: 认知复杂度: 15
- 🔄 `_print_timing()` L277: 认知复杂度: 17
- 🔄 `_format_tag_results()` L313: 认知复杂度: 14
- 🔄 `_synthesize_lines_sync()` L413: 认知复杂度: 31
- 🔄 `_poll_pending_tasks()` L532: 认知复杂度: 50
- 🔄 `process_stream()` L666: 认知复杂度: 68
- 🔄 `_print_timing()` L277: 嵌套深度: 4
- 🔄 `_synthesize_lines_sync()` L413: 嵌套深度: 4
- 🔄 `_poll_pending_tasks()` L532: 嵌套深度: 6
- 🔄 `process_stream()` L666: 嵌套深度: 7
- 📏 `process()` L137: 74 代码量
- 📏 `_run_agent_loop()` L215: 61 代码量
- 📏 `_synthesize_lines_sync()` L413: 82 代码量
- 📏 `_poll_pending_tasks()` L532: 123 代码量
- 📏 `process_stream()` L666: 257 代码量
- 📏 `__init__()` L121: 6 参数数量
- 🏗️ `_extract_narrations()` L71: 中等嵌套: 3
- 🏗️ `process()` L137: 中等嵌套: 3
- 🏗️ `_run_agent_loop()` L215: 中等嵌套: 3
- 🏗️ `_print_timing()` L277: 中等嵌套: 4
- 🏗️ `_format_tag_results()` L313: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L413: 中等嵌套: 4
- 🏗️ `_poll_pending_tasks()` L532: 嵌套过深: 6
- 🏗️ `process_stream()` L666: 嵌套过深: 7
- 🏗️ L1: 导入过多: 25
- ❌ L180: 未处理的易出错调用
- ❌ L196: 未处理的易出错调用
- ❌ L328: 未处理的易出错调用
- ❌ L439: 未处理的易出错调用
- ❌ L487: 未处理的易出错调用
- ❌ L490: 未处理的易出错调用
- ❌ L493: 未处理的易出错调用
- ❌ L503: 未处理的易出错调用
- ❌ L509: 未处理的易出错调用
- ❌ L529: 未处理的易出错调用
- ❌ L530: 未处理的易出错调用
- ❌ L564: 未处理的易出错调用
- ❌ L589: 未处理的易出错调用
- ❌ L626: 未处理的易出错调用
- ❌ L832: 未处理的易出错调用
- ❌ L846: 未处理的易出错调用
- ❌ L859: 未处理的易出错调用
- ❌ L879: 未处理的易出错调用
- ❌ L917: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L45: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L61: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L71: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L89: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L97: "_desc_task" - snake_case
- 🏷️ `__init__()` L121: "__init__" - snake_case
- 🏷️ `_dispatch_post_process()` L212: "_dispatch_post_process" - snake_case
- 🏷️ `_run_agent_loop()` L215: "_run_agent_loop" - snake_case
- 🏷️ `_print_timing()` L277: "_print_timing" - snake_case
- 🏷️ `_print_plugin_timing()` L304: "_print_plugin_timing" - snake_case

**详情**:
- 循环复杂度: 平均: 8.1, 最大: 54
- 认知复杂度: 平均: 11.8, 最大: 68
- 嵌套深度: 平均: 1.8, 最大: 7
- 函数长度: 平均: 33.4 行, 最大: 257 行
- 文件长度: 743 代码量 (923 总计)
- 参数数量: 平均: 2.0, 最大: 6
- 代码重复: 0.0% 重复 (0/25)
- 结构分析: 9 个结构问题
- 错误处理: 19/53 个错误被忽略 (35.8%)
- 注释比例: 6.3% (47/743)
- 命名规范: 发现 19 个违规

### 3. engine.py

**糟糕指数: 45.32**

> 行数: 1084 总计, 934 代码, 20 注释 | 函数: 40 | 类: 2

**问题**: 🔄 复杂度问题: 12, ⚠️ 其他问题: 6, 📋 重复问题: 4, 🏗️ 结构问题: 7, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L850-1083 | 234 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L441-488 | 48 | 17 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L578-614 | 37 | 15 | 2 | 1 | ✗ |
| `build_context` | L652-685 | 34 | 11 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L556-576 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L616-639 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L687-723 | 37 | 9 | 2 | 8 | ✓ |
| `_generate_result_message` | L262-309 | 48 | 8 | 2 | 3 | ✗ |
| `_register_context_plugins` | L535-554 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L725-744 | 20 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L217-235 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L311-332 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L334-362 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L364-389 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L409-425 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L427-439 | 13 | 6 | 3 | 1 | ✓ |
| `index_prompts_for_chat` | L752-772 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L776-824 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L828-836 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L189-203 | 15 | 5 | 3 | 1 | ✗ |
| `_dispatch_task_completion` | L205-215 | 11 | 5 | 2 | 3 | ✗ |
| `from_subapp` | L75-92 | 18 | 3 | 0 | 1 | ✗ |
| `__init__` | L106-138 | 33 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L166-185 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L248-260 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L391-407 | 17 | 3 | 2 | 1 | ✗ |
| `_init_plugins` | L490-500 | 11 | 3 | 0 | 1 | ✗ |
| `_plugin_enabled` | L502-507 | 6 | 3 | 1 | 2 | ✗ |
| `_init_database` | L159-164 | 6 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L237-246 | 10 | 2 | 1 | 3 | ✗ |
| `_register_filter_plugins` | L509-516 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L518-533 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L746-747 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L749-750 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L788-794 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L798-807 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L142-157 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L641-648 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L841-847 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (42)**

- 🔄 `_init_prompt()` L441: 复杂度: 17
- 🔄 `_register_execution_plugins()` L578: 复杂度: 15
- 🔄 `build_context()` L652: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L850: 复杂度: 43
- 🔄 `_init_prompt()` L441: 认知复杂度: 25
- 🔄 `_register_personality_plugins()` L556: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L578: 认知复杂度: 19
- 🔄 `_register_output_plugins()` L616: 认知复杂度: 13
- 🔄 `build_context()` L652: 认知复杂度: 13
- 🔄 `chat()` L687: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L850: 认知复杂度: 47
- 🔄 `_init_prompt()` L441: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L850: 234 代码量
- 📏 `build_context()` L652: 8 参数数量
- 📏 `chat()` L687: 8 参数数量
- 📏 `chat_stream()` L725: 8 参数数量
- 📏 `create_engine_with_defaults()` L850: 12 参数数量
- 📋 `from_subapp()` L75: 重复模式: from_subapp, _init_memory
- 📋 `_init_database()` L159: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L248: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 📋 `_register_execution_plugins()` L578: 重复模式: _register_execution_plugins, chat_stream
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L189: 中等嵌套: 3
- 🏗️ `_init_memory()` L334: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L427: 中等嵌套: 3
- 🏗️ `_init_prompt()` L441: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1084 行
- 🏗️ L1: 导入过多: 85
- ❌ L218: 未处理的易出错调用
- ❌ L232: 未处理的易出错调用
- ❌ L278: 未处理的易出错调用
- ❌ L792: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L42: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L106: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L142: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L159: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L166: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L189: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L205: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L217: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L237: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L248: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 43
- 认知复杂度: 平均: 9.0, 最大: 47
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 23.9 行, 最大: 234 行
- 文件长度: 934 代码量 (1084 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 15.0% 重复 (6/40)
- 结构分析: 7 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.1% (20/934)
- 命名规范: 发现 27 个违规

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

**糟糕指数: 41.71**

> 行数: 1010 总计, 871 代码, 9 注释 | 函数: 44 | 类: 4

**问题**: 🔄 复杂度问题: 22, ⚠️ 其他问题: 4, 📋 重复问题: 2, 🏗️ 结构问题: 14, ❌ 错误处理问题: 15, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L808-1007 | 192 | 44 | 6 | 0 | ✗ |
| `authenticate` | L193-274 | 82 | 14 | 2 | 3 | ✗ |
| `_handle_sse_stream` | L352-390 | 39 | 14 | 4 | 4 | ✗ |
| `_loop` | L483-512 | 30 | 10 | 5 | 1 | ✗ |
| `stop_and_send` | L587-619 | 33 | 10 | 2 | 1 | ✗ |
| `print_system_info` | L770-806 | 37 | 10 | 4 | 1 | ✓ |
| `_capture_loop` | L621-651 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L677-703 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L125-142 | 18 | 8 | 3 | 1 | ✗ |
| `_tts_worker` | L171-191 | 21 | 8 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L71-84 | 14 | 6 | 5 | 0 | ✓ |
| `send_audio` | L312-350 | 39 | 6 | 2 | 2 | ✗ |
| `_trigger` | L514-538 | 25 | 6 | 4 | 2 | ✓ |
| `_verify_api_key` | L276-293 | 18 | 5 | 3 | 1 | ✗ |
| `skip_latest` | L417-435 | 19 | 5 | 2 | 1 | ✓ |
| `_sync` | L437-463 | 27 | 5 | 3 | 1 | ✓ |
| `_play_beep` | L98-112 | 15 | 4 | 1 | 2 | ✓ |
| `__init__` | L156-169 | 14 | 4 | 1 | 3 | ✗ |
| `start` | L565-585 | 21 | 4 | 1 | 1 | ✗ |
| `print_header` | L705-732 | 28 | 4 | 1 | 3 | ✗ |
| `load_config` | L144-150 | 7 | 3 | 2 | 0 | ✗ |
| `_load_local` | L465-471 | 7 | 3 | 2 | 1 | ✗ |
| `print_personality` | L734-759 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L46-66 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L115-123 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L295-298 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L402-408 | 7 | 2 | 1 | 1 | ✗ |
| `_save_local` | L473-481 | 9 | 2 | 1 | 2 | ✗ |
| `start` | L659-664 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L666-669 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L671-675 | 5 | 2 | 1 | 2 | ✗ |
| `toggle_standby` | L761-767 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L866-873 | 8 | 2 | 1 | 2 | ✗ |
| `save_config` | L152-153 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L300-302 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L304-306 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L308-310 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L396-400 | 5 | 1 | 0 | 2 | ✗ |
| `stop` | L410-411 | 2 | 1 | 0 | 1 | ✗ |
| `sync_now` | L413-415 | 3 | 1 | 0 | 1 | ✓ |
| `_type_label` | L541-546 | 6 | 1 | 0 | 1 | ✗ |
| `__init__` | L550-559 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L562-563 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L654-657 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (65)**

- 🔄 `authenticate()` L193: 复杂度: 14
- 🔄 `_handle_sse_stream()` L352: 复杂度: 14
- 🔄 `main()` L808: 复杂度: 44
- 🔄 `_detect_tts_sample_rate()` L71: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L125: 认知复杂度: 14
- 🔄 `_tts_worker()` L171: 认知复杂度: 14
- 🔄 `authenticate()` L193: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L352: 认知复杂度: 22
- 🔄 `_loop()` L483: 认知复杂度: 20
- 🔄 `_trigger()` L514: 认知复杂度: 14
- 🔄 `stop_and_send()` L587: 认知复杂度: 14
- 🔄 `_capture_loop()` L621: 认知复杂度: 15
- 🔄 `_loop()` L677: 认知复杂度: 19
- 🔄 `print_system_info()` L770: 认知复杂度: 18
- 🔄 `main()` L808: 认知复杂度: 56
- 🔄 `_detect_tts_sample_rate()` L71: 嵌套深度: 5
- 🔄 `_handle_sse_stream()` L352: 嵌套深度: 4
- 🔄 `_loop()` L483: 嵌套深度: 5
- 🔄 `_trigger()` L514: 嵌套深度: 4
- 🔄 `_loop()` L677: 嵌套深度: 5
- 🔄 `print_system_info()` L770: 嵌套深度: 4
- 🔄 `main()` L808: 嵌套深度: 6
- 📏 `authenticate()` L193: 82 代码量
- 📏 `main()` L808: 192 代码量
- 📋 `__init__()` L156: 重复模式: __init__, _trigger, __init__
- 📋 `_tts_worker()` L171: 重复模式: _tts_worker, __init__, _loop
- 🏗️ `_detect_tts_sample_rate()` L71: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L125: 中等嵌套: 3
- 🏗️ `_tts_worker()` L171: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L276: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L352: 中等嵌套: 4
- 🏗️ `_sync()` L437: 中等嵌套: 3
- 🏗️ `_loop()` L483: 嵌套过深: 5
- 🏗️ `_trigger()` L514: 中等嵌套: 4
- 🏗️ `_capture_loop()` L621: 中等嵌套: 3
- 🏗️ `_loop()` L677: 嵌套过深: 5
- 🏗️ `print_system_info()` L770: 中等嵌套: 4
- 🏗️ `main()` L808: 嵌套过深: 6
- 🏗️ L1: 文件过大: 1010 行
- 🏗️ L1: 导入过多: 25
- ❌ L76: 未处理的易出错调用
- ❌ L118: 未处理的易出错调用
- ❌ L385: 未处理的易出错调用
- ❌ L431: 未处理的易出错调用
- ❌ L459: 未处理的易出错调用
- ❌ L528: 未处理的易出错调用
- ❌ L533: 未处理的易出错调用
- ❌ L536: 未处理的易出错调用
- ❌ L605: 未处理的易出错调用
- ❌ L690: 未处理的易出错调用
- ❌ L699: 未处理的易出错调用
- ❌ L755: 未处理的易出错调用
- ❌ L777: 未处理的易出错调用
- ❌ L802: 未处理的易出错调用
- ❌ L957: 未处理的易出错调用
- 🏷️ `_detect_tts_sample_rate()` L71: "_detect_tts_sample_rate" - snake_case
- 🏷️ `_play_beep()` L98: "_play_beep" - snake_case
- 🏷️ `__init__()` L156: "__init__" - snake_case
- 🏷️ `_tts_worker()` L171: "_tts_worker" - snake_case
- 🏷️ `_verify_api_key()` L276: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L295: "_headers" - snake_case
- 🏷️ `_http_get()` L300: "_http_get" - snake_case
- 🏷️ `_http_post()` L304: "_http_post" - snake_case
- 🏷️ `_http_post_stream()` L308: "_http_post_stream" - snake_case
- 🏷️ `_handle_sse_stream()` L352: "_handle_sse_stream" - snake_case

**详情**:
- 循环复杂度: 平均: 5.1, 最大: 44
- 认知复杂度: 平均: 8.6, 最大: 56
- 嵌套深度: 平均: 1.7, 最大: 6
- 函数长度: 平均: 20.3 行, 最大: 192 行
- 文件长度: 871 代码量 (1010 总计)
- 参数数量: 平均: 1.4, 最大: 4
- 代码重复: 9.1% 重复 (4/44)
- 结构分析: 14 个结构问题
- 错误处理: 15/88 个错误被忽略 (17.0%)
- 注释比例: 1.0% (9/871)
- 命名规范: 发现 21 个违规

### 6. psychoscope/static/js/app.js

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

### 7. boot.py

**糟糕指数: 32.04**

> 行数: 699 总计, 579 代码, 38 注释 | 函数: 13 | 类: 0

**问题**: 🔄 复杂度问题: 7, ⚠️ 其他问题: 3, 📋 重复问题: 1, 🏗️ 结构问题: 3, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 9

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_application` | L346-698 | 353 | 38 | 4 | 0 | ✓ |
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
- 📏 `create_application()` L346: 353 代码量
- 📋 `_save_debug_audio()` L99: 重复模式: _save_debug_audio, _handle_reminder_completion
- 🏗️ `process_task_completion()` L177: 中等嵌套: 3
- 🏗️ `create_application()` L346: 中等嵌套: 4
- 🏗️ L1: 导入过多: 54
- ❌ L104: 未处理的易出错调用
- ❌ L105: 未处理的易出错调用
- ❌ L146: 未处理的易出错调用
- ❌ L390: 未处理的易出错调用
- ❌ L406: 未处理的易出错调用
- ❌ L437: 未处理的易出错调用
- ❌ L676: 未处理的易出错调用
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
- 函数长度: 平均: 45.9 行, 最大: 353 行
- 文件长度: 579 代码量 (699 总计)
- 参数数量: 平均: 1.2, 最大: 3
- 代码重复: 7.7% 重复 (1/13)
- 结构分析: 3 个结构问题
- 错误处理: 7/33 个错误被忽略 (21.2%)
- 注释比例: 6.6% (38/579)
- 命名规范: 发现 9 个违规

### 8. tests/test_ncm_music.py

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

### 9. onboarding.py

**糟糕指数: 31.96**

> 行数: 628 总计, 489 代码, 16 注释 | 函数: 23 | 类: 0

**问题**: 🔄 复杂度问题: 14, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 5, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_ai_guided_configure` | L415-575 | 161 | 25 | 4 | 2 | ✓ |
| `_get_api_key` | L358-409 | 52 | 13 | 4 | 0 | ✓ |
| `_check_pip_packages` | L173-200 | 28 | 11 | 3 | 0 | ✗ |
| `_env_write` | L33-55 | 23 | 10 | 5 | 2 | ✗ |
| `_load_existing_env` | L19-30 | 12 | 7 | 4 | 0 | ✗ |
| `_chat_send_with_retry` | L109-132 | 24 | 6 | 4 | 3 | ✓ |
| `_install_missing_packages` | L255-278 | 24 | 6 | 2 | 1 | ✓ |
| `_get_current_config` | L291-301 | 11 | 6 | 2 | 0 | ✓ |
| `_get_character_cards_info` | L304-315 | 12 | 5 | 1 | 0 | ✓ |
| `run` | L581-622 | 42 | 4 | 2 | 0 | ✓ |
| `_is_configured` | L63-68 | 6 | 3 | 1 | 0 | ✗ |
| `_run_shell` | L71-86 | 16 | 3 | 1 | 2 | ✗ |
| `_safe_input` | L145-151 | 7 | 3 | 1 | 1 | ✗ |
| `_run_python` | L89-101 | 13 | 2 | 2 | 2 | ✗ |
| `_render_markdown` | L135-142 | 8 | 2 | 1 | 1 | ✗ |
| `_check_conda` | L166-170 | 5 | 2 | 1 | 0 | ✗ |
| `_get_env_config_info` | L284-288 | 5 | 2 | 1 | 0 | ✓ |
| `_env_read` | L58-60 | 3 | 1 | 0 | 1 | ✗ |
| `_create_chat` | L104-106 | 3 | 1 | 0 | 1 | ✗ |
| `_check_python` | L157-163 | 7 | 1 | 0 | 0 | ✗ |
| `_check_third_party` | L203-233 | 31 | 1 | 0 | 0 | ✗ |
| `_collect_environment_info` | L236-252 | 17 | 1 | 0 | 0 | ✓ |
| `_create_character_card` | L321-352 | 32 | 1 | 0 | 3 | ✓ |

**全部问题 (37)**

- 🔄 `_check_pip_packages()` L173: 复杂度: 11
- 🔄 `_get_api_key()` L358: 复杂度: 13
- 🔄 `_ai_guided_configure()` L415: 复杂度: 25
- 🔄 `_load_existing_env()` L19: 认知复杂度: 15
- 🔄 `_env_write()` L33: 认知复杂度: 20
- 🔄 `_chat_send_with_retry()` L109: 认知复杂度: 14
- 🔄 `_check_pip_packages()` L173: 认知复杂度: 17
- 🔄 `_get_api_key()` L358: 认知复杂度: 21
- 🔄 `_ai_guided_configure()` L415: 认知复杂度: 33
- 🔄 `_load_existing_env()` L19: 嵌套深度: 4
- 🔄 `_env_write()` L33: 嵌套深度: 5
- 🔄 `_chat_send_with_retry()` L109: 嵌套深度: 4
- 🔄 `_get_api_key()` L358: 嵌套深度: 4
- 🔄 `_ai_guided_configure()` L415: 嵌套深度: 4
- 📏 `_get_api_key()` L358: 52 代码量
- 📏 `_ai_guided_configure()` L415: 161 代码量
- 🏗️ `_load_existing_env()` L19: 中等嵌套: 4
- 🏗️ `_env_write()` L33: 嵌套过深: 5
- 🏗️ `_chat_send_with_retry()` L109: 中等嵌套: 4
- 🏗️ `_check_pip_packages()` L173: 中等嵌套: 3
- 🏗️ `_get_api_key()` L358: 中等嵌套: 4
- 🏗️ `_ai_guided_configure()` L415: 中等嵌套: 4
- ❌ L93: 未处理的易出错调用
- ❌ L94: 未处理的易出错调用
- ❌ L258: 未处理的易出错调用
- ❌ L540: 未处理的易出错调用
- ❌ L541: 未处理的易出错调用
- 🏷️ `_load_existing_env()` L19: "_load_existing_env" - snake_case
- 🏷️ `_env_write()` L33: "_env_write" - snake_case
- 🏷️ `_env_read()` L58: "_env_read" - snake_case
- 🏷️ `_is_configured()` L63: "_is_configured" - snake_case
- 🏷️ `_run_shell()` L71: "_run_shell" - snake_case
- 🏷️ `_run_python()` L89: "_run_python" - snake_case
- 🏷️ `_create_chat()` L104: "_create_chat" - snake_case
- 🏷️ `_chat_send_with_retry()` L109: "_chat_send_with_retry" - snake_case
- 🏷️ `_render_markdown()` L135: "_render_markdown" - snake_case
- 🏷️ `_safe_input()` L145: "_safe_input" - snake_case

**详情**:
- 循环复杂度: 平均: 5.0, 最大: 25
- 认知复杂度: 平均: 8.4, 最大: 33
- 嵌套深度: 平均: 1.7, 最大: 5
- 函数长度: 平均: 23.6 行, 最大: 161 行
- 文件长度: 489 代码量 (628 总计)
- 参数数量: 平均: 0.8, 最大: 3
- 代码重复: 0.0% 重复 (0/23)
- 结构分析: 6 个结构问题
- 错误处理: 5/14 个错误被忽略 (35.7%)
- 注释比例: 3.3% (16/489)
- 命名规范: 发现 22 个违规

### 10. models/clients.py

**糟糕指数: 30.55**

> 行数: 1018 总计, 831 代码, 29 注释 | 函数: 50 | 类: 5

**问题**: 🔄 复杂度问题: 14, ⚠️ 其他问题: 10, 🏗️ 结构问题: 5, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_llm` | L737-809 | 60 | 17 | 5 | 7 | ✓ |
| `_ocr_single` | L944-1007 | 57 | 13 | 5 | 3 | ✗ |
| `_call_and_append` | L168-244 | 77 | 12 | 2 | 1 | ✓ |
| `_call_embed_api` | L625-678 | 41 | 11 | 5 | 2 | ✓ |
| `describe_images` | L479-524 | 46 | 9 | 2 | 5 | ✓ |
| `classify_image` | L526-573 | 48 | 8 | 2 | 4 | ✓ |
| `__init__` | L889-915 | 27 | 8 | 1 | 5 | ✗ |
| `__init__` | L703-735 | 33 | 7 | 1 | 8 | ✗ |
| `summarize_dialog` | L837-870 | 34 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L33-41 | 9 | 6 | 1 | 1 | ✓ |
| `__init__` | L283-332 | 50 | 6 | 1 | 8 | ✓ |
| `_do_call_chat_api` | L346-364 | 19 | 6 | 4 | 2 | ✓ |
| `_call_and_append` | L379-416 | 38 | 6 | 2 | 1 | ✗ |
| `describe_image` | L445-477 | 33 | 6 | 1 | 5 | ✓ |
| `_unload_lmstudio_model` | L66-87 | 22 | 5 | 2 | 2 | ✓ |
| `__init__` | L104-154 | 51 | 5 | 1 | 8 | ✓ |
| `_do_request` | L759-771 | 13 | 5 | 2 | 0 | ✗ |
| `summarize_text` | L811-832 | 22 | 5 | 1 | 3 | ✓ |
| `send_message` | L366-373 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L588-608 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L610-617 | 8 | 4 | 1 | 2 | ✓ |
| `ocr_batch` | L922-942 | 21 | 4 | 1 | 3 | ✓ |
| `_load_lmstudio_model` | L44-63 | 20 | 3 | 1 | 4 | ✓ |
| `send_message` | L156-162 | 7 | 3 | 1 | 2 | ✓ |
| `_call_chat_api` | L339-344 | 6 | 3 | 2 | 2 | ✓ |
| `_do_request` | L630-642 | 13 | 3 | 1 | 0 | ✗ |
| `_do_request` | L964-970 | 7 | 3 | 1 | 0 | ✗ |
| `embed_batch` | L619-623 | 5 | 2 | 1 | 2 | ✓ |
| `ocr` | L917-920 | 4 | 2 | 0 | 3 | ✓ |
| `toggle_detail_chats` | L19-23 | 5 | 1 | 0 | 0 | ✓ |
| `toggle_detail_actions` | L26-30 | 5 | 1 | 0 | 0 | ✓ |
| `continue_conversation` | L164-166 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L246-249 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L251-257 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L259-266 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L268-271 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L273-274 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L334-335 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L375-377 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L418-421 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L423-429 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L431-438 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L440-443 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L575-576 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L680-681 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L683-684 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L834-835 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_loaded` | L1009-1010 | 2 | 1 | 0 | 1 | ✗ |
| `unload` | L1012-1014 | 3 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1016-1017 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (38)**

- 🔄 `_call_and_append()` L168: 复杂度: 12
- 🔄 `_call_embed_api()` L625: 复杂度: 11
- 🔄 `_call_llm()` L737: 复杂度: 17
- 🔄 `_ocr_single()` L944: 复杂度: 13
- 🔄 `_call_and_append()` L168: 认知复杂度: 16
- 🔄 `_do_call_chat_api()` L346: 认知复杂度: 14
- 🔄 `describe_images()` L479: 认知复杂度: 13
- 🔄 `_call_embed_api()` L625: 认知复杂度: 21
- 🔄 `_call_llm()` L737: 认知复杂度: 27
- 🔄 `_ocr_single()` L944: 认知复杂度: 23
- 🔄 `_do_call_chat_api()` L346: 嵌套深度: 4
- 🔄 `_call_embed_api()` L625: 嵌套深度: 5
- 🔄 `_call_llm()` L737: 嵌套深度: 5
- 🔄 `_ocr_single()` L944: 嵌套深度: 5
- 📏 `__init__()` L104: 51 代码量
- 📏 `_call_and_append()` L168: 77 代码量
- 📏 `_call_llm()` L737: 60 代码量
- 📏 `_ocr_single()` L944: 57 代码量
- 📏 `__init__()` L104: 8 参数数量
- 📏 `__init__()` L283: 8 参数数量
- 📏 `__init__()` L588: 6 参数数量
- 📏 `__init__()` L703: 8 参数数量
- 📏 `_call_llm()` L737: 7 参数数量
- 🏗️ `_do_call_chat_api()` L346: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L625: 嵌套过深: 5
- 🏗️ `_call_llm()` L737: 嵌套过深: 5
- 🏗️ `_ocr_single()` L944: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1018 行
- 🏷️ `_is_no_model_error()` L33: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L44: "_load_lmstudio_model" - snake_case
- 🏷️ `_unload_lmstudio_model()` L66: "_unload_lmstudio_model" - snake_case
- 🏷️ `__init__()` L104: "__init__" - snake_case
- 🏷️ `_call_and_append()` L168: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L273: "__repr__" - snake_case
- 🏷️ `__init__()` L283: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L334: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L339: "_call_chat_api" - snake_case
- 🏷️ `_do_call_chat_api()` L346: "_do_call_chat_api" - snake_case

**详情**:
- 循环复杂度: 平均: 4.0, 最大: 17
- 认知复杂度: 平均: 6.0, 最大: 27
- 嵌套深度: 平均: 1.0, 最大: 5
- 函数长度: 平均: 17.6 行, 最大: 77 行
- 文件长度: 831 代码量 (1018 总计)
- 参数数量: 平均: 2.3, 最大: 8
- 代码重复: 2.0% 重复 (1/50)
- 结构分析: 5 个结构问题
- 错误处理: 1/26 个错误被忽略 (3.8%)
- 注释比例: 3.5% (29/831)
- 命名规范: 发现 26 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `process_stream` | plugins/pipeline.py | 54 | 7 | 257 |
| `main` | psychoscope/minimal.py | 44 | 6 | 192 |
| `create_engine_with_defaults` | engine.py | 43 | 2 | 234 |
| `create_application` | boot.py | 38 | 4 | 353 |
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