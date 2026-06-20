# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-81%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **80.91/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 161 |
| 已跳过 | 372 |
| 耗时 | 894ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 26670 |
| 总注释行数 | 1331 |
| 整体注释比例 | 5.0% |
| 平均文件大小 | 207 行 |
| 最大文件 | `main.py` (2017) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 158 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 9.09% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 12.61% | 0.0% | 67.0% | 8.0% | ✓✓ |
| 嵌套深度 | 3.15% | 0.0% | 55.0% | 0.0% | ✓✓ |
| 函数长度 | 5.90% | 0.0% | 50.5% | 0.0% | ✓✓ |
| 文件长度 | 2.66% | 0.0% | 89.3% | 0.0% | ✓✓ |
| 参数数量 | 13.11% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 3.76% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.53% | 0.0% | 74.5% | 0.0% | ✓✓ |
| 错误处理 | 33.84% | 0.0% | 98.8% | 5.4% | ✓ |
| 注释比例 | 35.87% | 0.0% | 100.0% | 30.7% | ○ |
| 命名规范 | 26.56% | 0.0% | 94.7% | 21.1% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. main.py

**糟糕指数: 46.96**

> 行数: 2017 总计, 1671 代码, 30 注释 | 函数: 66 | 类: 1

**问题**: 🔄 复杂度问题: 31, ⚠️ 其他问题: 26, 🏗️ 结构问题: 11, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_reminder` | L590-718 | 129 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L963-1103 | 141 | 31 | 3 | 2 | ✓ |
| `_cmd_plan` | L721-783 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1106-1234 | 121 | 21 | 3 | 2 | ✓ |
| `main` | L1888-2012 | 115 | 19 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L1309-1393 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L1781-1847 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_export` | L424-513 | 90 | 13 | 2 | 2 | ✓ |
| `_cmd_memory` | L886-917 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L516-587 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L830-883 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1530-1569 | 40 | 11 | 2 | 2 | ✓ |
| `_env_write` | L85-112 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L1671-1696 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L195-233 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L236-272 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_memory_reindex` | L920-960 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1572-1606 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L1750-1778 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L313-345 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1237-1270 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1273-1306 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1396-1422 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1443-1462 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L1850-1878 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L47-57 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L298-310 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L348-367 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L370-397 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L947-956 | 10 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1637-1668 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L1699-1725 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L60-74 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L287-295 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1222-1229 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L1969-1978 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L77-82 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L146-156 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L159-164 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L178-192 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L400-416 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1619-1630 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L1735-1747 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L115-118 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L121-123 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L126-139 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1474-1475 | 2 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1609-1633 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L1881-1885 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L133-134 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L419-421 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L786-827 | 42 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1425-1440 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1465-1466 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1468-1469 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1471-1472 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1477-1478 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1480-1481 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1483-1484 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1486-1487 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1489-1490 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1492-1493 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1496-1497 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1500-1501 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L1504-1505 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L1508-1509 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (89)**

- 🔄 `_cmd_export()` L424: 复杂度: 13
- 🔄 `_cmd_import()` L516: 复杂度: 11
- 🔄 `_cmd_reminder()` L590: 复杂度: 31
- 🔄 `_cmd_plan()` L721: 复杂度: 21
- 🔄 `_cmd_plugin()` L830: 复杂度: 11
- 🔄 `_cmd_memory()` L886: 复杂度: 12
- 🔄 `_cmd_memory_query()` L963: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1106: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1309: 复杂度: 17
- 🔄 `_cmd_persona()` L1530: 复杂度: 11
- 🔄 `_cmd_hibernate_check()` L1781: 复杂度: 14
- 🔄 `main()` L1888: 复杂度: 19
- 🔄 `_env_write()` L85: 认知复杂度: 20
- 🔄 `_cmd_users()` L195: 认知复杂度: 13
- 🔄 `_cmd_status()` L236: 认知复杂度: 13
- 🔄 `_cmd_export()` L424: 认知复杂度: 17
- 🔄 `_cmd_import()` L516: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L590: 认知复杂度: 39
- 🔄 `_cmd_plan()` L721: 认知复杂度: 25
- 🔄 `_cmd_plugin()` L830: 认知复杂度: 15
- 🔄 `_cmd_memory()` L886: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L963: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1106: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1309: 认知复杂度: 21
- 🔄 `_cmd_persona()` L1530: 认知复杂度: 15
- 🔄 `_persona_status()` L1572: 认知复杂度: 14
- 🔄 `_persona_materials()` L1671: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L1781: 认知复杂度: 20
- 🔄 `main()` L1888: 认知复杂度: 25
- 🔄 `_env_write()` L85: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L590: 嵌套深度: 4
- 📏 `_cmd_export()` L424: 90 代码量
- 📏 `_cmd_import()` L516: 72 代码量
- 📏 `_cmd_reminder()` L590: 129 代码量
- 📏 `_cmd_plan()` L721: 63 代码量
- 📏 `_cmd_plugin()` L830: 54 代码量
- 📏 `_cmd_memory_query()` L963: 141 代码量
- 📏 `_cmd_memory_rebuild()` L1106: 121 代码量
- 📏 `_cmd_memory_list()` L1309: 85 代码量
- 📏 `_cmd_hibernate_check()` L1781: 67 代码量
- 📏 `main()` L1888: 115 代码量
- 📏 `_execute_command()` L1443: 9 参数数量
- 📏 `_h_newbind()` L1465: 7 参数数量
- 📏 `_h_users()` L1468: 7 参数数量
- 📏 `_h_status()` L1471: 7 参数数量
- 📏 `_h_plugin()` L1474: 7 参数数量
- 📏 `_h_memory()` L1477: 7 参数数量
- 📏 `_h_prompt()` L1480: 7 参数数量
- 📏 `_h_config()` L1483: 7 参数数量
- 📏 `_h_listconfig()` L1486: 7 参数数量
- 📏 `_h_persona()` L1489: 7 参数数量
- 📏 `_h_help()` L1492: 7 参数数量
- 📏 `_h_export()` L1496: 7 参数数量
- 📏 `_h_import()` L1500: 7 参数数量
- 📏 `_h_reminder()` L1504: 7 参数数量
- 📏 `_h_plan()` L1508: 7 参数数量
- 🏗️ `_env_backup_rotate()` L47: 中等嵌套: 3
- 🏗️ `_env_write()` L85: 嵌套过深: 5
- 🏗️ `_cmd_reminder()` L590: 中等嵌套: 4
- 🏗️ `_cmd_memory_query()` L963: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1106: 中等嵌套: 3
- 🏗️ `_persona_status()` L1572: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L1781: 中等嵌套: 3
- 🏗️ `main()` L1888: 中等嵌套: 3
- 🏗️ L1: 文件过大: 2017 行
- 🏗️ L1: 函数过多: 66
- 🏗️ L1: 导入过多: 45
- ❌ L221: 未处理的易出错调用
- ❌ L229: 未处理的易出错调用
- ❌ L558: 未处理的易出错调用
- ❌ L564: 未处理的易出错调用
- ❌ L578: 未处理的易出错调用
- ❌ L584: 未处理的易出错调用
- ❌ L878: 未处理的易出错调用
- ❌ L1390: 未处理的易出错调用
- ❌ L1604: 未处理的易出错调用
- ❌ L1659: 未处理的易出错调用
- ❌ L1660: 未处理的易出错调用
- ❌ L1661: 未处理的易出错调用
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
- 认知复杂度: 平均: 9.0, 最大: 39
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 27.3 行, 最大: 141 行
- 文件长度: 1671 代码量 (2017 总计)
- 参数数量: 平均: 2.7, 最大: 9
- 代码重复: 1.5% 重复 (1/66)
- 结构分析: 11 个结构问题
- 错误处理: 12/52 个错误被忽略 (23.1%)
- 注释比例: 1.8% (30/1671)
- 命名规范: 发现 63 个违规

### 2. memory/core.py

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

### 3. engine.py

**糟糕指数: 43.56**

> 行数: 1037 总计, 894 代码, 19 注释 | 函数: 38 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 📋 重复问题: 2, 🏗️ 结构问题: 7, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L800-1036 | 237 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L424-464 | 41 | 16 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L554-597 | 44 | 12 | 2 | 1 | ✗ |
| `build_context` | L635-668 | 34 | 10 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L532-552 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L599-622 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L670-706 | 37 | 9 | 2 | 8 | ✓ |
| `_register_context_plugins` | L511-530 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L708-727 | 20 | 8 | 1 | 8 | ✓ |
| `_generate_result_message` | L255-292 | 38 | 7 | 2 | 3 | ✗ |
| `run_scheduled` | L737-774 | 31 | 7 | 2 | 1 | ✓ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_handle_engine_action_completion` | L214-228 | 15 | 6 | 2 | 4 | ✗ |
| `_retry_engine_action` | L294-315 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L317-345 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L347-372 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L392-408 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L410-422 | 13 | 6 | 3 | 1 | ✓ |
| `get_info` | L778-786 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L186-200 | 15 | 5 | 3 | 1 | ✗ |
| `_dispatch_task_completion` | L202-212 | 11 | 5 | 2 | 3 | ✗ |
| `from_subapp` | L74-90 | 17 | 3 | 0 | 1 | ✗ |
| `__init__` | L104-135 | 32 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L163-182 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L241-253 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L374-390 | 17 | 3 | 2 | 1 | ✗ |
| `_init_plugins` | L466-476 | 11 | 3 | 0 | 1 | ✗ |
| `_plugin_enabled` | L478-483 | 6 | 3 | 1 | 2 | ✗ |
| `_init_database` | L156-161 | 6 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L230-239 | 10 | 2 | 1 | 3 | ✗ |
| `_register_filter_plugins` | L485-492 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L494-509 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L729-730 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L732-733 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L749-755 | 7 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L139-154 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L624-631 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L791-797 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (38)**

- 🔄 `_init_prompt()` L424: 复杂度: 16
- 🔄 `_register_execution_plugins()` L554: 复杂度: 12
- 🔄 `create_engine_with_defaults()` L800: 复杂度: 43
- 🔄 `_init_prompt()` L424: 认知复杂度: 24
- 🔄 `_register_personality_plugins()` L532: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L554: 认知复杂度: 16
- 🔄 `_register_output_plugins()` L599: 认知复杂度: 13
- 🔄 `chat()` L670: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L800: 认知复杂度: 47
- 🔄 `_init_prompt()` L424: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L800: 237 代码量
- 📏 `build_context()` L635: 8 参数数量
- 📏 `chat()` L670: 8 参数数量
- 📏 `chat_stream()` L708: 8 参数数量
- 📏 `create_engine_with_defaults()` L800: 12 参数数量
- 📋 `_init_database()` L156: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L241: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L186: 中等嵌套: 3
- 🏗️ `_init_memory()` L317: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L410: 中等嵌套: 3
- 🏗️ `_init_prompt()` L424: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1037 行
- 🏗️ L1: 导入过多: 82
- ❌ L215: 未处理的易出错调用
- ❌ L225: 未处理的易出错调用
- ❌ L271: 未处理的易出错调用
- ❌ L753: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L42: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L104: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L139: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L156: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L163: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L186: "_process_task_completion" - snake_case
- 🏷️ `_dispatch_task_completion()` L202: "_dispatch_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L214: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L230: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L241: "_handle_reasoner_completion" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 43
- 认知复杂度: 平均: 8.9, 最大: 47
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 23.9 行, 最大: 237 行
- 文件长度: 894 代码量 (1037 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.5% 重复 (4/38)
- 结构分析: 7 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.1% (19/894)
- 命名规范: 发现 27 个违规

### 4. plugins/pipeline.py

**糟糕指数: 38.30**

> 行数: 621 总计, 502 代码, 25 注释 | 函数: 15 | 类: 1

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 5, 🏗️ 结构问题: 6, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L418-620 | 203 | 40 | 5 | 3 | ✓ |
| `_poll_pending_tasks` | L377-406 | 30 | 18 | 5 | 4 | ✗ |
| `process` | L151-217 | 67 | 13 | 3 | 2 | ✓ |
| `_synthesize_lines_sync` | L291-344 | 54 | 12 | 3 | 2 | ✓ |
| `_invoke` | L27-56 | 30 | 7 | 2 | 0 | ✗ |
| `_dispatch_pre_process` | L241-278 | 38 | 7 | 1 | 2 | ✓ |
| `_run_all_plugins` | L355-375 | 21 | 7 | 2 | 5 | ✗ |
| `_task_completion_llm_reply` | L22-82 | 31 | 6 | 2 | 5 | ✓ |
| `_extract_narrations` | L85-100 | 16 | 4 | 3 | 1 | ✓ |
| `_assemble_prompt` | L219-237 | 19 | 4 | 1 | 2 | ✓ |
| `_bridge_progress` | L347-353 | 7 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L103-108 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L111-118 | 8 | 2 | 1 | 1 | ✗ |
| `__init__` | L135-147 | 13 | 1 | 0 | 6 | ✗ |
| `_synthesize_lines` | L282-289 | 8 | 1 | 0 | 2 | ✓ |

**全部问题 (42)**

- 🔄 `process()` L151: 复杂度: 13
- 🔄 `_synthesize_lines_sync()` L291: 复杂度: 12
- 🔄 `_poll_pending_tasks()` L377: 复杂度: 18
- 🔄 `process_stream()` L418: 复杂度: 40
- 🔄 `process()` L151: 认知复杂度: 19
- 🔄 `_synthesize_lines_sync()` L291: 认知复杂度: 18
- 🔄 `_poll_pending_tasks()` L377: 认知复杂度: 28
- 🔄 `process_stream()` L418: 认知复杂度: 50
- 🔄 `_poll_pending_tasks()` L377: 嵌套深度: 5
- 🔄 `process_stream()` L418: 嵌套深度: 5
- 📏 `process()` L151: 67 代码量
- 📏 `_synthesize_lines_sync()` L291: 54 代码量
- 📏 `process_stream()` L418: 203 代码量
- 📏 `__init__()` L135: 6 参数数量
- 🏗️ `_extract_narrations()` L85: 中等嵌套: 3
- 🏗️ `process()` L151: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L291: 中等嵌套: 3
- 🏗️ `_poll_pending_tasks()` L377: 嵌套过深: 5
- 🏗️ `process_stream()` L418: 嵌套过深: 5
- 🏗️ L1: 导入过多: 21
- ❌ L78: 未处理的易出错调用
- ❌ L207: 未处理的易出错调用
- ❌ L353: 未处理的易出错调用
- ❌ L359: 未处理的易出错调用
- ❌ L374: 未处理的易出错调用
- ❌ L375: 未处理的易出错调用
- ❌ L380: 未处理的易出错调用
- ❌ L402: 未处理的易出错调用
- ❌ L535: 未处理的易出错调用
- ❌ L549: 未处理的易出错调用
- ❌ L579: 未处理的易出错调用
- ❌ L615: 未处理的易出错调用
- 🏷️ `_task_completion_llm_reply()` L22: "_task_completion_llm_reply" - snake_case
- 🏷️ `_invoke()` L27: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L85: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L103: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L111: "_desc_task" - snake_case
- 🏷️ `__init__()` L135: "__init__" - snake_case
- 🏷️ `_assemble_prompt()` L219: "_assemble_prompt" - snake_case
- 🏷️ `_dispatch_pre_process()` L241: "_dispatch_pre_process" - snake_case
- 🏷️ `_synthesize_lines()` L282: "_synthesize_lines" - snake_case
- 🏷️ `_synthesize_lines_sync()` L291: "_synthesize_lines_sync" - snake_case

**详情**:
- 循环复杂度: 平均: 8.5, 最大: 40
- 认知复杂度: 平均: 12.6, 最大: 50
- 嵌套深度: 平均: 2.1, 最大: 5
- 函数长度: 平均: 36.7 行, 最大: 203 行
- 文件长度: 502 代码量 (621 总计)
- 参数数量: 平均: 2.5, 最大: 6
- 代码重复: 0.0% 重复 (0/15)
- 结构分析: 6 个结构问题
- 错误处理: 12/33 个错误被忽略 (36.4%)
- 注释比例: 5.0% (25/502)
- 命名规范: 发现 13 个违规

### 5. psychoscope/minimal.py

**糟糕指数: 37.66**

> 行数: 902 总计, 773 代码, 10 注释 | 函数: 40 | 类: 4

**问题**: 🔄 复杂度问题: 19, ⚠️ 其他问题: 3, 🏗️ 结构问题: 12, ❌ 错误处理问题: 11, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L728-899 | 164 | 36 | 6 | 0 | ✗ |
| `authenticate` | L195-276 | 82 | 14 | 2 | 3 | ✗ |
| `_handle_sse_stream` | L354-386 | 33 | 11 | 3 | 3 | ✗ |
| `_loop` | L454-483 | 30 | 10 | 5 | 1 | ✗ |
| `stop_and_send` | L549-581 | 33 | 10 | 2 | 1 | ✗ |
| `_tts_worker` | L171-193 | 23 | 9 | 3 | 1 | ✗ |
| `_capture_loop` | L583-613 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L639-665 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L125-142 | 18 | 8 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L71-84 | 14 | 6 | 5 | 0 | ✓ |
| `send_audio` | L314-352 | 39 | 6 | 2 | 2 | ✗ |
| `_trigger` | L485-508 | 24 | 6 | 4 | 2 | ✓ |
| `_verify_api_key` | L278-295 | 18 | 5 | 3 | 1 | ✗ |
| `_sync` | L408-434 | 27 | 5 | 3 | 1 | ✓ |
| `_play_beep` | L98-112 | 15 | 4 | 1 | 2 | ✓ |
| `__init__` | L156-169 | 14 | 4 | 1 | 3 | ✗ |
| `start` | L527-547 | 21 | 4 | 1 | 1 | ✗ |
| `print_header` | L667-691 | 25 | 4 | 1 | 3 | ✗ |
| `load_config` | L144-150 | 7 | 3 | 2 | 0 | ✗ |
| `_load_local` | L436-442 | 7 | 3 | 2 | 1 | ✗ |
| `print_personality` | L693-718 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L46-66 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L115-123 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L297-300 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L397-403 | 7 | 2 | 1 | 1 | ✗ |
| `_save_local` | L444-452 | 9 | 2 | 1 | 2 | ✗ |
| `start` | L621-626 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L628-631 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L633-637 | 5 | 2 | 1 | 2 | ✗ |
| `toggle_standby` | L720-726 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L786-793 | 8 | 2 | 1 | 2 | ✗ |
| `save_config` | L152-153 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L302-304 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L306-308 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L310-312 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L392-395 | 4 | 1 | 0 | 2 | ✗ |
| `stop` | L405-406 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L512-521 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L524-525 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L616-619 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (54)**

- 🔄 `authenticate()` L195: 复杂度: 14
- 🔄 `_handle_sse_stream()` L354: 复杂度: 11
- 🔄 `main()` L728: 复杂度: 36
- 🔄 `_detect_tts_sample_rate()` L71: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L125: 认知复杂度: 14
- 🔄 `_tts_worker()` L171: 认知复杂度: 15
- 🔄 `authenticate()` L195: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L354: 认知复杂度: 17
- 🔄 `_loop()` L454: 认知复杂度: 20
- 🔄 `_trigger()` L485: 认知复杂度: 14
- 🔄 `stop_and_send()` L549: 认知复杂度: 14
- 🔄 `_capture_loop()` L583: 认知复杂度: 15
- 🔄 `_loop()` L639: 认知复杂度: 19
- 🔄 `main()` L728: 认知复杂度: 48
- 🔄 `_detect_tts_sample_rate()` L71: 嵌套深度: 5
- 🔄 `_loop()` L454: 嵌套深度: 5
- 🔄 `_trigger()` L485: 嵌套深度: 4
- 🔄 `_loop()` L639: 嵌套深度: 5
- 🔄 `main()` L728: 嵌套深度: 6
- 📏 `authenticate()` L195: 82 代码量
- 📏 `main()` L728: 164 代码量
- 🏗️ `_detect_tts_sample_rate()` L71: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L125: 中等嵌套: 3
- 🏗️ `_tts_worker()` L171: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L278: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L354: 中等嵌套: 3
- 🏗️ `_sync()` L408: 中等嵌套: 3
- 🏗️ `_loop()` L454: 嵌套过深: 5
- 🏗️ `_trigger()` L485: 中等嵌套: 4
- 🏗️ `_capture_loop()` L583: 中等嵌套: 3
- 🏗️ `_loop()` L639: 嵌套过深: 5
- 🏗️ `main()` L728: 嵌套过深: 6
- 🏗️ L1: 导入过多: 25
- ❌ L76: 未处理的易出错调用
- ❌ L118: 未处理的易出错调用
- ❌ L338: 未处理的易出错调用
- ❌ L430: 未处理的易出错调用
- ❌ L498: 未处理的易出错调用
- ❌ L503: 未处理的易出错调用
- ❌ L506: 未处理的易出错调用
- ❌ L567: 未处理的易出错调用
- ❌ L652: 未处理的易出错调用
- ❌ L661: 未处理的易出错调用
- ❌ L714: 未处理的易出错调用
- 🏷️ `_detect_tts_sample_rate()` L71: "_detect_tts_sample_rate" - snake_case
- 🏷️ `_play_beep()` L98: "_play_beep" - snake_case
- 🏷️ `__init__()` L156: "__init__" - snake_case
- 🏷️ `_tts_worker()` L171: "_tts_worker" - snake_case
- 🏷️ `_verify_api_key()` L278: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L297: "_headers" - snake_case
- 🏷️ `_http_get()` L302: "_http_get" - snake_case
- 🏷️ `_http_post()` L306: "_http_post" - snake_case
- 🏷️ `_http_post_stream()` L310: "_http_post_stream" - snake_case
- 🏷️ `_handle_sse_stream()` L354: "_handle_sse_stream" - snake_case

**详情**:
- 循环复杂度: 平均: 5.0, 最大: 36
- 认知复杂度: 平均: 8.4, 最大: 48
- 嵌套深度: 平均: 1.7, 最大: 6
- 函数长度: 平均: 19.8 行, 最大: 164 行
- 文件长度: 773 代码量 (902 总计)
- 参数数量: 平均: 1.4, 最大: 3
- 代码重复: 5.0% 重复 (2/40)
- 结构分析: 12 个结构问题
- 错误处理: 11/70 个错误被忽略 (15.7%)
- 注释比例: 1.3% (10/773)
- 命名规范: 发现 20 个违规

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

**糟糕指数: 30.16**

> 行数: 508 总计, 433 代码, 22 注释 | 函数: 12 | 类: 0

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 2, 📋 重复问题: 1, 🏗️ 结构问题: 3, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 8

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_application` | L265-507 | 243 | 31 | 4 | 0 | ✓ |
| `_synthesize_tts_lines` | L124-146 | 23 | 10 | 2 | 1 | ✗ |
| `process_task_completion` | L173-190 | 18 | 8 | 3 | 0 | ✗ |
| `_handle_action_completion` | L214-239 | 26 | 8 | 2 | 3 | ✗ |
| `_convert_audio_to_wav` | L105-121 | 17 | 5 | 2 | 1 | ✗ |
| `_process_image_input` | L77-92 | 16 | 4 | 1 | 2 | ✗ |
| `create_chat_client` | L63-74 | 12 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L204-211 | 8 | 3 | 1 | 2 | ✗ |
| `_save_debug_audio` | L95-102 | 8 | 2 | 1 | 1 | ✗ |
| `setup_logging` | L149-170 | 22 | 2 | 1 | 1 | ✗ |
| `_handle_reminder_completion` | L193-201 | 9 | 2 | 1 | 2 | ✗ |
| `_t` | L249-260 | 12 | 2 | 1 | 1 | ✗ |

**全部问题 (25)**

- 🔄 `create_application()` L265: 复杂度: 31
- 🔄 `_synthesize_tts_lines()` L124: 认知复杂度: 14
- 🔄 `process_task_completion()` L173: 认知复杂度: 14
- 🔄 `create_application()` L265: 认知复杂度: 39
- 🔄 `create_application()` L265: 嵌套深度: 4
- 📏 `create_application()` L265: 243 代码量
- 📋 `_save_debug_audio()` L95: 重复模式: _save_debug_audio, _handle_reminder_completion
- 🏗️ `process_task_completion()` L173: 中等嵌套: 3
- 🏗️ `create_application()` L265: 中等嵌套: 4
- 🏗️ L1: 导入过多: 42
- ❌ L100: 未处理的易出错调用
- ❌ L101: 未处理的易出错调用
- ❌ L142: 未处理的易出错调用
- ❌ L308: 未处理的易出错调用
- ❌ L320: 未处理的易出错调用
- ❌ L351: 未处理的易出错调用
- ❌ L485: 未处理的易出错调用
- 🏷️ `_process_image_input()` L77: "_process_image_input" - snake_case
- 🏷️ `_save_debug_audio()` L95: "_save_debug_audio" - snake_case
- 🏷️ `_convert_audio_to_wav()` L105: "_convert_audio_to_wav" - snake_case
- 🏷️ `_synthesize_tts_lines()` L124: "_synthesize_tts_lines" - snake_case
- 🏷️ `_handle_reminder_completion()` L193: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L204: "_handle_reasoner_completion" - snake_case
- 🏷️ `_handle_action_completion()` L214: "_handle_action_completion" - snake_case
- 🏷️ `_t()` L249: "_t" - snake_case

**详情**:
- 循环复杂度: 平均: 6.7, 最大: 31
- 认知复杂度: 平均: 10.0, 最大: 39
- 嵌套深度: 平均: 1.7, 最大: 4
- 函数长度: 平均: 34.5 行, 最大: 243 行
- 文件长度: 433 代码量 (508 总计)
- 参数数量: 平均: 1.3, 最大: 3
- 代码重复: 8.3% 重复 (1/12)
- 结构分析: 3 个结构问题
- 错误处理: 7/32 个错误被忽略 (21.9%)
- 注释比例: 5.1% (22/433)
- 命名规范: 发现 8 个违规

### 9. chatdbmgr.py

**糟糕指数: 28.69**

> 行数: 715 总计, 634 代码, 24 注释 | 函数: 28 | 类: 1

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 6, 📋 重复问题: 3, 🏗️ 结构问题: 5, ❌ 错误处理问题: 59, 📝 注释问题: 1, 🏷️ 命名问题: 6

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `append_messages` | L638-689 | 52 | 9 | 3 | 7 | ✓ |
| `_tokenize` | L17-30 | 14 | 7 | 4 | 1 | ✓ |
| `get_messages_by_rounds` | L430-465 | 36 | 6 | 3 | 4 | ✓ |
| `save_chat_history` | L512-547 | 36 | 6 | 3 | 4 | ✓ |
| `_init_db` | L111-275 | 165 | 5 | 4 | 1 | ✓ |
| `get_impressions` | L330-348 | 19 | 4 | 2 | 5 | ✗ |
| `get_next_round_index` | L483-495 | 13 | 4 | 1 | 2 | ✓ |
| `update_impression` | L298-317 | 20 | 3 | 1 | 2 | ✗ |
| `count_impressions` | L350-359 | 10 | 3 | 1 | 2 | ✗ |
| `get_last_message_ids` | L467-481 | 15 | 3 | 2 | 3 | ✓ |
| `get_chat_history` | L549-569 | 21 | 3 | 2 | 3 | ✓ |
| `replace_last_assistant` | L600-621 | 22 | 3 | 2 | 4 | ✓ |
| `load_kv` | L705-714 | 10 | 3 | 1 | 2 | ✗ |
| `__init__` | L40-57 | 18 | 2 | 1 | 3 | ✗ |
| `_get_connection` | L59-65 | 7 | 2 | 1 | 1 | ✓ |
| `close_connection` | L67-71 | 5 | 2 | 1 | 1 | ✓ |
| `_migrate_add_column` | L74-80 | 7 | 2 | 1 | 4 | ✓ |
| `_migrate_messages_role` | L83-109 | 27 | 2 | 1 | 1 | ✓ |
| `add_impression` | L281-296 | 16 | 2 | 1 | 7 | ✗ |
| `delete_impression` | L319-328 | 10 | 2 | 1 | 2 | ✗ |
| `get_impression_categories` | L361-371 | 11 | 2 | 1 | 2 | ✗ |
| `add_or_update_user` | L373-387 | 15 | 2 | 1 | 3 | ✓ |
| `save_memory` | L389-406 | 18 | 2 | 1 | 8 | ✓ |
| `get_memories` | L408-428 | 21 | 2 | 1 | 3 | ✓ |
| `create_chat` | L497-510 | 14 | 2 | 1 | 3 | ✓ |
| `list_chats` | L571-598 | 28 | 2 | 1 | 2 | ✓ |
| `delete_chat` | L623-636 | 14 | 2 | 1 | 3 | ✓ |
| `save_kv` | L691-703 | 13 | 2 | 1 | 3 | ✗ |

**全部问题 (83)**

- 🔄 `_tokenize()` L17: 认知复杂度: 15
- 🔄 `_init_db()` L111: 认知复杂度: 13
- 🔄 `append_messages()` L638: 认知复杂度: 15
- 🔄 `_tokenize()` L17: 嵌套深度: 4
- 🔄 `_init_db()` L111: 嵌套深度: 4
- 📏 `_init_db()` L111: 165 代码量
- 📏 `append_messages()` L638: 52 代码量
- 📏 `add_impression()` L281: 7 参数数量
- 📏 `save_memory()` L389: 8 参数数量
- 📏 `append_messages()` L638: 7 参数数量
- 📋 `_get_connection()` L59: 重复模式: _get_connection, get_memories, delete_chat
- 📋 `add_impression()` L281: 重复模式: add_impression, get_next_round_index
- 📋 `count_impressions()` L350: 重复模式: count_impressions, get_impression_categories, load_kv
- 🏗️ `_tokenize()` L17: 中等嵌套: 4
- 🏗️ `_init_db()` L111: 中等嵌套: 4
- 🏗️ `get_messages_by_rounds()` L430: 中等嵌套: 3
- 🏗️ `save_chat_history()` L512: 中等嵌套: 3
- 🏗️ `append_messages()` L638: 中等嵌套: 3
- ❌ L70: 未处理的易出错调用
- ❌ L77: 未处理的易出错调用
- ❌ L86: 未处理的易出错调用
- ❌ L88: 未处理的易出错调用
- ❌ L93: 未处理的易出错调用
- ❌ L104: 未处理的易出错调用
- ❌ L105: 未处理的易出错调用
- ❌ L106: 未处理的易出错调用
- ❌ L107: 未处理的易出错调用
- ❌ L108: 未处理的易出错调用
- ❌ L116: 未处理的易出错调用
- ❌ L127: 未处理的易出错调用
- ❌ L136: 未处理的易出错调用
- ❌ L146: 未处理的易出错调用
- ❌ L147: 未处理的易出错调用
- ❌ L150: 未处理的易出错调用
- ❌ L162: 未处理的易出错调用
- ❌ L166: 未处理的易出错调用
- ❌ L173: 未处理的易出错调用
- ❌ L179: 未处理的易出错调用
- ❌ L184: 未处理的易出错调用
- ❌ L198: 未处理的易出错调用
- ❌ L199: 未处理的易出错调用
- ❌ L202: 未处理的易出错调用
- ❌ L214: 未处理的易出错调用
- ❌ L230: 未处理的易出错调用
- ❌ L239: 未处理的易出错调用
- ❌ L248: 未处理的易出错调用
- ❌ L262: 未处理的易出错调用
- ❌ L270: 未处理的易出错调用
- ❌ L274: 未处理的易出错调用
- ❌ L291: 未处理的易出错调用
- ❌ L295: 未处理的易出错调用
- ❌ L308: 未处理的易出错调用
- ❌ L312: 未处理的易出错调用
- ❌ L316: 未处理的易出错调用
- ❌ L323: 未处理的易出错调用
- ❌ L327: 未处理的易出错调用
- ❌ L377: 未处理的易出错调用
- ❌ L382: 未处理的易出错调用
- ❌ L386: 未处理的易出错调用
- ❌ L400: 未处理的易出错调用
- ❌ L405: 未处理的易出错调用
- ❌ L505: 未处理的易出错调用
- ❌ L509: 未处理的易出错调用
- ❌ L521: 未处理的易出错调用
- ❌ L541: 未处理的易出错调用
- ❌ L546: 未处理的易出错调用
- ❌ L612: 未处理的易出错调用
- ❌ L616: 未处理的易出错调用
- ❌ L620: 未处理的易出错调用
- ❌ L631: 未处理的易出错调用
- ❌ L635: 未处理的易出错调用
- ❌ L675: 未处理的易出错调用
- ❌ L684: 未处理的易出错调用
- ❌ L688: 未处理的易出错调用
- ❌ L694: 未处理的易出错调用
- ❌ L698: 未处理的易出错调用
- ❌ L702: 未处理的易出错调用
- 🏷️ `_tokenize()` L17: "_tokenize" - snake_case
- 🏷️ `__init__()` L40: "__init__" - snake_case
- 🏷️ `_get_connection()` L59: "_get_connection" - snake_case
- 🏷️ `_migrate_add_column()` L74: "_migrate_add_column" - snake_case
- 🏷️ `_migrate_messages_role()` L83: "_migrate_messages_role" - snake_case
- 🏷️ `_init_db()` L111: "_init_db" - snake_case

**详情**:
- 循环复杂度: 平均: 3.2, 最大: 9
- 认知复杂度: 平均: 6.3, 最大: 15
- 嵌套深度: 平均: 1.6, 最大: 4
- 函数长度: 平均: 23.5 行, 最大: 165 行
- 文件长度: 634 代码量 (715 总计)
- 参数数量: 平均: 3.1, 最大: 8
- 代码重复: 17.9% 重复 (5/28)
- 结构分析: 5 个结构问题
- 错误处理: 59/86 个错误被忽略 (68.6%)
- 注释比例: 3.8% (24/634)
- 命名规范: 发现 6 个违规

### 10. plugins/builtin/agent_plugin.py

**糟糕指数: 28.40**

> 行数: 331 总计, 255 代码, 8 注释 | 函数: 14 | 类: 1

**问题**: 🔄 复杂度问题: 4, ⚠️ 其他问题: 2, 🏗️ 结构问题: 2, ❌ 错误处理问题: 13, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_run_agent_loop` | L107-194 | 88 | 21 | 3 | 2 | ✓ |
| `_execute_tools` | L198-238 | 41 | 14 | 2 | 3 | ✓ |
| `_extract_impressions` | L240-257 | 18 | 6 | 3 | 3 | ✓ |
| `_run_single_pass` | L84-103 | 20 | 5 | 1 | 2 | ✓ |
| `on_hook` | L71-80 | 10 | 4 | 1 | 3 | ✗ |
| `_format_tool_result` | L260-268 | 9 | 4 | 1 | 3 | ✗ |
| `_afmt_web_search` | L274-282 | 9 | 4 | 2 | 1 | ✗ |
| `on_load` | L65-69 | 5 | 3 | 1 | 1 | ✗ |
| `_afmt_file_list_dir` | L285-289 | 5 | 3 | 1 | 1 | ✗ |
| `_afmt_list_experiences` | L313-320 | 8 | 3 | 2 | 1 | ✗ |
| `_afmt_file_read` | L292-296 | 5 | 2 | 1 | 1 | ✗ |
| `_afmt_import_experience` | L303-310 | 8 | 2 | 1 | 1 | ✗ |
| `__init__` | L47-63 | 17 | 1 | 0 | 8 | ✗ |
| `_afmt_file_write` | L299-300 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (31)**

- 🔄 `_run_agent_loop()` L107: 复杂度: 21
- 🔄 `_execute_tools()` L198: 复杂度: 14
- 🔄 `_run_agent_loop()` L107: 认知复杂度: 27
- 🔄 `_execute_tools()` L198: 认知复杂度: 18
- 📏 `_run_agent_loop()` L107: 88 代码量
- 📏 `__init__()` L47: 8 参数数量
- 🏗️ `_run_agent_loop()` L107: 中等嵌套: 3
- 🏗️ `_extract_impressions()` L240: 中等嵌套: 3
- ❌ L137: 未处理的易出错调用
- ❌ L164: 未处理的易出错调用
- ❌ L263: 未处理的易出错调用
- ❌ L276: 未处理的易出错调用
- ❌ L277: 未处理的易出错调用
- ❌ L278: 未处理的易出错调用
- ❌ L280: 未处理的易出错调用
- ❌ L287: 未处理的易出错调用
- ❌ L304: 未处理的易出错调用
- ❌ L306: 未处理的易出错调用
- ❌ L307: 未处理的易出错调用
- ❌ L308: 未处理的易出错调用
- ❌ L314: 未处理的易出错调用
- 🏷️ `__init__()` L47: "__init__" - snake_case
- 🏷️ `_run_single_pass()` L84: "_run_single_pass" - snake_case
- 🏷️ `_run_agent_loop()` L107: "_run_agent_loop" - snake_case
- 🏷️ `_execute_tools()` L198: "_execute_tools" - snake_case
- 🏷️ `_extract_impressions()` L240: "_extract_impressions" - snake_case
- 🏷️ `_format_tool_result()` L260: "_format_tool_result" - snake_case
- 🏷️ `_afmt_web_search()` L274: "_afmt_web_search" - snake_case
- 🏷️ `_afmt_file_list_dir()` L285: "_afmt_file_list_dir" - snake_case
- 🏷️ `_afmt_file_read()` L292: "_afmt_file_read" - snake_case
- 🏷️ `_afmt_file_write()` L299: "_afmt_file_write" - snake_case

**详情**:
- 循环复杂度: 平均: 5.2, 最大: 21
- 认知复杂度: 平均: 7.9, 最大: 27
- 嵌套深度: 平均: 1.4, 最大: 3
- 函数长度: 平均: 17.5 行, 最大: 88 行
- 文件长度: 255 代码量 (331 总计)
- 参数数量: 平均: 2.2, 最大: 8
- 代码重复: 0.0% 重复 (0/14)
- 结构分析: 2 个结构问题
- 错误处理: 13/33 个错误被忽略 (39.4%)
- 注释比例: 3.1% (8/255)
- 命名规范: 发现 12 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `create_engine_with_defaults` | engine.py | 43 | 2 | 237 |
| `process_stream` | plugins/pipeline.py | 40 | 5 | 203 |
| `search` | memory/core.py | 38 | 7 | 129 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `main` | psychoscope/minimal.py | 36 | 6 | 164 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `_cmd_reminder` | main.py | 31 | 4 | 129 |
| `_cmd_memory_query` | main.py | 31 | 3 | 141 |
| `create_application` | boot.py | 31 | 4 | 243 |
| `_cmd_plan` | main.py | 21 | 2 | 63 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*