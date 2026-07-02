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
| **糟糕指数** | **79.19/100** |
| 屎山等级 | 😐 微臭青年 |

> 略带清香，偶尔飘过一丝酸爽

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 229 |
| 已跳过 | 716 |
| 耗时 | 1132ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 37758 |
| 总注释行数 | 1731 |
| 整体注释比例 | 4.6% |
| 平均文件大小 | 205 行 |
| 最大文件 | `main.py` (2349) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 226 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 9.67% | 0.0% | 80.0% | 2.0% | ✓✓ |
| 认知复杂度 | 13.01% | 0.0% | 70.0% | 8.0% | ✓✓ |
| 嵌套深度 | 4.19% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 函数长度 | 5.87% | 0.0% | 56.8% | 0.0% | ✓✓ |
| 文件长度 | 2.69% | 0.0% | 94.0% | 0.0% | ✓✓ |
| 参数数量 | 13.46% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.52% | 0.0% | 67.6% | 0.0% | ✓✓ |
| 结构分析 | 4.77% | 0.0% | 79.5% | 0.0% | ✓✓ |
| 错误处理 | 32.41% | 0.0% | 98.8% | 6.7% | ✓ |
| 注释比例 | 45.05% | 0.0% | 100.0% | 44.7% | ○ |
| 命名规范 | 31.55% | 0.0% | 100.0% | 25.0% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. plugins/pipeline.py

**糟糕指数: 52.05**

> 行数: 1260 总计, 1028 代码, 60 注释 | 函数: 32 | 类: 1

**问题**: 🔄 复杂度问题: 21, ⚠️ 其他问题: 8, 🏗️ 结构问题: 12, ❌ 错误处理问题: 34, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L896-1259 | 356 | 75 | 7 | 3 | ✓ |
| `_poll_pending_tasks` | L762-884 | 123 | 38 | 6 | 4 | ✓ |
| `_run_agent_loop` | L363-505 | 143 | 28 | 4 | 2 | ✗ |
| `_synthesize_lines_sync` | L643-724 | 82 | 23 | 4 | 4 | ✓ |
| `process` | L179-262 | 84 | 16 | 3 | 2 | ✗ |
| `_run_tool` | L296-333 | 38 | 9 | 4 | 0 | ✓ |
| `_print_timing` | L507-532 | 26 | 9 | 4 | 3 | ✗ |
| `_format_tag_results` | L543-560 | 18 | 8 | 3 | 1 | ✗ |
| `_run_all_plugins` | L735-760 | 26 | 8 | 2 | 5 | ✗ |
| `_dispatch_pre_process` | L584-621 | 38 | 7 | 1 | 2 | ✓ |
| `process_tts` | L144-158 | 15 | 6 | 4 | 2 | ✓ |
| `_run_async_background` | L267-339 | 35 | 6 | 2 | 2 | ✗ |
| `_call_llm_with_msgs` | L45-71 | 18 | 5 | 2 | 2 | ✓ |
| `_report_agent_progress` | L342-361 | 20 | 5 | 1 | 6 | ✓ |
| `_extract_narrations` | L74-89 | 16 | 4 | 3 | 1 | ✓ |
| `process_post_process` | L169-175 | 7 | 4 | 1 | 3 | ✓ |
| `_print_plugin_timing` | L534-540 | 7 | 4 | 2 | 2 | ✗ |
| `_assemble_prompt` | L562-580 | 19 | 4 | 1 | 2 | ✓ |
| `_invoke` | L61-69 | 9 | 3 | 2 | 0 | ✗ |
| `_bridge_progress` | L727-733 | 7 | 3 | 2 | 2 | ✗ |
| `_consume_agent_progress` | L1065-1072 | 8 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L92-97 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L100-107 | 8 | 2 | 1 | 1 | ✗ |
| `process_pre_process` | L160-167 | 8 | 2 | 1 | 2 | ✓ |
| `timer_enabled` | L25-26 | 2 | 1 | 0 | 0 | ✗ |
| `enable_timer` | L29-31 | 3 | 1 | 0 | 0 | ✗ |
| `disable_timer` | L34-36 | 3 | 1 | 0 | 0 | ✗ |
| `toggle_timer` | L39-42 | 4 | 1 | 0 | 0 | ✗ |
| `__init__` | L124-140 | 17 | 1 | 0 | 8 | ✗ |
| `_dispatch_post_process` | L264-265 | 2 | 1 | 0 | 2 | ✗ |
| `_synthesize_lines` | L625-631 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L633-641 | 9 | 1 | 0 | 3 | ✓ |

**全部问题 (84)**

- 🔄 `process()` L179: 复杂度: 16
- 🔄 `_run_agent_loop()` L363: 复杂度: 28
- 🔄 `_synthesize_lines_sync()` L643: 复杂度: 23
- 🔄 `_poll_pending_tasks()` L762: 复杂度: 38
- 🔄 `process_stream()` L896: 复杂度: 75
- 🔄 `process_tts()` L144: 认知复杂度: 14
- 🔄 `process()` L179: 认知复杂度: 22
- 🔄 `_run_tool()` L296: 认知复杂度: 17
- 🔄 `_run_agent_loop()` L363: 认知复杂度: 36
- 🔄 `_print_timing()` L507: 认知复杂度: 17
- 🔄 `_format_tag_results()` L543: 认知复杂度: 14
- 🔄 `_synthesize_lines_sync()` L643: 认知复杂度: 31
- 🔄 `_poll_pending_tasks()` L762: 认知复杂度: 50
- 🔄 `process_stream()` L896: 认知复杂度: 89
- 🔄 `process_tts()` L144: 嵌套深度: 4
- 🔄 `_run_tool()` L296: 嵌套深度: 4
- 🔄 `_run_agent_loop()` L363: 嵌套深度: 4
- 🔄 `_print_timing()` L507: 嵌套深度: 4
- 🔄 `_synthesize_lines_sync()` L643: 嵌套深度: 4
- 🔄 `_poll_pending_tasks()` L762: 嵌套深度: 6
- 🔄 `process_stream()` L896: 嵌套深度: 7
- 📏 `process()` L179: 84 代码量
- 📏 `_run_agent_loop()` L363: 143 代码量
- 📏 `_synthesize_lines_sync()` L643: 82 代码量
- 📏 `_poll_pending_tasks()` L762: 123 代码量
- 📏 `process_stream()` L896: 356 代码量
- 📏 `__init__()` L124: 8 参数数量
- 📏 `_report_agent_progress()` L342: 6 参数数量
- 🏗️ `_extract_narrations()` L74: 中等嵌套: 3
- 🏗️ `process_tts()` L144: 中等嵌套: 4
- 🏗️ `process()` L179: 中等嵌套: 3
- 🏗️ `_run_tool()` L296: 中等嵌套: 4
- 🏗️ `_run_agent_loop()` L363: 中等嵌套: 4
- 🏗️ `_print_timing()` L507: 中等嵌套: 4
- 🏗️ `_format_tag_results()` L543: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L643: 中等嵌套: 4
- 🏗️ `_poll_pending_tasks()` L762: 嵌套过深: 6
- 🏗️ `process_stream()` L896: 嵌套过深: 7
- 🏗️ L1: 文件过大: 1260 行
- 🏗️ L1: 导入过多: 29
- ❌ L151: 未处理的易出错调用
- ❌ L173: 未处理的易出错调用
- ❌ L216: 未处理的易出错调用
- ❌ L232: 未处理的易出错调用
- ❌ L248: 未处理的易出错调用
- ❌ L273: 未处理的易出错调用
- ❌ L313: 未处理的易出错调用
- ❌ L314: 未处理的易出错调用
- ❌ L315: 未处理的易出错调用
- ❌ L333: 未处理的易出错调用
- ❌ L350: 未处理的易出错调用
- ❌ L361: 未处理的易出错调用
- ❌ L394: 未处理的易出错调用
- ❌ L416: 未处理的易出错调用
- ❌ L440: 未处理的易出错调用
- ❌ L558: 未处理的易出错调用
- ❌ L669: 未处理的易出错调用
- ❌ L717: 未处理的易出错调用
- ❌ L720: 未处理的易出错调用
- ❌ L723: 未处理的易出错调用
- ❌ L733: 未处理的易出错调用
- ❌ L739: 未处理的易出错调用
- ❌ L759: 未处理的易出错调用
- ❌ L760: 未处理的易出错调用
- ❌ L794: 未处理的易出错调用
- ❌ L819: 未处理的易出错调用
- ❌ L856: 未处理的易出错调用
- ❌ L956: 未处理的易出错调用
- ❌ L1072: 未处理的易出错调用
- ❌ L1165: 未处理的易出错调用
- ❌ L1179: 未处理的易出错调用
- ❌ L1196: 未处理的易出错调用
- ❌ L1216: 未处理的易出错调用
- ❌ L1254: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L45: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L61: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L74: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L92: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L100: "_desc_task" - snake_case
- 🏷️ `__init__()` L124: "__init__" - snake_case
- 🏷️ `_dispatch_post_process()` L264: "_dispatch_post_process" - snake_case
- 🏷️ `_run_async_background()` L267: "_run_async_background" - snake_case
- 🏷️ `_run_tool()` L296: "_run_tool" - snake_case
- 🏷️ `_report_agent_progress()` L342: "_report_agent_progress" - snake_case

**详情**:
- 循环复杂度: 平均: 8.8, 最大: 75
- 认知复杂度: 平均: 12.8, 最大: 89
- 嵌套深度: 平均: 2.0, 最大: 7
- 函数长度: 平均: 36.4 行, 最大: 356 行
- 文件长度: 1028 代码量 (1260 总计)
- 参数数量: 平均: 2.2, 最大: 8
- 代码重复: 3.1% 重复 (1/32)
- 结构分析: 12 个结构问题
- 错误处理: 34/78 个错误被忽略 (43.6%)
- 注释比例: 5.8% (60/1028)
- 命名规范: 发现 23 个违规

### 2. main.py

**糟糕指数: 48.87**

> 行数: 2349 总计, 1954 代码, 37 注释 | 函数: 73 | 类: 1

**问题**: 🔄 复杂度问题: 38, ⚠️ 其他问题: 30, 🏗️ 结构问题: 14, ❌ 错误处理问题: 14, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_agent` | L1785-1929 | 145 | 34 | 3 | 3 | ✓ |
| `_cmd_reminder` | L682-810 | 129 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L1062-1202 | 141 | 31 | 3 | 2 | ✓ |
| `main` | L2184-2344 | 151 | 25 | 3 | 0 | ✗ |
| `_cmd_plan` | L813-875 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1205-1333 | 121 | 21 | 3 | 2 | ✓ |
| `_cmd_memory_list` | L1408-1492 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L2077-2143 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_export` | L516-605 | 90 | 13 | 2 | 2 | ✓ |
| `_cmd_memory` | L985-1016 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L608-679 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L929-982 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1679-1718 | 40 | 11 | 2 | 2 | ✓ |
| `_check_port_available` | L123-171 | 49 | 10 | 5 | 2 | ✗ |
| `_env_write` | L174-201 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L1967-1992 | 26 | 10 | 2 | 2 | ✗ |
| `_is_env_configured` | L24-39 | 16 | 9 | 4 | 0 | ✗ |
| `_cmd_users` | L287-325 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L328-364 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_detail` | L1542-1571 | 30 | 9 | 2 | 1 | ✓ |
| `_cmd_memory_reindex` | L1019-1059 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1721-1755 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L2046-2074 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L405-437 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1336-1369 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1372-1405 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1495-1521 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1574-1593 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L2146-2174 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L85-95 | 11 | 5 | 3 | 0 | ✓ |
| `_enable_console_logging` | L235-248 | 14 | 5 | 2 | 0 | ✗ |
| `_try_convert` | L390-402 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L440-459 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L462-489 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L1046-1055 | 10 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1933-1964 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L1995-2021 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L98-112 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L379-387 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1321-1328 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L2296-2305 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L115-120 | 6 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L251-256 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L270-284 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L492-508 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1768-1779 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L2031-2043 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L204-207 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L210-212 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L215-228 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1605-1606 | 2 | 2 | 0 | 7 | ✗ |
| `_h_timer` | L1650-1655 | 6 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1758-1782 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L2177-2181 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L222-223 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L511-513 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L878-926 | 49 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1524-1539 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1596-1597 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1599-1600 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1602-1603 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1608-1609 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1611-1612 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1614-1615 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1617-1618 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1620-1621 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1623-1624 | 2 | 1 | 0 | 7 | ✗ |
| `_h_agent` | L1626-1627 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1630-1631 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1634-1635 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L1638-1639 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L1642-1643 | 2 | 1 | 0 | 7 | ✗ |
| `_h_detail` | L1646-1647 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (105)**

- 🔄 `_cmd_export()` L516: 复杂度: 13
- 🔄 `_cmd_import()` L608: 复杂度: 11
- 🔄 `_cmd_reminder()` L682: 复杂度: 31
- 🔄 `_cmd_plan()` L813: 复杂度: 21
- 🔄 `_cmd_plugin()` L929: 复杂度: 11
- 🔄 `_cmd_memory()` L985: 复杂度: 12
- 🔄 `_cmd_memory_query()` L1062: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1205: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1408: 复杂度: 17
- 🔄 `_cmd_persona()` L1679: 复杂度: 11
- 🔄 `_cmd_agent()` L1785: 复杂度: 34
- 🔄 `_cmd_hibernate_check()` L2077: 复杂度: 14
- 🔄 `main()` L2184: 复杂度: 25
- 🔄 `_is_env_configured()` L24: 认知复杂度: 17
- 🔄 `_check_port_available()` L123: 认知复杂度: 20
- 🔄 `_env_write()` L174: 认知复杂度: 20
- 🔄 `_cmd_users()` L287: 认知复杂度: 13
- 🔄 `_cmd_status()` L328: 认知复杂度: 13
- 🔄 `_cmd_export()` L516: 认知复杂度: 17
- 🔄 `_cmd_import()` L608: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L682: 认知复杂度: 39
- 🔄 `_cmd_plan()` L813: 认知复杂度: 25
- 🔄 `_cmd_plugin()` L929: 认知复杂度: 15
- 🔄 `_cmd_memory()` L985: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L1062: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1205: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1408: 认知复杂度: 21
- 🔄 `_cmd_detail()` L1542: 认知复杂度: 13
- 🔄 `_cmd_persona()` L1679: 认知复杂度: 15
- 🔄 `_persona_status()` L1721: 认知复杂度: 14
- 🔄 `_cmd_agent()` L1785: 认知复杂度: 40
- 🔄 `_persona_materials()` L1967: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L2077: 认知复杂度: 20
- 🔄 `main()` L2184: 认知复杂度: 31
- 🔄 `_is_env_configured()` L24: 嵌套深度: 4
- 🔄 `_check_port_available()` L123: 嵌套深度: 5
- 🔄 `_env_write()` L174: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L682: 嵌套深度: 4
- 📏 `_cmd_export()` L516: 90 代码量
- 📏 `_cmd_import()` L608: 72 代码量
- 📏 `_cmd_reminder()` L682: 129 代码量
- 📏 `_cmd_plan()` L813: 63 代码量
- 📏 `_cmd_plugin()` L929: 54 代码量
- 📏 `_cmd_memory_query()` L1062: 141 代码量
- 📏 `_cmd_memory_rebuild()` L1205: 121 代码量
- 📏 `_cmd_memory_list()` L1408: 85 代码量
- 📏 `_cmd_agent()` L1785: 145 代码量
- 📏 `_cmd_hibernate_check()` L2077: 67 代码量
- 📏 `main()` L2184: 151 代码量
- 📏 `_execute_command()` L1574: 9 参数数量
- 📏 `_h_newbind()` L1596: 7 参数数量
- 📏 `_h_users()` L1599: 7 参数数量
- 📏 `_h_status()` L1602: 7 参数数量
- 📏 `_h_plugin()` L1605: 7 参数数量
- 📏 `_h_memory()` L1608: 7 参数数量
- 📏 `_h_prompt()` L1611: 7 参数数量
- 📏 `_h_config()` L1614: 7 参数数量
- 📏 `_h_listconfig()` L1617: 7 参数数量
- 📏 `_h_persona()` L1620: 7 参数数量
- 📏 `_h_help()` L1623: 7 参数数量
- 📏 `_h_agent()` L1626: 7 参数数量
- 📏 `_h_export()` L1630: 7 参数数量
- 📏 `_h_import()` L1634: 7 参数数量
- 📏 `_h_reminder()` L1638: 7 参数数量
- 📏 `_h_plan()` L1642: 7 参数数量
- 📏 `_h_detail()` L1646: 7 参数数量
- 📏 `_h_timer()` L1650: 7 参数数量
- 🏗️ `_is_env_configured()` L24: 中等嵌套: 4
- 🏗️ `_env_backup_rotate()` L85: 中等嵌套: 3
- 🏗️ `_check_port_available()` L123: 嵌套过深: 5
- 🏗️ `_env_write()` L174: 嵌套过深: 5
- 🏗️ `_cmd_reminder()` L682: 中等嵌套: 4
- 🏗️ `_cmd_memory_query()` L1062: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1205: 中等嵌套: 3
- 🏗️ `_persona_status()` L1721: 中等嵌套: 3
- 🏗️ `_cmd_agent()` L1785: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L2077: 中等嵌套: 3
- 🏗️ `main()` L2184: 中等嵌套: 3
- 🏗️ L1: 文件过大: 2349 行
- 🏗️ L1: 函数过多: 73
- 🏗️ L1: 导入过多: 53
- ❌ L130: 未处理的易出错调用
- ❌ L313: 未处理的易出错调用
- ❌ L321: 未处理的易出错调用
- ❌ L650: 未处理的易出错调用
- ❌ L656: 未处理的易出错调用
- ❌ L670: 未处理的易出错调用
- ❌ L676: 未处理的易出错调用
- ❌ L977: 未处理的易出错调用
- ❌ L1489: 未处理的易出错调用
- ❌ L1753: 未处理的易出错调用
- ❌ L1928: 未处理的易出错调用
- ❌ L1955: 未处理的易出错调用
- ❌ L1956: 未处理的易出错调用
- ❌ L1957: 未处理的易出错调用
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
- 循环复杂度: 平均: 6.7, 最大: 34
- 认知复杂度: 平均: 9.5, 最大: 40
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 28.7 行, 最大: 151 行
- 文件长度: 1954 代码量 (2349 总计)
- 参数数量: 平均: 2.8, 最大: 9
- 代码重复: 1.4% 重复 (1/73)
- 结构分析: 14 个结构问题
- 错误处理: 14/62 个错误被忽略 (22.6%)
- 注释比例: 1.9% (37/1954)
- 命名规范: 发现 70 个违规

### 3. psychoscope/minimal.py

**糟糕指数: 45.91**

> 行数: 1160 总计, 975 代码, 24 注释 | 函数: 47 | 类: 5

**问题**: 🔄 复杂度问题: 23, ⚠️ 其他问题: 6, 📋 重复问题: 3, 🏗️ 结构问题: 13, ❌ 错误处理问题: 16, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L942-1157 | 207 | 49 | 8 | 0 | ✗ |
| `_loop` | L457-523 | 67 | 24 | 6 | 1 | ✗ |
| `_handle_sse_stream` | L371-416 | 46 | 17 | 4 | 5 | ✗ |
| `_beat` | L602-665 | 64 | 15 | 1 | 1 | ✓ |
| `authenticate` | L194-275 | 82 | 14 | 2 | 3 | ✗ |
| `stop_and_send` | L718-750 | 33 | 10 | 2 | 1 | ✗ |
| `print_system_info` | L904-940 | 37 | 10 | 4 | 1 | ✓ |
| `_capture_loop` | L752-782 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L808-834 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L125-142 | 18 | 8 | 3 | 1 | ✗ |
| `_tts_worker` | L172-192 | 21 | 8 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L71-84 | 14 | 6 | 5 | 0 | ✓ |
| `send_audio` | L331-369 | 39 | 6 | 2 | 2 | ✗ |
| `_verify_api_key` | L277-294 | 18 | 5 | 3 | 1 | ✗ |
| `send_async` | L313-329 | 17 | 5 | 2 | 2 | ✓ |
| `skip_latest` | L568-586 | 19 | 5 | 2 | 1 | ✓ |
| `_loop` | L588-600 | 13 | 5 | 3 | 1 | ✗ |
| `_play_beep` | L98-112 | 15 | 4 | 1 | 2 | ✓ |
| `__init__` | L156-170 | 15 | 4 | 1 | 3 | ✗ |
| `start` | L696-716 | 21 | 4 | 1 | 1 | ✗ |
| `print_header` | L836-866 | 31 | 4 | 1 | 3 | ✗ |
| `load_config` | L144-150 | 7 | 3 | 2 | 0 | ✗ |
| `add_task` | L448-455 | 8 | 3 | 2 | 2 | ✓ |
| `print_personality` | L868-893 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L46-66 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L115-123 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L296-299 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L434-440 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L442-446 | 5 | 2 | 1 | 1 | ✗ |
| `start` | L551-557 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L559-562 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L790-795 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L797-800 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L802-806 | 5 | 2 | 1 | 2 | ✗ |
| `toggle_standby` | L895-901 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L1003-1011 | 9 | 2 | 1 | 2 | ✗ |
| `save_config` | L152-153 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L301-303 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L305-307 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L309-311 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L425-432 | 8 | 1 | 0 | 3 | ✗ |
| `__init__` | L543-549 | 7 | 1 | 0 | 3 | ✗ |
| `sync_now` | L564-566 | 3 | 1 | 0 | 1 | ✓ |
| `_type_label` | L668-673 | 6 | 1 | 0 | 1 | ✗ |
| `__init__` | L681-690 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L693-694 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L785-788 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (69)**

- 🔄 `authenticate()` L194: 复杂度: 14
- 🔄 `_handle_sse_stream()` L371: 复杂度: 17
- 🔄 `_loop()` L457: 复杂度: 24
- 🔄 `_beat()` L602: 复杂度: 15
- 🔄 `main()` L942: 复杂度: 49
- 🔄 `_detect_tts_sample_rate()` L71: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L125: 认知复杂度: 14
- 🔄 `_tts_worker()` L172: 认知复杂度: 14
- 🔄 `authenticate()` L194: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L371: 认知复杂度: 25
- 🔄 `_loop()` L457: 认知复杂度: 36
- 🔄 `_beat()` L602: 认知复杂度: 17
- 🔄 `stop_and_send()` L718: 认知复杂度: 14
- 🔄 `_capture_loop()` L752: 认知复杂度: 15
- 🔄 `_loop()` L808: 认知复杂度: 19
- 🔄 `print_system_info()` L904: 认知复杂度: 18
- 🔄 `main()` L942: 认知复杂度: 65
- 🔄 `_detect_tts_sample_rate()` L71: 嵌套深度: 5
- 🔄 `_handle_sse_stream()` L371: 嵌套深度: 4
- 🔄 `_loop()` L457: 嵌套深度: 6
- 🔄 `_loop()` L808: 嵌套深度: 5
- 🔄 `print_system_info()` L904: 嵌套深度: 4
- 🔄 `main()` L942: 嵌套深度: 8
- 📏 `authenticate()` L194: 82 代码量
- 📏 `_loop()` L457: 67 代码量
- 📏 `_beat()` L602: 64 代码量
- 📏 `main()` L942: 207 代码量
- 📋 `_tts_worker()` L172: 重复模式: _tts_worker, _loop
- 📋 `__init__()` L425: 重复模式: __init__, print_header
- 📋 `start()` L434: 重复模式: start, start
- 🏗️ `_detect_tts_sample_rate()` L71: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L125: 中等嵌套: 3
- 🏗️ `_tts_worker()` L172: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L277: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L371: 中等嵌套: 4
- 🏗️ `_loop()` L457: 嵌套过深: 6
- 🏗️ `_loop()` L588: 中等嵌套: 3
- 🏗️ `_capture_loop()` L752: 中等嵌套: 3
- 🏗️ `_loop()` L808: 嵌套过深: 5
- 🏗️ `print_system_info()` L904: 中等嵌套: 4
- 🏗️ `main()` L942: 嵌套过深: 8
- 🏗️ L1: 文件过大: 1160 行
- 🏗️ L1: 导入过多: 25
- ❌ L76: 未处理的易出错调用
- ❌ L118: 未处理的易出错调用
- ❌ L411: 未处理的易出错调用
- ❌ L482: 未处理的易出错调用
- ❌ L496: 未处理的易出错调用
- ❌ L514: 未处理的易出错调用
- ❌ L582: 未处理的易出错调用
- ❌ L623: 未处理的易出错调用
- ❌ L650: 未处理的易出错调用
- ❌ L736: 未处理的易出错调用
- ❌ L821: 未处理的易出错调用
- ❌ L830: 未处理的易出错调用
- ❌ L889: 未处理的易出错调用
- ❌ L911: 未处理的易出错调用
- ❌ L936: 未处理的易出错调用
- ❌ L1097: 未处理的易出错调用
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
- 循环复杂度: 平均: 5.6, 最大: 49
- 认知复杂度: 平均: 9.0, 最大: 65
- 嵌套深度: 平均: 1.7, 最大: 8
- 函数长度: 平均: 21.6 行, 最大: 207 行
- 文件长度: 975 代码量 (1160 总计)
- 参数数量: 平均: 1.4, 最大: 5
- 代码重复: 6.4% 重复 (3/47)
- 结构分析: 13 个结构问题
- 错误处理: 16/102 个错误被忽略 (15.7%)
- 注释比例: 2.5% (24/975)
- 命名规范: 发现 20 个违规

### 4. engine.py

**糟糕指数: 45.32**

> 行数: 1293 总计, 1110 代码, 30 注释 | 函数: 48 | 类: 2

**问题**: 🔄 复杂度问题: 13, ⚠️ 其他问题: 8, 📋 重复问题: 5, 🏗️ 结构问题: 9, ❌ 错误处理问题: 11, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L1072-1292 | 221 | 40 | 2 | 12 | ✓ |
| `_init_prompt` | L492-539 | 48 | 17 | 4 | 1 | ✗ |
| `build_context` | L701-737 | 37 | 13 | 1 | 8 | ✓ |
| `_register_execution_plugins` | L633-662 | 30 | 12 | 2 | 1 | ✗ |
| `chat_debug_respond` | L857-930 | 74 | 11 | 2 | 4 | ✓ |
| `_register_output_plugins` | L663-686 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L770-806 | 37 | 9 | 2 | 8 | ✓ |
| `_dispatch_task_completion` | L210-224 | 15 | 8 | 2 | 3 | ✗ |
| `_generate_result_message` | L276-323 | 48 | 8 | 2 | 3 | ✗ |
| `_register_context_plugins` | L593-612 | 20 | 8 | 1 | 1 | ✗ |
| `_register_personality_plugins` | L614-631 | 18 | 8 | 2 | 1 | ✗ |
| `chat_stream` | L808-827 | 20 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L226-244 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L43-49 | 7 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L325-346 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L348-376 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L378-403 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L423-443 | 21 | 6 | 2 | 1 | ✗ |
| `_inject_system_skill_deps` | L445-476 | 32 | 6 | 3 | 1 | ✓ |
| `_inject_v3_to_exa_evolution` | L478-490 | 13 | 6 | 3 | 1 | ✓ |
| `chat_debug` | L831-855 | 25 | 6 | 0 | 6 | ✓ |
| `index_prompts_for_chat` | L974-994 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L998-1046 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L1050-1058 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L194-208 | 15 | 5 | 3 | 1 | ✗ |
| `_init_plugins` | L541-558 | 18 | 5 | 1 | 1 | ✗ |
| `_dump_context_for_session` | L936-966 | 31 | 5 | 3 | 2 | ✓ |
| `from_subapp` | L78-95 | 18 | 3 | 0 | 1 | ✗ |
| `__init__` | L109-141 | 33 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L171-190 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L262-274 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L405-421 | 17 | 3 | 2 | 1 | ✗ |
| `_plugin_enabled` | L560-565 | 6 | 3 | 1 | 2 | ✗ |
| `_get_skills_info` | L742-754 | 13 | 3 | 2 | 1 | ✗ |
| `_get_tool_parameters` | L756-768 | 13 | 3 | 2 | 2 | ✗ |
| `_init_database` | L162-169 | 8 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L246-260 | 15 | 2 | 1 | 3 | ✓ |
| `_register_filter_plugins` | L567-574 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L576-591 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L968-969 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L971-972 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L1010-1016 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L1020-1029 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L145-160 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L688-697 | 10 | 1 | 0 | 1 | ✗ |
| `_is_debug_mode` | L739-740 | 2 | 1 | 0 | 1 | ✗ |
| `process_tts` | L932-934 | 3 | 1 | 0 | 2 | ✓ |
| `create_engine` | L1063-1069 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (55)**

- 🔄 `_init_prompt()` L492: 复杂度: 17
- 🔄 `_register_execution_plugins()` L633: 复杂度: 12
- 🔄 `build_context()` L701: 复杂度: 13
- 🔄 `chat_debug_respond()` L857: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L1072: 复杂度: 40
- 🔄 `_init_prompt()` L492: 认知复杂度: 25
- 🔄 `_register_execution_plugins()` L633: 认知复杂度: 16
- 🔄 `_register_output_plugins()` L663: 认知复杂度: 13
- 🔄 `build_context()` L701: 认知复杂度: 15
- 🔄 `chat()` L770: 认知复杂度: 13
- 🔄 `chat_debug_respond()` L857: 认知复杂度: 15
- 🔄 `create_engine_with_defaults()` L1072: 认知复杂度: 44
- 🔄 `_init_prompt()` L492: 嵌套深度: 4
- 📏 `chat_debug_respond()` L857: 74 代码量
- 📏 `create_engine_with_defaults()` L1072: 221 代码量
- 📏 `build_context()` L701: 8 参数数量
- 📏 `chat()` L770: 8 参数数量
- 📏 `chat_stream()` L808: 8 参数数量
- 📏 `chat_debug()` L831: 6 参数数量
- 📏 `create_engine_with_defaults()` L1072: 12 参数数量
- 📋 `from_subapp()` L78: 重复模式: from_subapp, _init_memory
- 📋 `_init_database()` L162: 重复模式: _init_database, _handle_reminder_completion
- 📋 `_process_task_completion()` L194: 重复模式: _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L262: 重复模式: _handle_reasoner_completion, _register_context_plugins
- 📋 `_register_execution_plugins()` L633: 重复模式: _register_execution_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L43: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L194: 中等嵌套: 3
- 🏗️ `_init_memory()` L348: 中等嵌套: 3
- 🏗️ `_inject_system_skill_deps()` L445: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L478: 中等嵌套: 3
- 🏗️ `_init_prompt()` L492: 中等嵌套: 4
- 🏗️ `_dump_context_for_session()` L936: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1293 行
- 🏗️ L1: 导入过多: 87
- ❌ L214: 未处理的易出错调用
- ❌ L227: 未处理的易出错调用
- ❌ L241: 未处理的易出错调用
- ❌ L292: 未处理的易出错调用
- ❌ L747: 未处理的易出错调用
- ❌ L748: 未处理的易出错调用
- ❌ L749: 未处理的易出错调用
- ❌ L750: 未处理的易出错调用
- ❌ L751: 未处理的易出错调用
- ❌ L764: 未处理的易出错调用
- ❌ L1014: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L43: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L109: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L145: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L162: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L171: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L194: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L210: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L226: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L246: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L262: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 5.9, 最大: 40
- 认知复杂度: 平均: 8.8, 最大: 44
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 24.0 行, 最大: 221 行
- 文件长度: 1110 代码量 (1293 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.4% 重复 (5/48)
- 结构分析: 9 个结构问题
- 错误处理: 11/47 个错误被忽略 (23.4%)
- 注释比例: 2.7% (30/1110)
- 命名规范: 发现 32 个违规

### 5. memory/core.py

**糟糕指数: 43.56**

> 行数: 817 总计, 671 代码, 45 注释 | 函数: 28 | 类: 1

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 9, 📋 重复问题: 2, 🏗️ 结构问题: 6, ❌ 错误处理问题: 16, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L271-398 | 128 | 38 | 7 | 7 | ✓ |
| `assemble_context` | L215-265 | 51 | 14 | 3 | 4 | ✗ |
| `_format_detail_results` | L779-816 | 38 | 13 | 4 | 2 | ✗ |
| `_format_search_results` | L746-776 | 31 | 11 | 2 | 3 | ✗ |
| `reindex_embeddings` | L409-483 | 75 | 10 | 3 | 2 | ✓ |
| `_inject_unsynced_agent_chat` | L686-705 | 20 | 10 | 2 | 4 | ✓ |
| `handle_tags` | L592-619 | 28 | 9 | 2 | 4 | ✗ |
| `_handle_recall` | L621-646 | 26 | 9 | 3 | 4 | ✗ |
| `_format_timedelta` | L721-743 | 23 | 9 | 2 | 1 | ✗ |
| `rebuild_summaries` | L489-549 | 61 | 8 | 3 | 2 | ✓ |
| `_cosine_similarity` | L201-209 | 9 | 6 | 1 | 2 | ✗ |
| `summarize_turn` | L92-117 | 26 | 5 | 1 | 7 | ✓ |
| `_do_summarize` | L119-148 | 30 | 5 | 2 | 6 | ✗ |
| `_build_round_text` | L551-565 | 15 | 5 | 2 | 4 | ✓ |
| `_build_round_messages` | L567-586 | 20 | 5 | 2 | 4 | ✓ |
| `_embed_raw_round` | L171-190 | 20 | 4 | 2 | 6 | ✓ |
| `__init__` | L29-42 | 14 | 3 | 0 | 4 | ✗ |
| `_get_bound_agent` | L680-684 | 5 | 3 | 1 | 2 | ✓ |
| `_decrypt` | L83-86 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L652-662 | 11 | 2 | 1 | 4 | ✗ |
| `delete_memo` | L707-714 | 8 | 2 | 1 | 2 | ✗ |
| `_init_table` | L44-76 | 33 | 1 | 0 | 1 | ✗ |
| `_encrypt` | L80-81 | 2 | 1 | 0 | 3 | ✗ |
| `_get_exp_memories` | L150-165 | 16 | 1 | 0 | 2 | ✗ |
| `_pack_embedding` | L193-194 | 2 | 1 | 0 | 1 | ✗ |
| `_unpack_embedding` | L197-198 | 2 | 1 | 0 | 1 | ✗ |
| `get_detail` | L400-403 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L664-678 | 15 | 1 | 0 | 2 | ✗ |

**全部问题 (58)**

- 🔄 `assemble_context()` L215: 复杂度: 14
- 🔄 `search()` L271: 复杂度: 38
- 🔄 `_format_search_results()` L746: 复杂度: 11
- 🔄 `_format_detail_results()` L779: 复杂度: 13
- 🔄 `assemble_context()` L215: 认知复杂度: 20
- 🔄 `search()` L271: 认知复杂度: 52
- 🔄 `reindex_embeddings()` L409: 认知复杂度: 16
- 🔄 `rebuild_summaries()` L489: 认知复杂度: 14
- 🔄 `handle_tags()` L592: 认知复杂度: 13
- 🔄 `_handle_recall()` L621: 认知复杂度: 15
- 🔄 `_inject_unsynced_agent_chat()` L686: 认知复杂度: 14
- 🔄 `_format_timedelta()` L721: 认知复杂度: 13
- 🔄 `_format_search_results()` L746: 认知复杂度: 15
- 🔄 `_format_detail_results()` L779: 认知复杂度: 21
- 🔄 `search()` L271: 嵌套深度: 7
- 🔄 `_format_detail_results()` L779: 嵌套深度: 4
- 📏 `assemble_context()` L215: 51 代码量
- 📏 `search()` L271: 128 代码量
- 📏 `reindex_embeddings()` L409: 75 代码量
- 📏 `rebuild_summaries()` L489: 61 代码量
- 📏 `summarize_turn()` L92: 7 参数数量
- 📏 `_do_summarize()` L119: 6 参数数量
- 📏 `_embed_raw_round()` L171: 6 参数数量
- 📏 `search()` L271: 7 参数数量
- 📋 `_get_exp_memories()` L150: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L652: 重复模式: add_memo, delete_memo
- 🏗️ `assemble_context()` L215: 中等嵌套: 3
- 🏗️ `search()` L271: 嵌套过深: 7
- 🏗️ `reindex_embeddings()` L409: 中等嵌套: 3
- 🏗️ `rebuild_summaries()` L489: 中等嵌套: 3
- 🏗️ `_handle_recall()` L621: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L779: 中等嵌套: 4
- ❌ L46: 未处理的易出错调用
- ❌ L57: 未处理的易出错调用
- ❌ L61: 未处理的易出错调用
- ❌ L72: 未处理的易出错调用
- ❌ L76: 未处理的易出错调用
- ❌ L140: 未处理的易出错调用
- ❌ L182: 未处理的易出错调用
- ❌ L187: 未处理的易出错调用
- ❌ L470: 未处理的易出错调用
- ❌ L475: 未处理的易出错调用
- ❌ L536: 未处理的易出错调用
- ❌ L540: 未处理的易出错调用
- ❌ L661: 未处理的易出错调用
- ❌ L700: 未处理的易出错调用
- ❌ L713: 未处理的易出错调用
- ❌ L793: 未处理的易出错调用
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
- 循环复杂度: 平均: 6.4, 最大: 38
- 认知复杂度: 平均: 9.6, 最大: 52
- 嵌套深度: 平均: 1.6, 最大: 7
- 函数长度: 平均: 25.6 行, 最大: 128 行
- 文件长度: 671 代码量 (817 总计)
- 参数数量: 平均: 3.3, 最大: 7
- 代码重复: 7.1% 重复 (2/28)
- 结构分析: 6 个结构问题
- 错误处理: 16/38 个错误被忽略 (42.1%)
- 注释比例: 6.7% (45/671)
- 命名规范: 发现 19 个违规

### 6. plugins/builtin/models_plugin.py

**糟糕指数: 37.00**

> 行数: 251 总计, 217 代码, 4 注释 | 函数: 9 | 类: 1

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 2, 🏗️ 结构问题: 3, ❌ 错误处理问题: 2, 📝 注释问题: 1, 🏷️ 命名问题: 4

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `on_hook` | L56-146 | 91 | 24 | 6 | 3 | ✗ |
| `invoke` | L210-238 | 29 | 10 | 4 | 4 | ✗ |
| `_build_tools_schema` | L148-168 | 21 | 6 | 3 | 1 | ✗ |
| `set_skill_registry` | L47-50 | 4 | 2 | 0 | 2 | ✗ |
| `_create_chat` | L170-184 | 15 | 2 | 1 | 2 | ✗ |
| `_clean_reply` | L187-208 | 22 | 2 | 1 | 1 | ✗ |
| `__init__` | L23-45 | 23 | 1 | 0 | 10 | ✗ |
| `on_load` | L52-54 | 3 | 1 | 0 | 1 | ✗ |
| `describe_image` | L240-250 | 11 | 1 | 0 | 3 | ✗ |

**全部问题 (16)**

- 🔄 `on_hook()` L56: 复杂度: 24
- 🔄 `on_hook()` L56: 认知复杂度: 36
- 🔄 `invoke()` L210: 认知复杂度: 18
- 🔄 `on_hook()` L56: 嵌套深度: 6
- 🔄 `invoke()` L210: 嵌套深度: 4
- 📏 `on_hook()` L56: 91 代码量
- 📏 `__init__()` L23: 10 参数数量
- 🏗️ `on_hook()` L56: 嵌套过深: 6
- 🏗️ `_build_tools_schema()` L148: 中等嵌套: 3
- 🏗️ `invoke()` L210: 中等嵌套: 4
- ❌ L116: 未处理的易出错调用
- ❌ L133: 未处理的易出错调用
- 🏷️ `__init__()` L23: "__init__" - snake_case
- 🏷️ `_build_tools_schema()` L148: "_build_tools_schema" - snake_case
- 🏷️ `_create_chat()` L170: "_create_chat" - snake_case
- 🏷️ `_clean_reply()` L187: "_clean_reply" - snake_case

**详情**:
- 循环复杂度: 平均: 5.4, 最大: 24
- 认知复杂度: 平均: 8.8, 最大: 36
- 嵌套深度: 平均: 1.7, 最大: 6
- 函数长度: 平均: 24.3 行, 最大: 91 行
- 文件长度: 217 代码量 (251 总计)
- 参数数量: 平均: 3.0, 最大: 10
- 代码重复: 0.0% 重复 (0/9)
- 结构分析: 3 个结构问题
- 错误处理: 2/8 个错误被忽略 (25.0%)
- 注释比例: 1.8% (4/217)
- 命名规范: 发现 4 个违规

### 7. models/clients.py

**糟糕指数: 36.36**

> 行数: 1215 总计, 1011 代码, 22 注释 | 函数: 59 | 类: 6

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 11, 🏗️ 结构问题: 7, ❌ 错误处理问题: 5, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_and_append` | L159-251 | 93 | 20 | 3 | 3 | ✗ |
| `_call_llm` | L744-816 | 60 | 17 | 5 | 7 | ✓ |
| `_ocr_single` | L951-1014 | 57 | 13 | 5 | 3 | ✗ |
| `ask` | L1065-1129 | 65 | 13 | 1 | 6 | ✓ |
| `_call_embed_api` | L632-685 | 41 | 11 | 5 | 2 | ✓ |
| `describe_images` | L486-531 | 46 | 9 | 2 | 5 | ✓ |
| `classify_image` | L533-580 | 48 | 8 | 2 | 4 | ✓ |
| `__init__` | L896-922 | 27 | 8 | 1 | 5 | ✗ |
| `__init__` | L710-742 | 33 | 7 | 1 | 8 | ✗ |
| `summarize_dialog` | L844-877 | 34 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L33-41 | 9 | 6 | 1 | 1 | ✓ |
| `__init__` | L104-139 | 36 | 6 | 1 | 8 | ✗ |
| `__init__` | L290-339 | 50 | 6 | 1 | 8 | ✓ |
| `_do_call_chat_api` | L353-371 | 19 | 6 | 4 | 2 | ✓ |
| `_call_and_append` | L386-423 | 38 | 6 | 2 | 1 | ✗ |
| `describe_image` | L452-484 | 33 | 6 | 1 | 5 | ✓ |
| `classify_image` | L1161-1180 | 20 | 6 | 2 | 3 | ✓ |
| `_unload_lmstudio_model` | L66-87 | 22 | 5 | 2 | 2 | ✓ |
| `_do_request` | L766-778 | 13 | 5 | 2 | 0 | ✗ |
| `summarize_text` | L818-839 | 22 | 5 | 1 | 3 | ✓ |
| `__init__` | L1042-1053 | 12 | 5 | 1 | 5 | ✗ |
| `send_message` | L373-380 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L595-615 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L617-624 | 8 | 4 | 1 | 2 | ✓ |
| `ocr_batch` | L929-949 | 21 | 4 | 1 | 3 | ✓ |
| `_load_lmstudio_model` | L44-63 | 20 | 3 | 1 | 4 | ✓ |
| `send_message` | L141-146 | 6 | 3 | 1 | 4 | ✗ |
| `last_tool_calls` | L153-157 | 5 | 3 | 1 | 1 | ✗ |
| `_call_chat_api` | L346-351 | 6 | 3 | 2 | 2 | ✓ |
| `_do_request` | L637-649 | 13 | 3 | 1 | 0 | ✗ |
| `_do_request` | L971-977 | 7 | 3 | 1 | 0 | ✗ |
| `encode_image` | L1056-1063 | 8 | 3 | 1 | 2 | ✓ |
| `ask_raw` | L1131-1157 | 27 | 3 | 1 | 5 | ✓ |
| `ocr_md` | L1182-1196 | 15 | 3 | 1 | 3 | ✓ |
| `embed_batch` | L626-630 | 5 | 2 | 1 | 2 | ✓ |
| `ocr` | L924-927 | 4 | 2 | 0 | 3 | ✓ |
| `ocr_md_batch` | L1198-1211 | 14 | 2 | 1 | 3 | ✓ |
| `toggle_detail_chats` | L19-23 | 5 | 1 | 0 | 0 | ✓ |
| `toggle_detail_actions` | L26-30 | 5 | 1 | 0 | 0 | ✓ |
| `continue_conversation` | L148-150 | 3 | 1 | 0 | 3 | ✗ |
| `reset_conversation` | L253-256 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L258-264 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L266-273 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L275-278 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L280-281 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L341-342 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L382-384 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L425-428 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L430-436 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L438-445 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L447-450 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L582-583 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L687-688 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L690-691 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L841-842 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_loaded` | L1016-1017 | 2 | 1 | 0 | 1 | ✗ |
| `unload` | L1019-1021 | 3 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1023-1024 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1213-1214 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (48)**

- 🔄 `_call_and_append()` L159: 复杂度: 20
- 🔄 `_call_embed_api()` L632: 复杂度: 11
- 🔄 `_call_llm()` L744: 复杂度: 17
- 🔄 `_ocr_single()` L951: 复杂度: 13
- 🔄 `ask()` L1065: 复杂度: 13
- 🔄 `_call_and_append()` L159: 认知复杂度: 26
- 🔄 `_do_call_chat_api()` L353: 认知复杂度: 14
- 🔄 `describe_images()` L486: 认知复杂度: 13
- 🔄 `_call_embed_api()` L632: 认知复杂度: 21
- 🔄 `_call_llm()` L744: 认知复杂度: 27
- 🔄 `_ocr_single()` L951: 认知复杂度: 23
- 🔄 `ask()` L1065: 认知复杂度: 15
- 🔄 `_do_call_chat_api()` L353: 嵌套深度: 4
- 🔄 `_call_embed_api()` L632: 嵌套深度: 5
- 🔄 `_call_llm()` L744: 嵌套深度: 5
- 🔄 `_ocr_single()` L951: 嵌套深度: 5
- 📏 `_call_and_append()` L159: 93 代码量
- 📏 `_call_llm()` L744: 60 代码量
- 📏 `_ocr_single()` L951: 57 代码量
- 📏 `ask()` L1065: 65 代码量
- 📏 `__init__()` L104: 8 参数数量
- 📏 `__init__()` L290: 8 参数数量
- 📏 `__init__()` L595: 6 参数数量
- 📏 `__init__()` L710: 8 参数数量
- 📏 `_call_llm()` L744: 7 参数数量
- 📏 `ask()` L1065: 6 参数数量
- 🏗️ `_call_and_append()` L159: 中等嵌套: 3
- 🏗️ `_do_call_chat_api()` L353: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L632: 嵌套过深: 5
- 🏗️ `_call_llm()` L744: 嵌套过深: 5
- 🏗️ `_ocr_single()` L951: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1215 行
- 🏗️ L1: 函数过多: 59
- ❌ L59: 未处理的易出错调用
- ❌ L155: 未处理的易出错调用
- ❌ L209: 未处理的易出错调用
- ❌ L212: 未处理的易出错调用
- ❌ L1061: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L33: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L44: "_load_lmstudio_model" - snake_case
- 🏷️ `_unload_lmstudio_model()` L66: "_unload_lmstudio_model" - snake_case
- 🏷️ `__init__()` L104: "__init__" - snake_case
- 🏷️ `_call_and_append()` L159: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L280: "__repr__" - snake_case
- 🏷️ `__init__()` L290: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L341: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L346: "_call_chat_api" - snake_case
- 🏷️ `_do_call_chat_api()` L353: "_do_call_chat_api" - snake_case

**详情**:
- 循环复杂度: 平均: 4.2, 最大: 20
- 认知复杂度: 平均: 6.2, 最大: 27
- 嵌套深度: 平均: 1.0, 最大: 5
- 函数长度: 平均: 17.8 行, 最大: 93 行
- 文件长度: 1011 代码量 (1215 总计)
- 参数数量: 平均: 2.6, 最大: 8
- 代码重复: 3.4% 重复 (2/59)
- 结构分析: 7 个结构问题
- 错误处理: 5/36 个错误被忽略 (13.9%)
- 注释比例: 2.2% (22/1011)
- 命名规范: 发现 28 个违规

### 8. document/doc_processor.py

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

### 9. psychoscope/static/js/app.js

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

### 10. onboarding.py

**糟糕指数: 32.59**

> 行数: 650 总计, 511 代码, 16 注释 | 函数: 23 | 类: 0

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 4, 🏗️ 结构问题: 7, ❌ 错误处理问题: 5, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_ai_guided_configure` | L437-597 | 161 | 25 | 4 | 2 | ✓ |
| `_get_api_key` | L380-431 | 52 | 13 | 4 | 0 | ✓ |
| `_check_pip_packages` | L173-200 | 28 | 11 | 3 | 0 | ✗ |
| `_env_write` | L33-55 | 23 | 10 | 5 | 2 | ✗ |
| `_load_existing_env` | L19-30 | 12 | 7 | 4 | 0 | ✗ |
| `_check_third_party` | L203-255 | 53 | 7 | 3 | 0 | ✗ |
| `_chat_send_with_retry` | L109-132 | 24 | 6 | 4 | 3 | ✓ |
| `_install_missing_packages` | L277-300 | 24 | 6 | 2 | 1 | ✓ |
| `_get_current_config` | L313-323 | 11 | 6 | 2 | 0 | ✓ |
| `_get_character_cards_info` | L326-337 | 12 | 5 | 1 | 0 | ✓ |
| `run` | L603-644 | 42 | 4 | 2 | 0 | ✓ |
| `_is_configured` | L63-68 | 6 | 3 | 1 | 0 | ✗ |
| `_run_shell` | L71-86 | 16 | 3 | 1 | 2 | ✗ |
| `_safe_input` | L145-151 | 7 | 3 | 1 | 1 | ✗ |
| `_run_python` | L89-101 | 13 | 2 | 2 | 2 | ✗ |
| `_render_markdown` | L135-142 | 8 | 2 | 1 | 1 | ✗ |
| `_check_conda` | L166-170 | 5 | 2 | 1 | 0 | ✗ |
| `_get_env_config_info` | L306-310 | 5 | 2 | 1 | 0 | ✓ |
| `_env_read` | L58-60 | 3 | 1 | 0 | 1 | ✗ |
| `_create_chat` | L104-106 | 3 | 1 | 0 | 1 | ✗ |
| `_check_python` | L157-163 | 7 | 1 | 0 | 0 | ✗ |
| `_collect_environment_info` | L258-274 | 17 | 1 | 0 | 0 | ✓ |
| `_create_character_card` | L343-374 | 32 | 1 | 0 | 3 | ✓ |

**全部问题 (40)**

- 🔄 `_check_pip_packages()` L173: 复杂度: 11
- 🔄 `_get_api_key()` L380: 复杂度: 13
- 🔄 `_ai_guided_configure()` L437: 复杂度: 25
- 🔄 `_load_existing_env()` L19: 认知复杂度: 15
- 🔄 `_env_write()` L33: 认知复杂度: 20
- 🔄 `_chat_send_with_retry()` L109: 认知复杂度: 14
- 🔄 `_check_pip_packages()` L173: 认知复杂度: 17
- 🔄 `_check_third_party()` L203: 认知复杂度: 13
- 🔄 `_get_api_key()` L380: 认知复杂度: 21
- 🔄 `_ai_guided_configure()` L437: 认知复杂度: 33
- 🔄 `_load_existing_env()` L19: 嵌套深度: 4
- 🔄 `_env_write()` L33: 嵌套深度: 5
- 🔄 `_chat_send_with_retry()` L109: 嵌套深度: 4
- 🔄 `_get_api_key()` L380: 嵌套深度: 4
- 🔄 `_ai_guided_configure()` L437: 嵌套深度: 4
- 📏 `_check_third_party()` L203: 53 代码量
- 📏 `_get_api_key()` L380: 52 代码量
- 📏 `_ai_guided_configure()` L437: 161 代码量
- 🏗️ `_load_existing_env()` L19: 中等嵌套: 4
- 🏗️ `_env_write()` L33: 嵌套过深: 5
- 🏗️ `_chat_send_with_retry()` L109: 中等嵌套: 4
- 🏗️ `_check_pip_packages()` L173: 中等嵌套: 3
- 🏗️ `_check_third_party()` L203: 中等嵌套: 3
- 🏗️ `_get_api_key()` L380: 中等嵌套: 4
- 🏗️ `_ai_guided_configure()` L437: 中等嵌套: 4
- ❌ L93: 未处理的易出错调用
- ❌ L94: 未处理的易出错调用
- ❌ L280: 未处理的易出错调用
- ❌ L562: 未处理的易出错调用
- ❌ L563: 未处理的易出错调用
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
- 循环复杂度: 平均: 5.3, 最大: 25
- 认知复杂度: 平均: 9.0, 最大: 33
- 嵌套深度: 平均: 1.8, 最大: 5
- 函数长度: 平均: 24.5 行, 最大: 161 行
- 文件长度: 511 代码量 (650 总计)
- 参数数量: 平均: 0.8, 最大: 3
- 代码重复: 0.0% 重复 (0/23)
- 结构分析: 7 个结构问题
- 错误处理: 5/14 个错误被忽略 (35.7%)
- 注释比例: 3.1% (16/511)
- 命名规范: 发现 22 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `process_stream` | plugins/pipeline.py | 75 | 7 | 356 |
| `main` | psychoscope/minimal.py | 49 | 8 | 207 |
| `create_application` | boot.py | 42 | 4 | 378 |
| `create_engine_with_defaults` | engine.py | 40 | 2 | 221 |
| `_poll_pending_tasks` | plugins/pipeline.py | 38 | 6 | 123 |
| `search` | memory/core.py | 38 | 7 | 128 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `_cmd_agent` | main.py | 34 | 3 | 145 |
| `process_scan` | document/doc_processor.py | 32 | 5 | 147 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*