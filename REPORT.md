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
| **糟糕指数** | **81.30/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 146 |
| 已跳过 | 348 |
| 耗时 | 836ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 25022 |
| 总注释行数 | 1297 |
| 整体注释比例 | 5.2% |
| 平均文件大小 | 215 行 |
| 最大文件 | `main.py` (1817) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 143 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 8.79% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 12.51% | 0.0% | 67.0% | 8.0% | ✓✓ |
| 嵌套深度 | 3.27% | 0.0% | 55.0% | 0.0% | ✓✓ |
| 函数长度 | 5.81% | 0.0% | 49.9% | 0.0% | ✓✓ |
| 文件长度 | 2.95% | 0.0% | 89.2% | 0.0% | ✓✓ |
| 参数数量 | 13.35% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 3.42% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.78% | 0.0% | 60.5% | 0.0% | ✓✓ |
| 错误处理 | 33.01% | 0.0% | 98.8% | 4.3% | ✓ |
| 注释比例 | 35.44% | 0.0% | 100.0% | 29.7% | ○ |
| 命名规范 | 26.67% | 0.0% | 94.7% | 21.8% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. main.py

**糟糕指数: 46.28**

> 行数: 1817 总计, 1500 代码, 27 注释 | 函数: 62 | 类: 1

**问题**: 🔄 复杂度问题: 26, ⚠️ 其他问题: 22, 🏗️ 结构问题: 12, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_memory_query` | L773-913 | 141 | 31 | 3 | 2 | ✓ |
| `_cmd_memory_rebuild` | L916-1044 | 121 | 21 | 3 | 2 | ✓ |
| `main` | L1688-1812 | 115 | 19 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L1119-1203 | 85 | 17 | 2 | 4 | ✓ |
| `_cmd_export` | L424-516 | 93 | 14 | 3 | 2 | ✓ |
| `_cmd_hibernate_check` | L1581-1647 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_import` | L519-596 | 78 | 12 | 3 | 2 | ✓ |
| `_cmd_memory` | L696-727 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_plugin` | L640-693 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L1330-1369 | 40 | 11 | 2 | 2 | ✓ |
| `_env_write` | L85-112 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L1471-1496 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L195-233 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L236-272 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_memory_reindex` | L730-770 | 31 | 8 | 1 | 1 | ✓ |
| `_persona_status` | L1372-1406 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L1550-1578 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L313-345 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L1047-1080 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1083-1116 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L1206-1232 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L1253-1272 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L1650-1678 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L47-57 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L298-310 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L348-367 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L370-397 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L757-766 | 10 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L1437-1468 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L1499-1525 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L60-74 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L287-295 | 9 | 4 | 2 | 2 | ✗ |
| `_run` | L1032-1039 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L1769-1778 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L77-82 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L146-156 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L159-164 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L178-192 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L400-416 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L1419-1430 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L1535-1547 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L115-118 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L121-123 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L126-139 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L1284-1285 | 2 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L1409-1433 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L1681-1685 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L133-134 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L419-421 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L599-637 | 39 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L1235-1250 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L1275-1276 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L1278-1279 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L1281-1282 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L1287-1288 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L1290-1291 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L1293-1294 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L1296-1297 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L1299-1300 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L1302-1303 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L1306-1307 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L1310-1311 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (81)**

- 🔄 `_cmd_export()` L424: 复杂度: 14
- 🔄 `_cmd_import()` L519: 复杂度: 12
- 🔄 `_cmd_plugin()` L640: 复杂度: 11
- 🔄 `_cmd_memory()` L696: 复杂度: 12
- 🔄 `_cmd_memory_query()` L773: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L916: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1119: 复杂度: 17
- 🔄 `_cmd_persona()` L1330: 复杂度: 11
- 🔄 `_cmd_hibernate_check()` L1581: 复杂度: 14
- 🔄 `main()` L1688: 复杂度: 19
- 🔄 `_env_write()` L85: 认知复杂度: 20
- 🔄 `_cmd_users()` L195: 认知复杂度: 13
- 🔄 `_cmd_status()` L236: 认知复杂度: 13
- 🔄 `_cmd_export()` L424: 认知复杂度: 20
- 🔄 `_cmd_import()` L519: 认知复杂度: 18
- 🔄 `_cmd_plugin()` L640: 认知复杂度: 15
- 🔄 `_cmd_memory()` L696: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L773: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L916: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1119: 认知复杂度: 21
- 🔄 `_cmd_persona()` L1330: 认知复杂度: 15
- 🔄 `_persona_status()` L1372: 认知复杂度: 14
- 🔄 `_persona_materials()` L1471: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L1581: 认知复杂度: 20
- 🔄 `main()` L1688: 认知复杂度: 25
- 🔄 `_env_write()` L85: 嵌套深度: 5
- 📏 `_cmd_export()` L424: 93 代码量
- 📏 `_cmd_import()` L519: 78 代码量
- 📏 `_cmd_plugin()` L640: 54 代码量
- 📏 `_cmd_memory_query()` L773: 141 代码量
- 📏 `_cmd_memory_rebuild()` L916: 121 代码量
- 📏 `_cmd_memory_list()` L1119: 85 代码量
- 📏 `_cmd_hibernate_check()` L1581: 67 代码量
- 📏 `main()` L1688: 115 代码量
- 📏 `_execute_command()` L1253: 9 参数数量
- 📏 `_h_newbind()` L1275: 7 参数数量
- 📏 `_h_users()` L1278: 7 参数数量
- 📏 `_h_status()` L1281: 7 参数数量
- 📏 `_h_plugin()` L1284: 7 参数数量
- 📏 `_h_memory()` L1287: 7 参数数量
- 📏 `_h_prompt()` L1290: 7 参数数量
- 📏 `_h_config()` L1293: 7 参数数量
- 📏 `_h_listconfig()` L1296: 7 参数数量
- 📏 `_h_persona()` L1299: 7 参数数量
- 📏 `_h_help()` L1302: 7 参数数量
- 📏 `_h_export()` L1306: 7 参数数量
- 📏 `_h_import()` L1310: 7 参数数量
- 🏗️ `_env_backup_rotate()` L47: 中等嵌套: 3
- 🏗️ `_env_write()` L85: 嵌套过深: 5
- 🏗️ `_cmd_export()` L424: 中等嵌套: 3
- 🏗️ `_cmd_import()` L519: 中等嵌套: 3
- 🏗️ `_cmd_memory_query()` L773: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L916: 中等嵌套: 3
- 🏗️ `_persona_status()` L1372: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L1581: 中等嵌套: 3
- 🏗️ `main()` L1688: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1817 行
- 🏗️ L1: 函数过多: 62
- 🏗️ L1: 导入过多: 42
- ❌ L221: 未处理的易出错调用
- ❌ L229: 未处理的易出错调用
- ❌ L561: 未处理的易出错调用
- ❌ L573: 未处理的易出错调用
- ❌ L587: 未处理的易出错调用
- ❌ L593: 未处理的易出错调用
- ❌ L688: 未处理的易出错调用
- ❌ L1200: 未处理的易出错调用
- ❌ L1404: 未处理的易出错调用
- ❌ L1459: 未处理的易出错调用
- ❌ L1460: 未处理的易出错调用
- ❌ L1461: 未处理的易出错调用
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
- 循环复杂度: 平均: 5.8, 最大: 31
- 认知复杂度: 平均: 8.6, 最大: 37
- 嵌套深度: 平均: 1.4, 最大: 5
- 函数长度: 平均: 26.0 行, 最大: 141 行
- 文件长度: 1500 代码量 (1817 总计)
- 参数数量: 平均: 2.6, 最大: 9
- 代码重复: 1.6% 重复 (1/62)
- 结构分析: 12 个结构问题
- 错误处理: 12/55 个错误被忽略 (21.8%)
- 注释比例: 1.8% (27/1500)
- 命名规范: 发现 59 个违规

### 2. memory/core.py

**糟糕指数: 43.78**

> 行数: 752 总计, 614 代码, 43 注释 | 函数: 26 | 类: 1

**问题**: 🔄 复杂度问题: 14, ⚠️ 其他问题: 7, 📋 重复问题: 2, 🏗️ 结构问题: 5, ❌ 错误处理问题: 14, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L231-355 | 125 | 38 | 7 | 8 | ✓ |
| `_format_detail_results` | L714-751 | 38 | 13 | 4 | 2 | ✗ |
| `reindex_embeddings` | L366-444 | 79 | 11 | 3 | 4 | ✓ |
| `_format_search_results` | L681-711 | 31 | 11 | 2 | 3 | ✗ |
| `handle_tags` | L554-581 | 28 | 9 | 2 | 4 | ✗ |
| `_handle_recall` | L583-608 | 26 | 9 | 3 | 4 | ✗ |
| `_format_timedelta` | L656-678 | 23 | 9 | 2 | 1 | ✗ |
| `rebuild_summaries` | L450-511 | 62 | 8 | 3 | 2 | ✓ |
| `_do_summarize` | L109-138 | 30 | 6 | 2 | 6 | ✗ |
| `_cosine_similarity` | L187-195 | 9 | 6 | 1 | 2 | ✗ |
| `summarize_turn` | L82-107 | 26 | 5 | 1 | 7 | ✓ |
| `assemble_context` | L201-225 | 25 | 5 | 1 | 4 | ✗ |
| `_build_round_text` | L513-527 | 15 | 5 | 2 | 4 | ✓ |
| `_build_round_messages` | L529-548 | 20 | 5 | 2 | 4 | ✓ |
| `_embed_and_store` | L161-176 | 16 | 4 | 2 | 4 | ✓ |
| `__init__` | L29-42 | 14 | 3 | 0 | 4 | ✗ |
| `_init_table` | L44-66 | 23 | 2 | 1 | 1 | ✗ |
| `_decrypt` | L73-76 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L614-624 | 11 | 2 | 1 | 4 | ✗ |
| `delete_memo` | L642-649 | 8 | 2 | 1 | 2 | ✗ |
| `_encrypt` | L70-71 | 2 | 1 | 0 | 3 | ✗ |
| `_get_exp_memories` | L140-155 | 16 | 1 | 0 | 3 | ✗ |
| `_pack_embedding` | L179-180 | 2 | 1 | 0 | 1 | ✗ |
| `_unpack_embedding` | L183-184 | 2 | 1 | 0 | 1 | ✗ |
| `get_detail` | L357-360 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L626-640 | 15 | 1 | 0 | 3 | ✗ |

**全部问题 (51)**

- 🔄 `search()` L231: 复杂度: 38
- 🔄 `reindex_embeddings()` L366: 复杂度: 11
- 🔄 `_format_search_results()` L681: 复杂度: 11
- 🔄 `_format_detail_results()` L714: 复杂度: 13
- 🔄 `search()` L231: 认知复杂度: 52
- 🔄 `reindex_embeddings()` L366: 认知复杂度: 17
- 🔄 `rebuild_summaries()` L450: 认知复杂度: 14
- 🔄 `handle_tags()` L554: 认知复杂度: 13
- 🔄 `_handle_recall()` L583: 认知复杂度: 15
- 🔄 `_format_timedelta()` L656: 认知复杂度: 13
- 🔄 `_format_search_results()` L681: 认知复杂度: 15
- 🔄 `_format_detail_results()` L714: 认知复杂度: 21
- 🔄 `search()` L231: 嵌套深度: 7
- 🔄 `_format_detail_results()` L714: 嵌套深度: 4
- 📏 `search()` L231: 125 代码量
- 📏 `reindex_embeddings()` L366: 79 代码量
- 📏 `rebuild_summaries()` L450: 62 代码量
- 📏 `summarize_turn()` L82: 7 参数数量
- 📏 `_do_summarize()` L109: 6 参数数量
- 📏 `search()` L231: 8 参数数量
- 📋 `_get_exp_memories()` L140: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L614: 重复模式: add_memo, delete_memo
- 🏗️ `search()` L231: 嵌套过深: 7
- 🏗️ `reindex_embeddings()` L366: 中等嵌套: 3
- 🏗️ `rebuild_summaries()` L450: 中等嵌套: 3
- 🏗️ `_handle_recall()` L583: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L714: 中等嵌套: 4
- ❌ L46: 未处理的易出错调用
- ❌ L57: 未处理的易出错调用
- ❌ L63: 未处理的易出错调用
- ❌ L66: 未处理的易出错调用
- ❌ L130: 未处理的易出错调用
- ❌ L170: 未处理的易出错调用
- ❌ L174: 未处理的易出错调用
- ❌ L432: 未处理的易出错调用
- ❌ L436: 未处理的易出错调用
- ❌ L498: 未处理的易出错调用
- ❌ L502: 未处理的易出错调用
- ❌ L623: 未处理的易出错调用
- ❌ L648: 未处理的易出错调用
- ❌ L728: 未处理的易出错调用
- 🏷️ `__init__()` L29: "__init__" - snake_case
- 🏷️ `_init_table()` L44: "_init_table" - snake_case
- 🏷️ `_encrypt()` L70: "_encrypt" - snake_case
- 🏷️ `_decrypt()` L73: "_decrypt" - snake_case
- 🏷️ `_do_summarize()` L109: "_do_summarize" - snake_case
- 🏷️ `_get_exp_memories()` L140: "_get_exp_memories" - snake_case
- 🏷️ `_embed_and_store()` L161: "_embed_and_store" - snake_case
- 🏷️ `_pack_embedding()` L179: "_pack_embedding" - snake_case
- 🏷️ `_unpack_embedding()` L183: "_unpack_embedding" - snake_case
- 🏷️ `_cosine_similarity()` L187: "_cosine_similarity" - snake_case

**详情**:
- 循环复杂度: 平均: 6.2, 最大: 38
- 认知复杂度: 平均: 9.3, 最大: 52
- 嵌套深度: 平均: 1.6, 最大: 7
- 函数长度: 平均: 25.2 行, 最大: 125 行
- 文件长度: 614 代码量 (752 总计)
- 参数数量: 平均: 3.4, 最大: 8
- 代码重复: 7.7% 重复 (2/26)
- 结构分析: 5 个结构问题
- 错误处理: 14/35 个错误被忽略 (40.0%)
- 注释比例: 7.0% (43/614)
- 命名规范: 发现 17 个违规

### 3. engine.py

**糟糕指数: 43.52**

> 行数: 1034 总计, 891 代码, 19 注释 | 函数: 38 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 📋 重复问题: 2, 🏗️ 结构问题: 7, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L797-1033 | 237 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L424-464 | 41 | 16 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L554-594 | 41 | 11 | 2 | 1 | ✗ |
| `build_context` | L632-665 | 34 | 10 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L532-552 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L596-619 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L667-703 | 37 | 9 | 2 | 8 | ✓ |
| `_register_context_plugins` | L511-530 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L705-724 | 20 | 8 | 1 | 8 | ✓ |
| `_generate_result_message` | L255-292 | 38 | 7 | 2 | 3 | ✗ |
| `run_scheduled` | L734-771 | 31 | 7 | 2 | 1 | ✓ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_handle_engine_action_completion` | L214-228 | 15 | 6 | 2 | 4 | ✗ |
| `_retry_engine_action` | L294-315 | 22 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L317-345 | 29 | 6 | 3 | 1 | ✗ |
| `_init_world` | L347-372 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L392-408 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L410-422 | 13 | 6 | 3 | 1 | ✓ |
| `get_info` | L775-783 | 9 | 6 | 0 | 1 | ✗ |
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
| `create_chat` | L726-727 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L729-730 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L746-752 | 7 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L139-154 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L621-628 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L788-794 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (38)**

- 🔄 `_init_prompt()` L424: 复杂度: 16
- 🔄 `_register_execution_plugins()` L554: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L797: 复杂度: 43
- 🔄 `_init_prompt()` L424: 认知复杂度: 24
- 🔄 `_register_personality_plugins()` L532: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L554: 认知复杂度: 15
- 🔄 `_register_output_plugins()` L596: 认知复杂度: 13
- 🔄 `chat()` L667: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L797: 认知复杂度: 47
- 🔄 `_init_prompt()` L424: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L797: 237 代码量
- 📏 `build_context()` L632: 8 参数数量
- 📏 `chat()` L667: 8 参数数量
- 📏 `chat_stream()` L705: 8 参数数量
- 📏 `create_engine_with_defaults()` L797: 12 参数数量
- 📋 `_init_database()` L156: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L241: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L186: 中等嵌套: 3
- 🏗️ `_init_memory()` L317: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L410: 中等嵌套: 3
- 🏗️ `_init_prompt()` L424: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1034 行
- 🏗️ L1: 导入过多: 81
- ❌ L215: 未处理的易出错调用
- ❌ L225: 未处理的易出错调用
- ❌ L271: 未处理的易出错调用
- ❌ L750: 未处理的易出错调用
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
- 循环复杂度: 平均: 6.1, 最大: 43
- 认知复杂度: 平均: 8.9, 最大: 47
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 23.8 行, 最大: 237 行
- 文件长度: 891 代码量 (1034 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.5% 重复 (4/38)
- 结构分析: 7 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.1% (19/891)
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

**糟糕指数: 36.39**

> 行数: 775 总计, 663 代码, 5 注释 | 函数: 32 | 类: 3

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 3, 📋 重复问题: 2, 🏗️ 结构问题: 9, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L605-772 | 161 | 36 | 6 | 0 | ✗ |
| `authenticate` | L194-275 | 82 | 14 | 2 | 3 | ✗ |
| `_handle_sse_stream` | L353-386 | 34 | 11 | 3 | 3 | ✗ |
| `stop_and_send` | L426-458 | 33 | 10 | 2 | 1 | ✗ |
| `_tts_worker` | L170-192 | 23 | 9 | 3 | 1 | ✗ |
| `_capture_loop` | L460-490 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L516-542 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L124-141 | 18 | 8 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L70-83 | 14 | 6 | 5 | 0 | ✓ |
| `send_audio` | L313-351 | 39 | 6 | 2 | 2 | ✗ |
| `_verify_api_key` | L277-294 | 18 | 5 | 3 | 1 | ✗ |
| `_play_beep` | L97-111 | 15 | 4 | 1 | 2 | ✓ |
| `__init__` | L155-168 | 14 | 4 | 1 | 3 | ✗ |
| `start` | L404-424 | 21 | 4 | 1 | 1 | ✗ |
| `print_header` | L544-568 | 25 | 4 | 1 | 3 | ✗ |
| `load_config` | L143-149 | 7 | 3 | 2 | 0 | ✗ |
| `print_personality` | L570-595 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L45-65 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L114-122 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L296-299 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L498-503 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L505-508 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L510-514 | 5 | 2 | 1 | 2 | ✗ |
| `toggle_standby` | L597-603 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L661-667 | 7 | 2 | 1 | 2 | ✗ |
| `save_config` | L151-152 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L301-303 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L305-307 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L309-311 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L389-398 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L401-402 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L493-496 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (45)**

- 🔄 `authenticate()` L194: 复杂度: 14
- 🔄 `_handle_sse_stream()` L353: 复杂度: 11
- 🔄 `main()` L605: 复杂度: 36
- 🔄 `_detect_tts_sample_rate()` L70: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L124: 认知复杂度: 14
- 🔄 `_tts_worker()` L170: 认知复杂度: 15
- 🔄 `authenticate()` L194: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L353: 认知复杂度: 17
- 🔄 `stop_and_send()` L426: 认知复杂度: 14
- 🔄 `_capture_loop()` L460: 认知复杂度: 15
- 🔄 `_loop()` L516: 认知复杂度: 19
- 🔄 `main()` L605: 认知复杂度: 48
- 🔄 `_detect_tts_sample_rate()` L70: 嵌套深度: 5
- 🔄 `_loop()` L516: 嵌套深度: 5
- 🔄 `main()` L605: 嵌套深度: 6
- 📏 `authenticate()` L194: 82 代码量
- 📏 `main()` L605: 161 代码量
- 📋 `__init__()` L155: 重复模式: __init__, __init__
- 📋 `_tts_worker()` L170: 重复模式: _tts_worker, _loop
- 🏗️ `_detect_tts_sample_rate()` L70: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L124: 中等嵌套: 3
- 🏗️ `_tts_worker()` L170: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L277: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L353: 中等嵌套: 3
- 🏗️ `_capture_loop()` L460: 中等嵌套: 3
- 🏗️ `_loop()` L516: 嵌套过深: 5
- 🏗️ `main()` L605: 嵌套过深: 6
- 🏗️ L1: 导入过多: 25
- ❌ L75: 未处理的易出错调用
- ❌ L117: 未处理的易出错调用
- ❌ L337: 未处理的易出错调用
- ❌ L444: 未处理的易出错调用
- ❌ L529: 未处理的易出错调用
- ❌ L538: 未处理的易出错调用
- ❌ L591: 未处理的易出错调用
- 🏷️ `_detect_tts_sample_rate()` L70: "_detect_tts_sample_rate" - snake_case
- 🏷️ `_play_beep()` L97: "_play_beep" - snake_case
- 🏷️ `__init__()` L155: "__init__" - snake_case
- 🏷️ `_tts_worker()` L170: "_tts_worker" - snake_case
- 🏷️ `_verify_api_key()` L277: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L296: "_headers" - snake_case
- 🏷️ `_http_get()` L301: "_http_get" - snake_case
- 🏷️ `_http_post()` L305: "_http_post" - snake_case
- 🏷️ `_http_post_stream()` L309: "_http_post_stream" - snake_case
- 🏷️ `_handle_sse_stream()` L353: "_handle_sse_stream" - snake_case

**详情**:
- 循环复杂度: 平均: 5.3, 最大: 36
- 认知复杂度: 平均: 8.6, 最大: 48
- 嵌套深度: 平均: 1.7, 最大: 6
- 函数长度: 平均: 21.2 行, 最大: 161 行
- 文件长度: 663 代码量 (775 总计)
- 参数数量: 平均: 1.4, 最大: 3
- 代码重复: 6.3% 重复 (2/32)
- 结构分析: 9 个结构问题
- 错误处理: 7/61 个错误被忽略 (11.5%)
- 注释比例: 0.8% (5/663)
- 命名规范: 发现 14 个违规

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

### 8. chatdbmgr.py

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

### 9. plugins/builtin/agent_plugin.py

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

### 10. models.py

**糟糕指数: 23.78**

> 行数: 658 总计, 535 代码, 20 注释 | 函数: 36 | 类: 4

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 8, 🏗️ 结构问题: 3, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_llm` | L539-596 | 45 | 13 | 5 | 7 | ✓ |
| `_call_embed_api` | L427-480 | 41 | 11 | 5 | 2 | ✓ |
| `_call_and_append` | L125-182 | 58 | 9 | 2 | 1 | ✓ |
| `__init__` | L505-537 | 33 | 7 | 1 | 8 | ✗ |
| `summarize_dialog` | L624-657 | 34 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L14-22 | 9 | 6 | 1 | 1 | ✓ |
| `_call_chat_api` | L263-281 | 19 | 6 | 4 | 2 | ✓ |
| `describe_image` | L343-375 | 33 | 6 | 1 | 5 | ✓ |
| `__init__` | L61-111 | 51 | 5 | 1 | 8 | ✓ |
| `_do_request` | L550-562 | 13 | 5 | 2 | 0 | ✗ |
| `summarize_text` | L598-619 | 22 | 5 | 1 | 3 | ✓ |
| `__init__` | L221-256 | 36 | 4 | 1 | 7 | ✓ |
| `send_message` | L283-290 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L390-410 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L412-419 | 8 | 4 | 1 | 2 | ✓ |
| `_load_lmstudio_model` | L25-44 | 20 | 3 | 1 | 4 | ✓ |
| `send_message` | L113-119 | 7 | 3 | 1 | 2 | ✓ |
| `_call_and_append` | L296-314 | 19 | 3 | 1 | 1 | ✗ |
| `_do_request` | L432-444 | 13 | 3 | 1 | 0 | ✗ |
| `embed_batch` | L421-425 | 5 | 2 | 1 | 2 | ✓ |
| `continue_conversation` | L121-123 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L184-187 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L189-195 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L197-204 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L206-209 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L211-212 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L258-259 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L292-294 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L316-319 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L321-327 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L329-336 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L338-341 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L377-378 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L482-483 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L485-486 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L621-622 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (30)**

- 🔄 `_call_embed_api()` L427: 复杂度: 11
- 🔄 `_call_llm()` L539: 复杂度: 13
- 🔄 `_call_and_append()` L125: 认知复杂度: 13
- 🔄 `_call_chat_api()` L263: 认知复杂度: 14
- 🔄 `_call_embed_api()` L427: 认知复杂度: 21
- 🔄 `_call_llm()` L539: 认知复杂度: 23
- 🔄 `_call_chat_api()` L263: 嵌套深度: 4
- 🔄 `_call_embed_api()` L427: 嵌套深度: 5
- 🔄 `_call_llm()` L539: 嵌套深度: 5
- 📏 `__init__()` L61: 51 代码量
- 📏 `_call_and_append()` L125: 58 代码量
- 📏 `__init__()` L61: 8 参数数量
- 📏 `__init__()` L221: 7 参数数量
- 📏 `__init__()` L390: 6 参数数量
- 📏 `__init__()` L505: 8 参数数量
- 📏 `_call_llm()` L539: 7 参数数量
- 🏗️ `_call_chat_api()` L263: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L427: 嵌套过深: 5
- 🏗️ `_call_llm()` L539: 嵌套过深: 5
- ❌ L40: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L14: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L25: "_load_lmstudio_model" - snake_case
- 🏷️ `__init__()` L61: "__init__" - snake_case
- 🏷️ `_call_and_append()` L125: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L211: "__repr__" - snake_case
- 🏷️ `__init__()` L221: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L258: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L263: "_call_chat_api" - snake_case
- 🏷️ `_call_and_append()` L296: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L377: "__repr__" - snake_case

**详情**:
- 循环复杂度: 平均: 3.5, 最大: 13
- 认知复杂度: 平均: 5.3, 最大: 23
- 嵌套深度: 平均: 0.9, 最大: 5
- 函数长度: 平均: 15.5 行, 最大: 58 行
- 文件长度: 535 代码量 (658 总计)
- 参数数量: 平均: 2.4, 最大: 8
- 代码重复: 2.8% 重复 (1/36)
- 结构分析: 3 个结构问题
- 错误处理: 1/15 个错误被忽略 (6.7%)
- 注释比例: 3.7% (20/535)
- 命名规范: 发现 19 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `create_engine_with_defaults` | engine.py | 43 | 2 | 237 |
| `process_stream` | plugins/pipeline.py | 40 | 5 | 203 |
| `search` | memory/core.py | 38 | 7 | 125 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `main` | psychoscope/minimal.py | 36 | 6 | 161 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `_cmd_memory_query` | main.py | 31 | 3 | 141 |
| `_cmd_memory_rebuild` | main.py | 21 | 3 | 121 |
| `_run_agent_loop` | plugins/builtin/agent_plugin.py | 21 | 3 | 88 |
| `_collect_state` | stationed.py | 19 | 5 | 77 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*