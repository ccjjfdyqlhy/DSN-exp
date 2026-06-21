# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-80%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **80.31/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 165 |
| 已跳过 | 505 |
| 耗时 | 954ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 28067 |
| 总注释行数 | 1432 |
| 整体注释比例 | 5.1% |
| 平均文件大小 | 213 行 |
| 最大文件 | `main.py` (2056) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 162 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 9.25% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 12.85% | 0.0% | 67.0% | 8.0% | ✓✓ |
| 嵌套深度 | 3.41% | 0.0% | 55.0% | 0.0% | ✓✓ |
| 函数长度 | 6.12% | 0.0% | 53.6% | 0.0% | ✓✓ |
| 文件长度 | 2.83% | 0.0% | 90.0% | 0.0% | ✓✓ |
| 参数数量 | 13.32% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.45% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.70% | 0.0% | 82.5% | 0.0% | ✓✓ |
| 错误处理 | 34.19% | 0.0% | 98.8% | 6.7% | ✓ |
| 注释比例 | 36.01% | 0.0% | 100.0% | 30.7% | ○ |
| 命名规范 | 27.29% | 0.0% | 94.7% | 22.2% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. main.py

**糟糕指数: 47.01**

> 行数: 2056 总计, 1704 代码, 30 注释 | 函数: 68 | 类: 1

**问题**: 🔄 复杂度问题: 32, ⚠️ 其他问题: 27, 🏗️ 结构问题: 11, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_reminder` | L590-718 | 129 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L965-1105 | 141 | 31 | 3 | 2 | ✓ |
| `_cmd_plan` | L721-783 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1108-1236 | 121 | 21 | 3 | 2 | ✓ |
| `main` | L1927-2051 | 115 | 19 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L1311-1395 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L1820-1886 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_export` | L424-513 | 90 | 13 | 2 | 2 | ✓ |
| `_cmd_memory` | L888-919 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L516-587 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L832-885 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1569-1608 | 40 | 11 | 2 | 2 | ✓ |
| `_env_write` | L85-112 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L1710-1735 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L195-233 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L236-272 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_detail` | L1445-1474 | 30 | 9 | 2 | 1 | ✓ |
| `_cmd_memory_reindex` | L922-962 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1611-1645 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L1789-1817 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L313-345 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1239-1272 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1275-1308 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1398-1424 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1477-1496 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L1889-1917 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L47-57 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L298-310 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L348-367 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L370-397 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L949-958 | 10 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1676-1707 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L1738-1764 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L60-74 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L287-295 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1224-1231 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L2008-2017 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L77-82 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L146-156 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L159-164 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L178-192 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L400-416 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1658-1669 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L1774-1786 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L115-118 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L121-123 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L126-139 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1508-1509 | 2 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1648-1672 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L1920-1924 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L133-134 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L419-421 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L786-829 | 44 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1427-1442 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1499-1500 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1502-1503 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1505-1506 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1511-1512 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1514-1515 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1517-1518 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1520-1521 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1523-1524 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1526-1527 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1530-1531 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1534-1535 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L1538-1539 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L1542-1543 | 2 | 1 | 0 | 7 | ✗ |
| `_h_detail` | L1546-1547 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (91)**

- 🔄 `_cmd_export()` L424: 复杂度: 13
- 🔄 `_cmd_import()` L516: 复杂度: 11
- 🔄 `_cmd_reminder()` L590: 复杂度: 31
- 🔄 `_cmd_plan()` L721: 复杂度: 21
- 🔄 `_cmd_plugin()` L832: 复杂度: 11
- 🔄 `_cmd_memory()` L888: 复杂度: 12
- 🔄 `_cmd_memory_query()` L965: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1108: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1311: 复杂度: 17
- 🔄 `_cmd_persona()` L1569: 复杂度: 11
- 🔄 `_cmd_hibernate_check()` L1820: 复杂度: 14
- 🔄 `main()` L1927: 复杂度: 19
- 🔄 `_env_write()` L85: 认知复杂度: 20
- 🔄 `_cmd_users()` L195: 认知复杂度: 13
- 🔄 `_cmd_status()` L236: 认知复杂度: 13
- 🔄 `_cmd_export()` L424: 认知复杂度: 17
- 🔄 `_cmd_import()` L516: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L590: 认知复杂度: 39
- 🔄 `_cmd_plan()` L721: 认知复杂度: 25
- 🔄 `_cmd_plugin()` L832: 认知复杂度: 15
- 🔄 `_cmd_memory()` L888: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L965: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1108: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1311: 认知复杂度: 21
- 🔄 `_cmd_detail()` L1445: 认知复杂度: 13
- 🔄 `_cmd_persona()` L1569: 认知复杂度: 15
- 🔄 `_persona_status()` L1611: 认知复杂度: 14
- 🔄 `_persona_materials()` L1710: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L1820: 认知复杂度: 20
- 🔄 `main()` L1927: 认知复杂度: 25
- 🔄 `_env_write()` L85: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L590: 嵌套深度: 4
- 📏 `_cmd_export()` L424: 90 代码量
- 📏 `_cmd_import()` L516: 72 代码量
- 📏 `_cmd_reminder()` L590: 129 代码量
- 📏 `_cmd_plan()` L721: 63 代码量
- 📏 `_cmd_plugin()` L832: 54 代码量
- 📏 `_cmd_memory_query()` L965: 141 代码量
- 📏 `_cmd_memory_rebuild()` L1108: 121 代码量
- 📏 `_cmd_memory_list()` L1311: 85 代码量
- 📏 `_cmd_hibernate_check()` L1820: 67 代码量
- 📏 `main()` L1927: 115 代码量
- 📏 `_execute_command()` L1477: 9 参数数量
- 📏 `_h_newbind()` L1499: 7 参数数量
- 📏 `_h_users()` L1502: 7 参数数量
- 📏 `_h_status()` L1505: 7 参数数量
- 📏 `_h_plugin()` L1508: 7 参数数量
- 📏 `_h_memory()` L1511: 7 参数数量
- 📏 `_h_prompt()` L1514: 7 参数数量
- 📏 `_h_config()` L1517: 7 参数数量
- 📏 `_h_listconfig()` L1520: 7 参数数量
- 📏 `_h_persona()` L1523: 7 参数数量
- 📏 `_h_help()` L1526: 7 参数数量
- 📏 `_h_export()` L1530: 7 参数数量
- 📏 `_h_import()` L1534: 7 参数数量
- 📏 `_h_reminder()` L1538: 7 参数数量
- 📏 `_h_plan()` L1542: 7 参数数量
- 📏 `_h_detail()` L1546: 7 参数数量
- 🏗️ `_env_backup_rotate()` L47: 中等嵌套: 3
- 🏗️ `_env_write()` L85: 嵌套过深: 5
- 🏗️ `_cmd_reminder()` L590: 中等嵌套: 4
- 🏗️ `_cmd_memory_query()` L965: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1108: 中等嵌套: 3
- 🏗️ `_persona_status()` L1611: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L1820: 中等嵌套: 3
- 🏗️ `main()` L1927: 中等嵌套: 3
- 🏗️ L1: 文件过大: 2056 行
- 🏗️ L1: 函数过多: 68
- 🏗️ L1: 导入过多: 46
- ❌ L221: 未处理的易出错调用
- ❌ L229: 未处理的易出错调用
- ❌ L558: 未处理的易出错调用
- ❌ L564: 未处理的易出错调用
- ❌ L578: 未处理的易出错调用
- ❌ L584: 未处理的易出错调用
- ❌ L880: 未处理的易出错调用
- ❌ L1392: 未处理的易出错调用
- ❌ L1643: 未处理的易出错调用
- ❌ L1698: 未处理的易出错调用
- ❌ L1699: 未处理的易出错调用
- ❌ L1700: 未处理的易出错调用
- 🏷️ `_env_backup_rotate()` L47: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L60: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L77: "_env_backup_count" - snake_case
- 🏷️ `_env_write()` L85: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L126: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L146: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L159: "_disable_console_logging" - snake_case
- 🏷️ `_cmd_newbind()` L178: "_cmd_newbind" - snake_case
- 🏷️ `_cmd_users()` L195: "_cmd_users" - snake_case
- 🏷️ `_cmd_status()` L236: "_cmd_status" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 31
- 认知复杂度: 平均: 8.9, 最大: 39
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 27.0 行, 最大: 141 行
- 文件长度: 1704 代码量 (2056 总计)
- 参数数量: 平均: 2.7, 最大: 9
- 代码重复: 1.5% 重复 (1/68)
- 结构分析: 11 个结构问题
- 错误处理: 12/52 个错误被忽略 (23.1%)
- 注释比例: 1.8% (30/1704)
- 命名规范: 发现 65 个违规

### 2. plugins/pipeline.py

**糟糕指数: 45.68**

> 行数: 741 总计, 591 代码, 43 注释 | 函数: 16 | 类: 1

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 🏗️ 结构问题: 6, ❌ 错误处理问题: 16, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L502-740 | 239 | 48 | 7 | 3 | ✓ |
| `_poll_pending_tasks` | L368-490 | 123 | 37 | 6 | 4 | ✓ |
| `_synthesize_lines_sync` | L263-335 | 73 | 18 | 3 | 4 | ✓ |
| `process` | L114-180 | 67 | 13 | 3 | 2 | ✓ |
| `_dispatch_pre_process` | L204-241 | 38 | 7 | 1 | 2 | ✓ |
| `_run_all_plugins` | L346-366 | 21 | 7 | 2 | 5 | ✗ |
| `_call_llm_with_msgs` | L22-45 | 18 | 5 | 2 | 2 | ✓ |
| `_extract_narrations` | L48-63 | 16 | 4 | 3 | 1 | ✓ |
| `_assemble_prompt` | L182-200 | 19 | 4 | 1 | 2 | ✓ |
| `_bridge_progress` | L338-344 | 7 | 3 | 2 | 2 | ✗ |
| `_invoke` | L38-43 | 6 | 2 | 1 | 0 | ✗ |
| `_desc_tool` | L66-71 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L74-81 | 8 | 2 | 1 | 1 | ✗ |
| `__init__` | L98-110 | 13 | 1 | 0 | 6 | ✗ |
| `_synthesize_lines` | L245-251 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L253-261 | 9 | 1 | 0 | 3 | ✓ |

**全部问题 (47)**

- 🔄 `process()` L114: 复杂度: 13
- 🔄 `_synthesize_lines_sync()` L263: 复杂度: 18
- 🔄 `_poll_pending_tasks()` L368: 复杂度: 37
- 🔄 `process_stream()` L502: 复杂度: 48
- 🔄 `process()` L114: 认知复杂度: 19
- 🔄 `_synthesize_lines_sync()` L263: 认知复杂度: 24
- 🔄 `_poll_pending_tasks()` L368: 认知复杂度: 49
- 🔄 `process_stream()` L502: 认知复杂度: 62
- 🔄 `_poll_pending_tasks()` L368: 嵌套深度: 6
- 🔄 `process_stream()` L502: 嵌套深度: 7
- 📏 `process()` L114: 67 代码量
- 📏 `_synthesize_lines_sync()` L263: 73 代码量
- 📏 `_poll_pending_tasks()` L368: 123 代码量
- 📏 `process_stream()` L502: 239 代码量
- 📏 `__init__()` L98: 6 参数数量
- 🏗️ `_extract_narrations()` L48: 中等嵌套: 3
- 🏗️ `process()` L114: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L263: 中等嵌套: 3
- 🏗️ `_poll_pending_tasks()` L368: 嵌套过深: 6
- 🏗️ `process_stream()` L502: 嵌套过深: 7
- 🏗️ L1: 导入过多: 23
- ❌ L170: 未处理的易出错调用
- ❌ L289: 未处理的易出错调用
- ❌ L328: 未处理的易出错调用
- ❌ L331: 未处理的易出错调用
- ❌ L334: 未处理的易出错调用
- ❌ L344: 未处理的易出错调用
- ❌ L350: 未处理的易出错调用
- ❌ L365: 未处理的易出错调用
- ❌ L366: 未处理的易出错调用
- ❌ L400: 未处理的易出错调用
- ❌ L425: 未处理的易出错调用
- ❌ L462: 未处理的易出错调用
- ❌ L652: 未处理的易出错调用
- ❌ L666: 未处理的易出错调用
- ❌ L699: 未处理的易出错调用
- ❌ L735: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L22: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L38: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L48: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L66: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L74: "_desc_task" - snake_case
- 🏷️ `__init__()` L98: "__init__" - snake_case
- 🏷️ `_assemble_prompt()` L182: "_assemble_prompt" - snake_case
- 🏷️ `_dispatch_pre_process()` L204: "_dispatch_pre_process" - snake_case
- 🏷️ `_synthesize_lines()` L245: "_synthesize_lines" - snake_case
- 🏷️ `_synthesize_lines_stream()` L253: "_synthesize_lines_stream" - snake_case

**详情**:
- 循环复杂度: 平均: 9.7, 最大: 48
- 认知复杂度: 平均: 13.8, 最大: 62
- 嵌套深度: 平均: 2.1, 最大: 7
- 函数长度: 平均: 41.9 行, 最大: 239 行
- 文件长度: 591 代码量 (741 总计)
- 参数数量: 平均: 2.5, 最大: 6
- 代码重复: 0.0% 重复 (0/16)
- 结构分析: 6 个结构问题
- 错误处理: 16/40 个错误被忽略 (40.0%)
- 注释比例: 7.3% (43/591)
- 命名规范: 发现 14 个违规

### 3. memory/core.py

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

### 4. engine.py

**糟糕指数: 43.62**

> 行数: 1095 总计, 945 代码, 20 注释 | 函数: 40 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 📋 重复问题: 2, 🏗️ 结构问题: 7, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L858-1094 | 237 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L439-486 | 48 | 17 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L576-622 | 47 | 14 | 2 | 1 | ✗ |
| `build_context` | L660-693 | 34 | 10 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L554-574 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L624-647 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L695-731 | 37 | 9 | 2 | 8 | ✓ |
| `_generate_result_message` | L260-307 | 48 | 8 | 2 | 3 | ✗ |
| `_register_context_plugins` | L533-552 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L733-752 | 20 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L215-233 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L309-330 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L332-360 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L362-387 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L407-423 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L425-437 | 13 | 6 | 3 | 1 | ✓ |
| `index_prompts_for_chat` | L760-780 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L784-832 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L836-844 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L187-201 | 15 | 5 | 3 | 1 | ✗ |
| `_dispatch_task_completion` | L203-213 | 11 | 5 | 2 | 3 | ✗ |
| `from_subapp` | L74-90 | 17 | 3 | 0 | 1 | ✗ |
| `__init__` | L104-136 | 33 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L164-183 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L246-258 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L389-405 | 17 | 3 | 2 | 1 | ✗ |
| `_init_plugins` | L488-498 | 11 | 3 | 0 | 1 | ✗ |
| `_plugin_enabled` | L500-505 | 6 | 3 | 1 | 2 | ✗ |
| `_init_database` | L157-162 | 6 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L235-244 | 10 | 2 | 1 | 3 | ✗ |
| `_register_filter_plugins` | L507-514 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L516-531 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L754-755 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L757-758 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L796-802 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L806-815 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L140-155 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L649-656 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L849-855 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (38)**

- 🔄 `_init_prompt()` L439: 复杂度: 17
- 🔄 `_register_execution_plugins()` L576: 复杂度: 14
- 🔄 `create_engine_with_defaults()` L858: 复杂度: 43
- 🔄 `_init_prompt()` L439: 认知复杂度: 25
- 🔄 `_register_personality_plugins()` L554: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L576: 认知复杂度: 18
- 🔄 `_register_output_plugins()` L624: 认知复杂度: 13
- 🔄 `chat()` L695: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L858: 认知复杂度: 47
- 🔄 `_init_prompt()` L439: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L858: 237 代码量
- 📏 `build_context()` L660: 8 参数数量
- 📏 `chat()` L695: 8 参数数量
- 📏 `chat_stream()` L733: 8 参数数量
- 📏 `create_engine_with_defaults()` L858: 12 参数数量
- 📋 `_init_database()` L157: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L246: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L187: 中等嵌套: 3
- 🏗️ `_init_memory()` L332: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L425: 中等嵌套: 3
- 🏗️ `_init_prompt()` L439: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1095 行
- 🏗️ L1: 导入过多: 86
- ❌ L216: 未处理的易出错调用
- ❌ L230: 未处理的易出错调用
- ❌ L276: 未处理的易出错调用
- ❌ L800: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L42: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L104: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L140: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L157: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L164: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L187: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L203: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L215: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L235: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L246: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 43
- 认知复杂度: 平均: 8.9, 最大: 47
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 24.1 行, 最大: 237 行
- 文件长度: 945 代码量 (1095 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.0% 重复 (4/40)
- 结构分析: 7 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.1% (20/945)
- 命名规范: 发现 27 个违规

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

**糟糕指数: 34.53**

> 行数: 1497 总计, 1364 代码, 43 注释 | 函数: 57 | 类: 0

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 35, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `msgFlow` | L756-886 | 131 | 38 | 4 | 1 | ✗ |
| `sendRecording` | L646-750 | 105 | 36 | 4 | 2 | ✗ |
| `init` | L1464-1494 | 31 | 10 | 2 | 0 | ✓ |
| `openMaintenanceSSE` | L1021-1081 | 61 | 9 | 2 | 0 | ✗ |
| `selectChat` | L428-471 | 44 | 8 | 4 | 1 | ✗ |
| `tryPairLogin` | L353-372 | 20 | 7 | 1 | 0 | ✗ |
| `showTimingLine` | L976-994 | 19 | 7 | 2 | 2 | ✗ |
| `showKeyHints` | L1317-1371 | 55 | 7 | 1 | 0 | ✗ |
| `describeAction` | L194-208 | 15 | 6 | 1 | 2 | ✗ |
| `addMessage` | L273-311 | 39 | 6 | 2 | 3 | ✗ |
| `processLineQueue` | L948-974 | 27 | 6 | 2 | 0 | ✗ |
| `parseControlTags` | L172-192 | 21 | 5 | 4 | 1 | ✗ |
| `startRecording` | L529-550 | 22 | 5 | 1 | 0 | ✗ |
| `stopRecording` | L552-571 | 20 | 5 | 2 | 1 | ✗ |
| `startWaveform` | L593-623 | 31 | 5 | 1 | 0 | ✗ |
| `getAuthHeader` | L314-319 | 6 | 4 | 1 | 0 | ✓ |
| `tryRecoverLogin` | L374-393 | 20 | 4 | 1 | 0 | ✗ |
| `abortStream` | L902-912 | 11 | 4 | 1 | 0 | ✗ |
| `playAudioBase64Wait` | L932-946 | 15 | 4 | 1 | 1 | ✗ |
| `showConfirm` | L1407-1432 | 26 | 4 | 1 | 0 | ✗ |
| `detectTheme` | L10-14 | 5 | 3 | 1 | 0 | ✓ |
| `apiCall` | L320-325 | 6 | 3 | 1 | 3 | ✗ |
| `apiGet` | L326-334 | 9 | 3 | 1 | 1 | ✗ |
| `apiPost` | L337-342 | 6 | 3 | 1 | 2 | ✓ |
| `apiPostJson` | L343-351 | 9 | 3 | 1 | 2 | ✗ |
| `renderChatList` | L413-427 | 15 | 3 | 1 | 0 | ✗ |
| `handleImageSelected` | L486-498 | 13 | 3 | 1 | 1 | ✗ |
| `switchInputMode` | L510-527 | 18 | 3 | 1 | 1 | ✓ |
| `stopWaveform` | L625-633 | 9 | 3 | 1 | 0 | ✗ |
| `playAudioBase64` | L920-930 | 11 | 3 | 1 | 1 | ✗ |
| `renderMaintTasks` | L1083-1091 | 9 | 3 | 0 | 0 | ✗ |
| `updateMaintProgress` | L1093-1105 | 13 | 3 | 1 | 0 | ✗ |
| `hideConfirm` | L1434-1449 | 16 | 3 | 1 | 0 | ✗ |
| `toggleTheme` | L19-21 | 3 | 2 | 0 | 0 | ✗ |
| `addLineStatic` | L238-253 | 16 | 2 | 1 | 3 | ✗ |
| `newChat` | L472-479 | 8 | 2 | 1 | 0 | ✗ |
| `removeImage` | L500-507 | 8 | 2 | 1 | 0 | ✗ |
| `cancelRecording` | L573-581 | 9 | 2 | 1 | 0 | ✗ |
| `uncancelRecording` | L583-591 | 9 | 2 | 1 | 0 | ✗ |
| `sendMessage` | L888-900 | 13 | 2 | 1 | 0 | ✗ |
| `toggleTTS` | L915-919 | 5 | 2 | 0 | 0 | ✓ |
| `checkMaintStatus` | L1107-1116 | 10 | 2 | 1 | 0 | ✗ |
| `hideKeyHints` | L1373-1381 | 9 | 2 | 1 | 0 | ✗ |
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
| `updateStatusBar` | L997-1000 | 4 | 1 | 0 | 0 | ✓ |
| `updateStatusBarText` | L1001-1003 | 3 | 1 | 0 | 1 | ✗ |
| `createKeyCapSVG` | L1301-1311 | 11 | 1 | 0 | 1 | ✓ |
| `doConfirm` | L1451-1455 | 5 | 1 | 0 | 0 | ✗ |

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
- 🏗️ L1: 文件过大: 1497 行
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
- ❌ L908: 未处理的易出错调用
- ❌ L1108: 未处理的易出错调用
- ❌ L1126: 未处理的易出错调用
- ❌ L1136: 未处理的易出错调用
- ❌ L1137: 未处理的易出错调用
- ❌ L1156: 未处理的易出错调用
- ❌ L1378: 未处理的易出错调用
- ❌ L1379: 未处理的易出错调用
- ❌ L1410: 未处理的易出错调用
- ❌ L1413: 未处理的易出错调用
- ❌ L1437: 未处理的易出错调用
- ❌ L1439: 未处理的易出错调用
- ❌ L1444: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 4.4, 最大: 38
- 认知复杂度: 平均: 6.5, 最大: 46
- 嵌套深度: 平均: 1.0, 最大: 4
- 函数长度: 平均: 18.3 行, 最大: 131 行
- 文件长度: 1364 代码量 (1497 总计)
- 参数数量: 平均: 0.6, 最大: 3
- 代码重复: 3.5% 重复 (2/57)
- 结构分析: 6 个结构问题
- 错误处理: 35/59 个错误被忽略 (59.3%)
- 注释比例: 3.2% (43/1364)
- 命名规范: 无命名违规

### 7. tests/test_ncm_music.py

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

### 8. boot.py

**糟糕指数: 31.37**

> 行数: 632 总计, 521 代码, 36 注释 | 函数: 13 | 类: 0

**问题**: 🔄 复杂度问题: 7, ⚠️ 其他问题: 3, 📋 重复问题: 1, 🏗️ 结构问题: 4, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 9

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_application` | L351-631 | 281 | 34 | 4 | 0 | ✓ |
| `_preload_models` | L247-325 | 79 | 14 | 3 | 1 | ✓ |
| `_synthesize_tts_lines` | L126-148 | 23 | 10 | 2 | 1 | ✗ |
| `process_task_completion` | L175-193 | 19 | 8 | 3 | 0 | ✗ |
| `_handle_action_completion` | L217-242 | 26 | 8 | 2 | 3 | ✗ |
| `_convert_audio_to_wav` | L107-123 | 17 | 5 | 2 | 1 | ✗ |
| `_process_image_input` | L79-94 | 16 | 4 | 1 | 2 | ✗ |
| `create_chat_client` | L65-76 | 12 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L207-214 | 8 | 3 | 1 | 2 | ✗ |
| `_save_debug_audio` | L97-104 | 8 | 2 | 1 | 1 | ✗ |
| `setup_logging` | L151-172 | 22 | 2 | 1 | 1 | ✗ |
| `_handle_reminder_completion` | L196-204 | 9 | 2 | 1 | 2 | ✗ |
| `_t` | L335-346 | 12 | 2 | 1 | 1 | ✗ |

**全部问题 (30)**

- 🔄 `_preload_models()` L247: 复杂度: 14
- 🔄 `create_application()` L351: 复杂度: 34
- 🔄 `_synthesize_tts_lines()` L126: 认知复杂度: 14
- 🔄 `process_task_completion()` L175: 认知复杂度: 14
- 🔄 `_preload_models()` L247: 认知复杂度: 20
- 🔄 `create_application()` L351: 认知复杂度: 42
- 🔄 `create_application()` L351: 嵌套深度: 4
- 📏 `_preload_models()` L247: 79 代码量
- 📏 `create_application()` L351: 281 代码量
- 📋 `_save_debug_audio()` L97: 重复模式: _save_debug_audio, _handle_reminder_completion
- 🏗️ `process_task_completion()` L175: 中等嵌套: 3
- 🏗️ `_preload_models()` L247: 中等嵌套: 3
- 🏗️ `create_application()` L351: 中等嵌套: 4
- 🏗️ L1: 导入过多: 47
- ❌ L102: 未处理的易出错调用
- ❌ L103: 未处理的易出错调用
- ❌ L144: 未处理的易出错调用
- ❌ L395: 未处理的易出错调用
- ❌ L411: 未处理的易出错调用
- ❌ L442: 未处理的易出错调用
- ❌ L609: 未处理的易出错调用
- 🏷️ `_process_image_input()` L79: "_process_image_input" - snake_case
- 🏷️ `_save_debug_audio()` L97: "_save_debug_audio" - snake_case
- 🏷️ `_convert_audio_to_wav()` L107: "_convert_audio_to_wav" - snake_case
- 🏷️ `_synthesize_tts_lines()` L126: "_synthesize_tts_lines" - snake_case
- 🏷️ `_handle_reminder_completion()` L196: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L207: "_handle_reasoner_completion" - snake_case
- 🏷️ `_handle_action_completion()` L217: "_handle_action_completion" - snake_case
- 🏷️ `_preload_models()` L247: "_preload_models" - snake_case
- 🏷️ `_t()` L335: "_t" - snake_case

**详情**:
- 循环复杂度: 平均: 7.5, 最大: 34
- 认知复杂度: 平均: 11.0, 最大: 42
- 嵌套深度: 平均: 1.8, 最大: 4
- 函数长度: 平均: 40.9 行, 最大: 281 行
- 文件长度: 521 代码量 (632 总计)
- 参数数量: 平均: 1.2, 最大: 3
- 代码重复: 7.7% 重复 (1/13)
- 结构分析: 4 个结构问题
- 错误处理: 7/33 个错误被忽略 (21.2%)
- 注释比例: 6.9% (36/521)
- 命名规范: 发现 9 个违规

### 9. tasks.py

**糟糕指数: 29.00**

> 行数: 1015 总计, 811 代码, 67 注释 | 函数: 37 | 类: 6

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 9, 📋 重复问题: 2, 🏗️ 结构问题: 7, ❌ 错误处理问题: 23, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_load_persistent_tasks` | L243-307 | 65 | 12 | 5 | 1 | ✓ |
| `_execute_reminder_task` | L586-637 | 52 | 11 | 3 | 2 | ✓ |
| `_save_task` | L309-347 | 39 | 8 | 2 | 2 | ✓ |
| `_schedule_reminder_task` | L370-434 | 42 | 8 | 3 | 2 | ✓ |
| `_execute_action_task` | L656-714 | 59 | 8 | 2 | 2 | ✗ |
| `_action_edit_file` | L786-812 | 27 | 8 | 1 | 4 | ✗ |
| `analyze_complexity` | L932-998 | 67 | 8 | 1 | 3 | ✓ |
| `_update_task_status` | L349-368 | 20 | 7 | 3 | 5 | ✓ |
| `from_dict` | L107-135 | 29 | 6 | 1 | 2 | ✓ |
| `_execute_task_internal` | L511-527 | 17 | 6 | 2 | 2 | ✓ |
| `_execute_reasoner_task` | L529-584 | 56 | 6 | 1 | 2 | ✓ |
| `_action_write_file` | L766-784 | 19 | 6 | 1 | 4 | ✗ |
| `_handle_task_result` | L827-857 | 31 | 6 | 4 | 3 | ✓ |
| `reminder_job` | L378-395 | 18 | 5 | 1 | 0 | ✗ |
| `cancel_task` | L884-904 | 21 | 5 | 2 | 2 | ✓ |
| `to_dict` | L86-104 | 19 | 4 | 0 | 1 | ✓ |
| `create_task` | L443-473 | 31 | 4 | 1 | 8 | ✓ |
| `_run_scheduler` | L436-441 | 6 | 3 | 1 | 1 | ✓ |
| `_action_python` | L739-764 | 26 | 3 | 2 | 4 | ✗ |
| `get_user_tasks` | L873-882 | 10 | 3 | 2 | 3 | ✓ |
| `get_task_manager` | L1004-1009 | 6 | 3 | 1 | 1 | ✓ |
| `_migrate_add_column` | L173-177 | 5 | 2 | 1 | 4 | ✗ |
| `_init_db` | L179-241 | 63 | 2 | 1 | 1 | ✓ |
| `_long_delay_check` | L423-427 | 5 | 2 | 1 | 0 | ✗ |
| `execute_task` | L475-491 | 17 | 2 | 1 | 2 | ✓ |
| `execute_action_sync` | L493-509 | 17 | 2 | 1 | 4 | ✓ |
| `_action_shell` | L720-737 | 18 | 2 | 0 | 4 | ✗ |
| `_save_task_result` | L814-825 | 12 | 2 | 1 | 3 | ✓ |
| `_notify_task_completion` | L859-866 | 8 | 2 | 1 | 3 | ✓ |
| `get_task` | L868-871 | 4 | 2 | 1 | 2 | ✓ |
| `__init__` | L58-84 | 27 | 1 | 0 | 9 | ✗ |
| `__init__` | L141-163 | 23 | 1 | 0 | 3 | ✗ |
| `_execute_analysis_task` | L639-654 | 16 | 1 | 0 | 2 | ✓ |
| `_finalize_action` | L716-718 | 3 | 1 | 0 | 3 | ✗ |
| `shutdown` | L906-910 | 5 | 1 | 0 | 1 | ✓ |
| `__init__` | L916-930 | 15 | 1 | 0 | 1 | ✗ |
| `set_task_manager` | L1011-1014 | 4 | 1 | 0 | 1 | ✓ |

**全部问题 (59)**

- 🔄 `_load_persistent_tasks()` L243: 复杂度: 12
- 🔄 `_execute_reminder_task()` L586: 复杂度: 11
- 🔄 `_load_persistent_tasks()` L243: 认知复杂度: 22
- 🔄 `_update_task_status()` L349: 认知复杂度: 13
- 🔄 `_schedule_reminder_task()` L370: 认知复杂度: 14
- 🔄 `_execute_reminder_task()` L586: 认知复杂度: 17
- 🔄 `_handle_task_result()` L827: 认知复杂度: 14
- 🔄 `_load_persistent_tasks()` L243: 嵌套深度: 5
- 🔄 `_handle_task_result()` L827: 嵌套深度: 4
- 📏 `_init_db()` L179: 63 代码量
- 📏 `_load_persistent_tasks()` L243: 65 代码量
- 📏 `_execute_reasoner_task()` L529: 56 代码量
- 📏 `_execute_reminder_task()` L586: 52 代码量
- 📏 `_execute_action_task()` L656: 59 代码量
- 📏 `analyze_complexity()` L932: 67 代码量
- 📏 `__init__()` L58: 9 参数数量
- 📏 `create_task()` L443: 8 参数数量
- 📋 `_save_task()` L309: 重复模式: _save_task, _action_write_file
- 📋 `_update_task_status()` L349: 重复模式: _update_task_status, _action_shell
- 🏗️ `_load_persistent_tasks()` L243: 嵌套过深: 5
- 🏗️ `_update_task_status()` L349: 中等嵌套: 3
- 🏗️ `_schedule_reminder_task()` L370: 中等嵌套: 3
- 🏗️ `_execute_reminder_task()` L586: 中等嵌套: 3
- 🏗️ `_handle_task_result()` L827: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1015 行
- 🏗️ L1: 导入过多: 31
- ❌ L129: 未处理的易出错调用
- ❌ L131: 未处理的易出错调用
- ❌ L175: 未处理的易出错调用
- ❌ L184: 未处理的易出错调用
- ❌ L206: 未处理的易出错调用
- ❌ L217: 未处理的易出错调用
- ❌ L230: 未处理的易出错调用
- ❌ L240: 未处理的易出错调用
- ❌ L264: 未处理的易出错调用
- ❌ L321: 未处理的易出错调用
- ❌ L344: 未处理的易出错调用
- ❌ L347: 未处理的易出错调用
- ❌ L702: 未处理的易出错调用
- ❌ L703: 未处理的易出错调用
- ❌ L705: 未处理的易出错调用
- ❌ L707: 未处理的易出错调用
- ❌ L744: 未处理的易出错调用
- ❌ L780: 未处理的易出错调用
- ❌ L807: 未处理的易出错调用
- ❌ L818: 未处理的易出错调用
- ❌ L822: 未处理的易出错调用
- ❌ L825: 未处理的易出错调用
- ❌ L866: 未处理的易出错调用
- 🏷️ `__init__()` L58: "__init__" - snake_case
- 🏷️ `__init__()` L141: "__init__" - snake_case
- 🏷️ `_migrate_add_column()` L173: "_migrate_add_column" - snake_case
- 🏷️ `_init_db()` L179: "_init_db" - snake_case
- 🏷️ `_load_persistent_tasks()` L243: "_load_persistent_tasks" - snake_case
- 🏷️ `_save_task()` L309: "_save_task" - snake_case
- 🏷️ `_update_task_status()` L349: "_update_task_status" - snake_case
- 🏷️ `_schedule_reminder_task()` L370: "_schedule_reminder_task" - snake_case
- 🏷️ `_long_delay_check()` L423: "_long_delay_check" - snake_case
- 🏷️ `_run_scheduler()` L436: "_run_scheduler" - snake_case

**详情**:
- 循环复杂度: 平均: 4.2, 最大: 12
- 认知复杂度: 平均: 6.7, 最大: 22
- 嵌套深度: 平均: 1.3, 最大: 5
- 函数长度: 平均: 24.4 行, 最大: 67 行
- 文件长度: 811 代码量 (1015 总计)
- 参数数量: 平均: 2.6, 最大: 9
- 代码重复: 5.4% 重复 (2/37)
- 结构分析: 7 个结构问题
- 错误处理: 23/57 个错误被忽略 (40.4%)
- 注释比例: 8.3% (67/811)
- 命名规范: 发现 24 个违规

### 10. chatdbmgr.py

**糟糕指数: 28.98**

> 行数: 737 总计, 654 代码, 25 注释 | 函数: 28 | 类: 1

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 6, 📋 重复问题: 3, 🏗️ 结构问题: 5, ❌ 错误处理问题: 61, 📝 注释问题: 1, 🏷️ 命名问题: 6

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `append_messages` | L660-711 | 52 | 9 | 3 | 7 | ✓ |
| `_tokenize` | L17-30 | 14 | 7 | 4 | 1 | ✓ |
| `get_messages_by_rounds` | L452-487 | 36 | 6 | 3 | 4 | ✓ |
| `save_chat_history` | L534-569 | 36 | 6 | 3 | 4 | ✓ |
| `_init_db` | L112-297 | 186 | 5 | 4 | 1 | ✓ |
| `get_impressions` | L352-370 | 19 | 4 | 2 | 5 | ✗ |
| `get_next_round_index` | L505-517 | 13 | 4 | 1 | 2 | ✓ |
| `update_impression` | L320-339 | 20 | 3 | 1 | 2 | ✗ |
| `count_impressions` | L372-381 | 10 | 3 | 1 | 2 | ✗ |
| `get_last_message_ids` | L489-503 | 15 | 3 | 2 | 3 | ✓ |
| `get_chat_history` | L571-591 | 21 | 3 | 2 | 3 | ✓ |
| `replace_last_assistant` | L622-643 | 22 | 3 | 2 | 4 | ✓ |
| `load_kv` | L727-736 | 10 | 3 | 1 | 2 | ✗ |
| `__init__` | L40-58 | 19 | 2 | 1 | 3 | ✗ |
| `_get_connection` | L60-66 | 7 | 2 | 1 | 1 | ✓ |
| `close_connection` | L68-72 | 5 | 2 | 1 | 1 | ✓ |
| `_migrate_add_column` | L75-81 | 7 | 2 | 1 | 4 | ✓ |
| `_migrate_messages_role` | L84-110 | 27 | 2 | 1 | 1 | ✓ |
| `add_impression` | L303-318 | 16 | 2 | 1 | 7 | ✗ |
| `delete_impression` | L341-350 | 10 | 2 | 1 | 2 | ✗ |
| `get_impression_categories` | L383-393 | 11 | 2 | 1 | 2 | ✗ |
| `add_or_update_user` | L395-409 | 15 | 2 | 1 | 3 | ✓ |
| `save_memory` | L411-428 | 18 | 2 | 1 | 8 | ✓ |
| `get_memories` | L430-450 | 21 | 2 | 1 | 3 | ✓ |
| `create_chat` | L519-532 | 14 | 2 | 1 | 3 | ✓ |
| `list_chats` | L593-620 | 28 | 2 | 1 | 2 | ✓ |
| `delete_chat` | L645-658 | 14 | 2 | 1 | 3 | ✓ |
| `save_kv` | L713-725 | 13 | 2 | 1 | 3 | ✗ |

**全部问题 (85)**

- 🔄 `_tokenize()` L17: 认知复杂度: 15
- 🔄 `_init_db()` L112: 认知复杂度: 13
- 🔄 `append_messages()` L660: 认知复杂度: 15
- 🔄 `_tokenize()` L17: 嵌套深度: 4
- 🔄 `_init_db()` L112: 嵌套深度: 4
- 📏 `_init_db()` L112: 186 代码量
- 📏 `append_messages()` L660: 52 代码量
- 📏 `add_impression()` L303: 7 参数数量
- 📏 `save_memory()` L411: 8 参数数量
- 📏 `append_messages()` L660: 7 参数数量
- 📋 `_get_connection()` L60: 重复模式: _get_connection, get_memories, delete_chat
- 📋 `add_impression()` L303: 重复模式: add_impression, get_next_round_index
- 📋 `count_impressions()` L372: 重复模式: count_impressions, get_impression_categories, load_kv
- 🏗️ `_tokenize()` L17: 中等嵌套: 4
- 🏗️ `_init_db()` L112: 中等嵌套: 4
- 🏗️ `get_messages_by_rounds()` L452: 中等嵌套: 3
- 🏗️ `save_chat_history()` L534: 中等嵌套: 3
- 🏗️ `append_messages()` L660: 中等嵌套: 3
- ❌ L71: 未处理的易出错调用
- ❌ L78: 未处理的易出错调用
- ❌ L87: 未处理的易出错调用
- ❌ L89: 未处理的易出错调用
- ❌ L94: 未处理的易出错调用
- ❌ L105: 未处理的易出错调用
- ❌ L106: 未处理的易出错调用
- ❌ L107: 未处理的易出错调用
- ❌ L108: 未处理的易出错调用
- ❌ L109: 未处理的易出错调用
- ❌ L117: 未处理的易出错调用
- ❌ L128: 未处理的易出错调用
- ❌ L137: 未处理的易出错调用
- ❌ L147: 未处理的易出错调用
- ❌ L148: 未处理的易出错调用
- ❌ L151: 未处理的易出错调用
- ❌ L163: 未处理的易出错调用
- ❌ L167: 未处理的易出错调用
- ❌ L174: 未处理的易出错调用
- ❌ L180: 未处理的易出错调用
- ❌ L185: 未处理的易出错调用
- ❌ L199: 未处理的易出错调用
- ❌ L200: 未处理的易出错调用
- ❌ L203: 未处理的易出错调用
- ❌ L215: 未处理的易出错调用
- ❌ L231: 未处理的易出错调用
- ❌ L240: 未处理的易出错调用
- ❌ L249: 未处理的易出错调用
- ❌ L263: 未处理的易出错调用
- ❌ L272: 未处理的易出错调用
- ❌ L287: 未处理的易出错调用
- ❌ L292: 未处理的易出错调用
- ❌ L296: 未处理的易出错调用
- ❌ L313: 未处理的易出错调用
- ❌ L317: 未处理的易出错调用
- ❌ L330: 未处理的易出错调用
- ❌ L334: 未处理的易出错调用
- ❌ L338: 未处理的易出错调用
- ❌ L345: 未处理的易出错调用
- ❌ L349: 未处理的易出错调用
- ❌ L399: 未处理的易出错调用
- ❌ L404: 未处理的易出错调用
- ❌ L408: 未处理的易出错调用
- ❌ L422: 未处理的易出错调用
- ❌ L427: 未处理的易出错调用
- ❌ L527: 未处理的易出错调用
- ❌ L531: 未处理的易出错调用
- ❌ L543: 未处理的易出错调用
- ❌ L563: 未处理的易出错调用
- ❌ L568: 未处理的易出错调用
- ❌ L634: 未处理的易出错调用
- ❌ L638: 未处理的易出错调用
- ❌ L642: 未处理的易出错调用
- ❌ L653: 未处理的易出错调用
- ❌ L657: 未处理的易出错调用
- ❌ L697: 未处理的易出错调用
- ❌ L706: 未处理的易出错调用
- ❌ L710: 未处理的易出错调用
- ❌ L716: 未处理的易出错调用
- ❌ L720: 未处理的易出错调用
- ❌ L724: 未处理的易出错调用
- 🏷️ `_tokenize()` L17: "_tokenize" - snake_case
- 🏷️ `__init__()` L40: "__init__" - snake_case
- 🏷️ `_get_connection()` L60: "_get_connection" - snake_case
- 🏷️ `_migrate_add_column()` L75: "_migrate_add_column" - snake_case
- 🏷️ `_migrate_messages_role()` L84: "_migrate_messages_role" - snake_case
- 🏷️ `_init_db()` L112: "_init_db" - snake_case

**详情**:
- 循环复杂度: 平均: 3.2, 最大: 9
- 认知复杂度: 平均: 6.3, 最大: 15
- 嵌套深度: 平均: 1.6, 最大: 4
- 函数长度: 平均: 24.3 行, 最大: 186 行
- 文件长度: 654 代码量 (737 总计)
- 参数数量: 平均: 3.1, 最大: 8
- 代码重复: 17.9% 重复 (5/28)
- 结构分析: 5 个结构问题
- 错误处理: 61/88 个错误被忽略 (69.3%)
- 注释比例: 3.8% (25/654)
- 命名规范: 发现 6 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `process_stream` | plugins/pipeline.py | 48 | 7 | 239 |
| `main` | psychoscope/minimal.py | 44 | 6 | 192 |
| `create_engine_with_defaults` | engine.py | 43 | 2 | 237 |
| `search` | memory/core.py | 38 | 7 | 129 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `_poll_pending_tasks` | plugins/pipeline.py | 37 | 6 | 123 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `create_application` | boot.py | 34 | 4 | 281 |
| `_cmd_reminder` | main.py | 31 | 4 | 129 |
| `_cmd_memory_query` | main.py | 31 | 3 | 141 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*