# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-82%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **81.98/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 122 |
| 已跳过 | 507 |
| 耗时 | 766ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 21417 |
| 总注释行数 | 1149 |
| 整体注释比例 | 5.4% |
| 平均文件大小 | 220 行 |
| 最大文件 | `psychoscope/static/js/app.js` (1338) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 120 |
| JavaScript | 2 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 11.18% | 0.0% | 100.0% | 4.0% | ✓✓ |
| 认知复杂度 | 15.00% | 0.0% | 95.8% | 10.0% | ✓✓ |
| 嵌套深度 | 3.46% | 0.0% | 37.5% | 0.0% | ✓✓ |
| 函数长度 | 6.79% | 0.0% | 51.1% | 2.2% | ✓✓ |
| 文件长度 | 2.60% | 0.0% | 85.5% | 0.0% | ✓✓ |
| 参数数量 | 15.52% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 3.96% | 0.0% | 59.4% | 0.0% | ✓✓ |
| 结构分析 | 4.48% | 0.0% | 40.5% | 3.0% | ✓✓ |
| 错误处理 | 34.17% | 0.0% | 98.8% | 9.3% | ✓ |
| 注释比例 | 35.68% | 0.0% | 100.0% | 29.5% | ○ |
| 命名规范 | 25.95% | 0.0% | 89.5% | 22.2% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. chatdbmgr.py

**糟糕指数: 43.48**

> 行数: 812 总计, 717 代码, 26 注释 | 函数: 29 | 类: 1

**问题**: 🔄 复杂度问题: 8, ⚠️ 其他问题: 8, 📋 重复问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 60, 📝 注释问题: 1, 🏷️ 命名问题: 6

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search_memories` | L424-520 | 83 | 22 | 5 | 6 | ✓ |
| `append_messages` | L760-811 | 52 | 9 | 3 | 7 | ✓ |
| `_tokenize` | L429-442 | 14 | 7 | 4 | 1 | ✓ |
| `get_messages_by_rounds` | L522-557 | 36 | 6 | 3 | 4 | ✓ |
| `save_chat_history` | L634-669 | 36 | 6 | 3 | 4 | ✓ |
| `_init_db` | L94-269 | 176 | 5 | 4 | 1 | ✓ |
| `get_impressions` | L324-342 | 19 | 4 | 2 | 5 | ✗ |
| `save_memory` | L383-401 | 19 | 4 | 1 | 8 | ✓ |
| `get_next_round_index` | L588-600 | 13 | 4 | 1 | 2 | ✓ |
| `update_impression` | L292-311 | 20 | 3 | 1 | 2 | ✗ |
| `count_impressions` | L344-353 | 10 | 3 | 1 | 2 | ✗ |
| `get_memories` | L403-422 | 20 | 3 | 1 | 3 | ✓ |
| `get_last_message_ids` | L559-573 | 15 | 3 | 2 | 3 | ✓ |
| `get_memory_count` | L575-586 | 12 | 3 | 1 | 3 | ✓ |
| `get_chat_history` | L671-691 | 21 | 3 | 2 | 3 | ✓ |
| `replace_last_assistant` | L722-743 | 22 | 3 | 2 | 4 | ✓ |
| `__init__` | L23-40 | 18 | 2 | 1 | 3 | ✗ |
| `_get_connection` | L42-48 | 7 | 2 | 1 | 1 | ✓ |
| `close_connection` | L50-54 | 5 | 2 | 1 | 1 | ✓ |
| `_migrate_add_column` | L57-63 | 7 | 2 | 1 | 4 | ✓ |
| `_migrate_messages_role` | L66-92 | 27 | 2 | 1 | 1 | ✓ |
| `add_impression` | L275-290 | 16 | 2 | 1 | 7 | ✗ |
| `delete_impression` | L313-322 | 10 | 2 | 1 | 2 | ✗ |
| `get_impression_categories` | L355-365 | 11 | 2 | 1 | 2 | ✗ |
| `add_or_update_user` | L367-381 | 15 | 2 | 1 | 3 | ✓ |
| `delete_oldest_memory` | L602-617 | 16 | 2 | 1 | 4 | ✓ |
| `create_chat` | L619-632 | 14 | 2 | 1 | 3 | ✓ |
| `list_chats` | L693-720 | 28 | 2 | 1 | 2 | ✓ |
| `delete_chat` | L745-758 | 14 | 2 | 1 | 3 | ✓ |

**全部问题 (90)**

- 🔄 `search_memories()` L424: 复杂度: 22
- 🔄 `_init_db()` L94: 认知复杂度: 13
- 🔄 `search_memories()` L424: 认知复杂度: 32
- 🔄 `_tokenize()` L429: 认知复杂度: 15
- 🔄 `append_messages()` L760: 认知复杂度: 15
- 🔄 `_init_db()` L94: 嵌套深度: 4
- 🔄 `search_memories()` L424: 嵌套深度: 5
- 🔄 `_tokenize()` L429: 嵌套深度: 4
- 📏 `_init_db()` L94: 176 代码量
- 📏 `search_memories()` L424: 83 代码量
- 📏 `append_messages()` L760: 52 代码量
- 📏 `add_impression()` L275: 7 参数数量
- 📏 `save_memory()` L383: 8 参数数量
- 📏 `search_memories()` L424: 6 参数数量
- 📏 `append_messages()` L760: 7 参数数量
- 📋 `_get_connection()` L42: 重复模式: _get_connection, get_memories, get_memory_count, delete_oldest_memory, delete_chat
- 📋 `add_impression()` L275: 重复模式: add_impression, get_next_round_index
- 📋 `count_impressions()` L344: 重复模式: count_impressions, get_impression_categories
- 🏗️ `_init_db()` L94: 中等嵌套: 4
- 🏗️ `search_memories()` L424: 嵌套过深: 5
- 🏗️ `_tokenize()` L429: 中等嵌套: 4
- 🏗️ `get_messages_by_rounds()` L522: 中等嵌套: 3
- 🏗️ `save_chat_history()` L634: 中等嵌套: 3
- 🏗️ `append_messages()` L760: 中等嵌套: 3
- ❌ L53: 未处理的易出错调用
- ❌ L60: 未处理的易出错调用
- ❌ L69: 未处理的易出错调用
- ❌ L71: 未处理的易出错调用
- ❌ L76: 未处理的易出错调用
- ❌ L87: 未处理的易出错调用
- ❌ L88: 未处理的易出错调用
- ❌ L89: 未处理的易出错调用
- ❌ L90: 未处理的易出错调用
- ❌ L91: 未处理的易出错调用
- ❌ L99: 未处理的易出错调用
- ❌ L110: 未处理的易出错调用
- ❌ L119: 未处理的易出错调用
- ❌ L129: 未处理的易出错调用
- ❌ L130: 未处理的易出错调用
- ❌ L131: 未处理的易出错调用
- ❌ L145: 未处理的易出错调用
- ❌ L148: 未处理的易出错调用
- ❌ L160: 未处理的易出错调用
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
- ❌ L264: 未处理的易出错调用
- ❌ L268: 未处理的易出错调用
- ❌ L285: 未处理的易出错调用
- ❌ L289: 未处理的易出错调用
- ❌ L302: 未处理的易出错调用
- ❌ L306: 未处理的易出错调用
- ❌ L310: 未处理的易出错调用
- ❌ L317: 未处理的易出错调用
- ❌ L321: 未处理的易出错调用
- ❌ L371: 未处理的易出错调用
- ❌ L376: 未处理的易出错调用
- ❌ L380: 未处理的易出错调用
- ❌ L395: 未处理的易出错调用
- ❌ L400: 未处理的易出错调用
- ❌ L606: 未处理的易出错调用
- ❌ L612: 未处理的易出错调用
- ❌ L616: 未处理的易出错调用
- ❌ L627: 未处理的易出错调用
- ❌ L631: 未处理的易出错调用
- ❌ L643: 未处理的易出错调用
- ❌ L663: 未处理的易出错调用
- ❌ L668: 未处理的易出错调用
- ❌ L734: 未处理的易出错调用
- ❌ L738: 未处理的易出错调用
- ❌ L742: 未处理的易出错调用
- ❌ L753: 未处理的易出错调用
- ❌ L757: 未处理的易出错调用
- ❌ L797: 未处理的易出错调用
- ❌ L806: 未处理的易出错调用
- ❌ L810: 未处理的易出错调用
- 🏷️ `__init__()` L23: "__init__" - snake_case
- 🏷️ `_get_connection()` L42: "_get_connection" - snake_case
- 🏷️ `_migrate_add_column()` L57: "_migrate_add_column" - snake_case
- 🏷️ `_migrate_messages_role()` L66: "_migrate_messages_role" - snake_case
- 🏷️ `_init_db()` L94: "_init_db" - snake_case
- 🏷️ `_tokenize()` L429: "_tokenize" - snake_case

**详情**:
- 循环复杂度: 平均: 3.9, 最大: 22
- 认知复杂度: 平均: 7.3, 最大: 32
- 嵌套深度: 平均: 1.7, 最大: 5
- 函数长度: 平均: 26.1 行, 最大: 176 行
- 文件长度: 717 代码量 (812 总计)
- 参数数量: 平均: 3.2, 最大: 8
- 代码重复: 20.7% 重复 (6/29)
- 结构分析: 6 个结构问题
- 错误处理: 60/89 个错误被忽略 (67.4%)
- 注释比例: 3.6% (26/717)
- 命名规范: 发现 6 个违规

### 2. engine.py

**糟糕指数: 41.32**

> 行数: 1038 总计, 868 代码, 37 注释 | 函数: 31 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 7, 📋 重复问题: 1, 🏗️ 结构问题: 6, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L805-1037 | 233 | 43 | 2 | 12 | ✓ |
| `_init_plugins` | L452-630 | 173 | 37 | 2 | 1 | ✗ |
| `_init_prompt` | L410-450 | 41 | 16 | 4 | 1 | ✗ |
| `_process_task_completion` | L188-210 | 23 | 9 | 4 | 1 | ✗ |
| `build_context` | L643-673 | 31 | 9 | 1 | 8 | ✓ |
| `chat` | L675-711 | 37 | 9 | 2 | 8 | ✓ |
| `chat_stream` | L713-732 | 20 | 8 | 1 | 8 | ✓ |
| `_generate_result_message` | L253-290 | 38 | 7 | 2 | 3 | ✗ |
| `run_scheduled` | L742-779 | 31 | 7 | 2 | 1 | ✓ |
| `_get_event_loop` | L44-50 | 7 | 6 | 3 | 0 | ✗ |
| `_handle_engine_action_completion` | L212-226 | 15 | 6 | 2 | 4 | ✗ |
| `_retry_engine_action` | L292-313 | 22 | 6 | 2 | 4 | ✗ |
| `_init_world` | L333-358 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L378-394 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L396-408 | 13 | 6 | 3 | 1 | ✓ |
| `get_info` | L783-791 | 9 | 6 | 0 | 1 | ✗ |
| `_init_memory` | L315-331 | 17 | 4 | 1 | 1 | ✗ |
| `from_subapp` | L76-92 | 17 | 3 | 0 | 1 | ✗ |
| `__init__` | L106-137 | 32 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L165-184 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L239-251 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L360-376 | 17 | 3 | 2 | 1 | ✗ |
| `enabled` | L458-463 | 6 | 3 | 1 | 1 | ✓ |
| `_init_database` | L158-163 | 6 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L228-237 | 10 | 2 | 1 | 3 | ✗ |
| `create_chat` | L734-735 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L737-738 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L754-760 | 7 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L141-156 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L632-639 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L796-802 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (37)**

- 🔄 `_init_prompt()` L410: 复杂度: 16
- 🔄 `_init_plugins()` L452: 复杂度: 37
- 🔄 `create_engine_with_defaults()` L805: 复杂度: 43
- 🔄 `_process_task_completion()` L188: 认知复杂度: 17
- 🔄 `_init_prompt()` L410: 认知复杂度: 24
- 🔄 `_init_plugins()` L452: 认知复杂度: 41
- 🔄 `chat()` L675: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L805: 认知复杂度: 47
- 🔄 `_process_task_completion()` L188: 嵌套深度: 4
- 🔄 `_init_prompt()` L410: 嵌套深度: 4
- 📏 `_init_plugins()` L452: 173 代码量
- 📏 `create_engine_with_defaults()` L805: 233 代码量
- 📏 `build_context()` L643: 8 参数数量
- 📏 `chat()` L675: 8 参数数量
- 📏 `chat_stream()` L713: 8 参数数量
- 📏 `create_engine_with_defaults()` L805: 12 参数数量
- 📋 `_process_task_completion()` L188: 重复模式: _process_task_completion, _handle_reasoner_completion, _init_pipeline
- 🏗️ `_get_event_loop()` L44: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L188: 中等嵌套: 4
- 🏗️ `_inject_v3_to_exa_evolution()` L396: 中等嵌套: 3
- 🏗️ `_init_prompt()` L410: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1038 行
- 🏗️ L1: 导入过多: 80
- ❌ L213: 未处理的易出错调用
- ❌ L223: 未处理的易出错调用
- ❌ L269: 未处理的易出错调用
- ❌ L758: 未处理的易出错调用
- 🏷️ `_get_event_loop()` L44: "_get_event_loop" - snake_case
- 🏷️ `__init__()` L106: "__init__" - snake_case
- 🏷️ `_init_from_subapp()` L141: "_init_from_subapp" - snake_case
- 🏷️ `_init_database()` L158: "_init_database" - snake_case
- 🏷️ `_init_tasks()` L165: "_init_tasks" - snake_case
- 🏷️ `_process_task_completion()` L188: "_process_task_completion" - snake_case
- 🏷️ `_handle_engine_action_completion()` L212: "_handle_engine_action_completion" - snake_case
- 🏷️ `_handle_reminder_completion()` L228: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L239: "_handle_reasoner_completion" - snake_case
- 🏷️ `_generate_result_message()` L253: "_generate_result_message" - snake_case

**详情**:
- 循环复杂度: 平均: 7.2, 最大: 43
- 认知复杂度: 平均: 9.9, 最大: 47
- 嵌套深度: 平均: 1.4, 最大: 4
- 函数长度: 平均: 29.5 行, 最大: 233 行
- 文件长度: 868 代码量 (1038 总计)
- 参数数量: 平均: 2.5, 最大: 12
- 代码重复: 6.5% 重复 (2/31)
- 结构分析: 6 个结构问题
- 错误处理: 4/23 个错误被忽略 (17.4%)
- 注释比例: 4.3% (37/868)
- 命名规范: 发现 19 个违规

### 3. plugins/pipeline.py

**糟糕指数: 41.31**

> 行数: 620 总计, 500 代码, 26 注释 | 函数: 14 | 类: 1

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 🏗️ 结构问题: 6, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L349-619 | 206 | 40 | 5 | 3 | ✓ |
| `run_all` | L444-501 | 58 | 22 | 6 | 0 | ✗ |
| `process` | L151-217 | 67 | 13 | 3 | 2 | ✓ |
| `_synthesize_lines_sync` | L284-337 | 54 | 12 | 3 | 2 | ✓ |
| `_invoke` | L27-56 | 30 | 7 | 2 | 0 | ✗ |
| `_dispatch_pre_process` | L234-271 | 38 | 7 | 1 | 2 | ✓ |
| `_task_completion_llm_reply` | L22-82 | 31 | 6 | 2 | 5 | ✓ |
| `_extract_narrations` | L85-100 | 16 | 4 | 3 | 1 | ✓ |
| `_assemble_prompt` | L219-230 | 12 | 3 | 1 | 2 | ✓ |
| `bridge` | L434-440 | 7 | 3 | 2 | 0 | ✗ |
| `_desc_tool` | L103-108 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L111-118 | 8 | 2 | 1 | 1 | ✗ |
| `__init__` | L135-147 | 13 | 1 | 0 | 6 | ✗ |
| `_synthesize_lines` | L275-282 | 8 | 1 | 0 | 2 | ✓ |

**全部问题 (43)**

- 🔄 `process()` L151: 复杂度: 13
- 🔄 `_synthesize_lines_sync()` L284: 复杂度: 12
- 🔄 `process_stream()` L349: 复杂度: 40
- 🔄 `run_all()` L444: 复杂度: 22
- 🔄 `process()` L151: 认知复杂度: 19
- 🔄 `_synthesize_lines_sync()` L284: 认知复杂度: 18
- 🔄 `process_stream()` L349: 认知复杂度: 50
- 🔄 `run_all()` L444: 认知复杂度: 34
- 🔄 `process_stream()` L349: 嵌套深度: 5
- 🔄 `run_all()` L444: 嵌套深度: 6
- 📏 `process()` L151: 67 代码量
- 📏 `_synthesize_lines_sync()` L284: 54 代码量
- 📏 `process_stream()` L349: 206 代码量
- 📏 `run_all()` L444: 58 代码量
- 📏 `__init__()` L135: 6 参数数量
- 🏗️ `_extract_narrations()` L85: 中等嵌套: 3
- 🏗️ `process()` L151: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L284: 中等嵌套: 3
- 🏗️ `process_stream()` L349: 嵌套过深: 5
- 🏗️ `run_all()` L444: 嵌套过深: 6
- 🏗️ L1: 导入过多: 21
- ❌ L78: 未处理的易出错调用
- ❌ L207: 未处理的易出错调用
- ❌ L440: 未处理的易出错调用
- ❌ L448: 未处理的易出错调用
- ❌ L464: 未处理的易出错调用
- ❌ L491: 未处理的易出错调用
- ❌ L500: 未处理的易出错调用
- ❌ L501: 未处理的易出错调用
- ❌ L533: 未处理的易出错调用
- ❌ L547: 未处理的易出错调用
- ❌ L578: 未处理的易出错调用
- ❌ L614: 未处理的易出错调用
- 🏷️ `_task_completion_llm_reply()` L22: "_task_completion_llm_reply" - snake_case
- 🏷️ `_invoke()` L27: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L85: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L103: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L111: "_desc_task" - snake_case
- 🏷️ `__init__()` L135: "__init__" - snake_case
- 🏷️ `_assemble_prompt()` L219: "_assemble_prompt" - snake_case
- 🏷️ `_dispatch_pre_process()` L234: "_dispatch_pre_process" - snake_case
- 🏷️ `_synthesize_lines()` L275: "_synthesize_lines" - snake_case
- 🏷️ `_synthesize_lines_sync()` L284: "_synthesize_lines_sync" - snake_case

**详情**:
- 循环复杂度: 平均: 8.8, 最大: 40
- 认知复杂度: 平均: 13.1, 最大: 50
- 嵌套深度: 平均: 2.1, 最大: 6
- 函数长度: 平均: 39.6 行, 最大: 206 行
- 文件长度: 500 代码量 (620 总计)
- 参数数量: 平均: 1.9, 最大: 6
- 代码重复: 0.0% 重复 (0/14)
- 结构分析: 6 个结构问题
- 错误处理: 12/30 个错误被忽略 (40.0%)
- 注释比例: 5.2% (26/500)
- 命名规范: 发现 10 个违规

### 4. utils/formatter.py

**糟糕指数: 40.19**

> 行数: 96 总计, 85 代码, 2 注释 | 函数: 1 | 类: 0

**问题**: 🔄 复杂度问题: 3, ⚠️ 其他问题: 1, 🏗️ 结构问题: 1, ❌ 错误处理问题: 8, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `format_tool_result` | L5-95 | 91 | 41 | 4 | 3 | ✓ |

**全部问题 (13)**

- 🔄 `format_tool_result()` L5: 复杂度: 41
- 🔄 `format_tool_result()` L5: 认知复杂度: 49
- 🔄 `format_tool_result()` L5: 嵌套深度: 4
- 📏 `format_tool_result()` L5: 91 代码量
- 🏗️ `format_tool_result()` L5: 中等嵌套: 4
- ❌ L10: 未处理的易出错调用
- ❌ L15: 未处理的易出错调用
- ❌ L16: 未处理的易出错调用
- ❌ L17: 未处理的易出错调用
- ❌ L19: 未处理的易出错调用
- ❌ L26: 未处理的易出错调用
- ❌ L52: 未处理的易出错调用
- ❌ L70: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 41.0, 最大: 41
- 认知复杂度: 平均: 49.0, 最大: 49
- 嵌套深度: 平均: 4.0, 最大: 4
- 函数长度: 平均: 91.0 行, 最大: 91 行
- 文件长度: 85 代码量 (96 总计)
- 参数数量: 平均: 3.0, 最大: 3
- 代码重复: 未发现函数
- 结构分析: 1 个结构问题
- 错误处理: 8/36 个错误被忽略 (22.2%)
- 注释比例: 2.4% (2/85)
- 命名规范: 无命名违规

### 5. main.py

**糟糕指数: 38.47**

> 行数: 1041 总计, 859 代码, 11 注释 | 函数: 37 | 类: 1

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 5, 🏗️ 结构问题: 6, ❌ 错误处理问题: 13, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L915-1036 | 112 | 19 | 3 | 0 | ✗ |
| `_execute_command` | L717-751 | 35 | 18 | 2 | 8 | ✓ |
| `_cmd_memory_list` | L600-674 | 75 | 14 | 2 | 4 | ✓ |
| `_cmd_plugin` | L445-498 | 54 | 11 | 2 | 2 | ✓ |
| `_env_write` | L78-105 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L887-912 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L188-226 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L229-265 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_memory` | L501-525 | 25 | 9 | 2 | 3 | ✓ |
| `_cmd_persona` | L754-785 | 32 | 9 | 1 | 2 | ✓ |
| `_persona_status` | L788-822 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_config` | L306-338 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L528-561 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L564-597 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L677-703 | 27 | 6 | 1 | 2 | ✓ |
| `_env_backup_rotate` | L40-50 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L291-303 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L341-360 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L363-390 | 28 | 5 | 1 | 3 | ✓ |
| `_persona_list` | L853-884 | 32 | 5 | 1 | 1 | ✗ |
| `_env_backup_restore` | L53-67 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L280-288 | 9 | 4 | 2 | 2 | ✗ |
| `_handle_steward_chat` | L993-1002 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L70-75 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L139-149 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L152-157 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L171-185 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L393-409 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L835-846 | 12 | 3 | 2 | 0 | ✗ |
| `append_log` | L108-111 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L114-116 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L119-132 | 12 | 2 | 1 | 0 | ✗ |
| `_persona_distill` | L825-849 | 13 | 2 | 1 | 2 | ✗ |
| `emit` | L126-127 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L412-414 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L417-442 | 26 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L706-714 | 9 | 1 | 0 | 0 | ✓ |

**全部问题 (48)**

- 🔄 `_cmd_plugin()` L445: 复杂度: 11
- 🔄 `_cmd_memory_list()` L600: 复杂度: 14
- 🔄 `_execute_command()` L717: 复杂度: 18
- 🔄 `main()` L915: 复杂度: 19
- 🔄 `_env_write()` L78: 认知复杂度: 20
- 🔄 `_cmd_users()` L188: 认知复杂度: 13
- 🔄 `_cmd_status()` L229: 认知复杂度: 13
- 🔄 `_cmd_plugin()` L445: 认知复杂度: 15
- 🔄 `_cmd_memory()` L501: 认知复杂度: 13
- 🔄 `_cmd_memory_list()` L600: 认知复杂度: 18
- 🔄 `_execute_command()` L717: 认知复杂度: 22
- 🔄 `_persona_status()` L788: 认知复杂度: 14
- 🔄 `_persona_materials()` L887: 认知复杂度: 14
- 🔄 `main()` L915: 认知复杂度: 25
- 🔄 `_env_write()` L78: 嵌套深度: 5
- 📏 `_cmd_plugin()` L445: 54 代码量
- 📏 `_cmd_memory_list()` L600: 75 代码量
- 📏 `main()` L915: 112 代码量
- 📏 `_execute_command()` L717: 8 参数数量
- 🏗️ `_env_backup_rotate()` L40: 中等嵌套: 3
- 🏗️ `_env_write()` L78: 嵌套过深: 5
- 🏗️ `_persona_status()` L788: 中等嵌套: 3
- 🏗️ `main()` L915: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1041 行
- 🏗️ L1: 导入过多: 21
- ❌ L214: 未处理的易出错调用
- ❌ L222: 未处理的易出错调用
- ❌ L493: 未处理的易出错调用
- ❌ L657: 未处理的易出错调用
- ❌ L667: 未处理的易出错调用
- ❌ L668: 未处理的易出错调用
- ❌ L669: 未处理的易出错调用
- ❌ L670: 未处理的易出错调用
- ❌ L671: 未处理的易出错调用
- ❌ L820: 未处理的易出错调用
- ❌ L875: 未处理的易出错调用
- ❌ L876: 未处理的易出错调用
- ❌ L877: 未处理的易出错调用
- 🏷️ `_env_backup_rotate()` L40: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L53: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L70: "_env_backup_count" - snake_case
- 🏷️ `_env_write()` L78: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L119: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L139: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L152: "_disable_console_logging" - snake_case
- 🏷️ `_cmd_newbind()` L171: "_cmd_newbind" - snake_case
- 🏷️ `_cmd_users()` L188: "_cmd_users" - snake_case
- 🏷️ `_cmd_status()` L229: "_cmd_status" - snake_case

**详情**:
- 循环复杂度: 平均: 5.9, 最大: 19
- 认知复杂度: 平均: 9.1, 最大: 25
- 嵌套深度: 平均: 1.6, 最大: 5
- 函数长度: 平均: 24.4 行, 最大: 112 行
- 文件长度: 859 代码量 (1041 总计)
- 参数数量: 平均: 1.5, 最大: 8
- 代码重复: 0.0% 重复 (0/37)
- 结构分析: 6 个结构问题
- 错误处理: 13/30 个错误被忽略 (43.3%)
- 注释比例: 1.3% (11/859)
- 命名规范: 发现 34 个违规

### 6. psychoscope/static/js/app.js

**糟糕指数: 34.22**

> 行数: 1338 总计, 1217 代码, 40 注释 | 函数: 53 | 类: 0

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 31, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `msgFlow` | L750-880 | 131 | 38 | 4 | 1 | ✗ |
| `sendRecording` | L640-744 | 105 | 36 | 4 | 2 | ✗ |
| `init` | L1307-1335 | 29 | 10 | 2 | 0 | ✓ |
| `selectChat` | L422-465 | 44 | 8 | 4 | 1 | ✗ |
| `tryPairLogin` | L347-366 | 20 | 7 | 1 | 0 | ✗ |
| `showTimingLine` | L970-988 | 19 | 7 | 2 | 2 | ✗ |
| `showKeyHints` | L1160-1214 | 55 | 7 | 1 | 0 | ✗ |
| `describeAction` | L188-202 | 15 | 6 | 1 | 2 | ✗ |
| `addMessage` | L267-305 | 39 | 6 | 2 | 3 | ✗ |
| `processLineQueue` | L942-968 | 27 | 6 | 2 | 0 | ✗ |
| `parseControlTags` | L166-186 | 21 | 5 | 4 | 1 | ✗ |
| `startRecording` | L523-544 | 22 | 5 | 1 | 0 | ✗ |
| `stopRecording` | L546-565 | 20 | 5 | 2 | 1 | ✗ |
| `startWaveform` | L587-617 | 31 | 5 | 1 | 0 | ✗ |
| `getAuthHeader` | L308-313 | 6 | 4 | 1 | 0 | ✓ |
| `tryRecoverLogin` | L368-387 | 20 | 4 | 1 | 0 | ✗ |
| `abortStream` | L896-906 | 11 | 4 | 1 | 0 | ✗ |
| `playAudioBase64Wait` | L926-940 | 15 | 4 | 1 | 1 | ✗ |
| `showConfirm` | L1250-1275 | 26 | 4 | 1 | 0 | ✗ |
| `detectTheme` | L10-14 | 5 | 3 | 1 | 0 | ✓ |
| `apiCall` | L314-319 | 6 | 3 | 1 | 3 | ✗ |
| `apiGet` | L320-328 | 9 | 3 | 1 | 1 | ✗ |
| `apiPost` | L331-336 | 6 | 3 | 1 | 2 | ✓ |
| `apiPostJson` | L337-345 | 9 | 3 | 1 | 2 | ✗ |
| `renderChatList` | L407-421 | 15 | 3 | 1 | 0 | ✗ |
| `handleImageSelected` | L480-492 | 13 | 3 | 1 | 1 | ✗ |
| `switchInputMode` | L504-521 | 18 | 3 | 1 | 1 | ✓ |
| `stopWaveform` | L619-627 | 9 | 3 | 1 | 0 | ✗ |
| `playAudioBase64` | L914-924 | 11 | 3 | 1 | 1 | ✗ |
| `hideConfirm` | L1277-1292 | 16 | 3 | 1 | 0 | ✗ |
| `toggleTheme` | L19-21 | 3 | 2 | 0 | 0 | ✗ |
| `addLineStatic` | L232-247 | 16 | 2 | 1 | 3 | ✗ |
| `newChat` | L466-473 | 8 | 2 | 1 | 0 | ✗ |
| `removeImage` | L494-501 | 8 | 2 | 1 | 0 | ✗ |
| `cancelRecording` | L567-575 | 9 | 2 | 1 | 0 | ✗ |
| `uncancelRecording` | L577-585 | 9 | 2 | 1 | 0 | ✗ |
| `sendMessage` | L882-894 | 13 | 2 | 1 | 0 | ✗ |
| `toggleTTS` | L909-913 | 5 | 2 | 0 | 0 | ✓ |
| `hideKeyHints` | L1216-1224 | 9 | 2 | 1 | 0 | ✗ |
| `applyTheme` | L15-18 | 4 | 1 | 0 | 1 | ✗ |
| `archiveActiveLines` | L205-211 | 7 | 1 | 0 | 0 | ✓ |
| `addNarrationLine` | L213-220 | 8 | 1 | 0 | 1 | ✗ |
| `addNarratorLine` | L222-230 | 9 | 1 | 0 | 1 | ✗ |
| `addSystemLine` | L249-256 | 8 | 1 | 0 | 1 | ✗ |
| `addErrorLine` | L258-265 | 8 | 1 | 0 | 1 | ✗ |
| `logout` | L389-400 | 12 | 1 | 0 | 0 | ✗ |
| `loadChats` | L403-406 | 4 | 1 | 0 | 0 | ✓ |
| `selectImage` | L476-478 | 3 | 1 | 0 | 0 | ✓ |
| `blobToBase64` | L629-638 | 10 | 1 | 0 | 1 | ✗ |
| `updateStatusBar` | L991-994 | 4 | 1 | 0 | 0 | ✓ |
| `updateStatusBarText` | L995-997 | 3 | 1 | 0 | 1 | ✗ |
| `createKeyCapSVG` | L1144-1154 | 11 | 1 | 0 | 1 | ✓ |
| `doConfirm` | L1294-1298 | 5 | 1 | 0 | 0 | ✗ |

**全部问题 (48)**

- 🔄 `sendRecording()` L640: 复杂度: 36
- 🔄 `msgFlow()` L750: 复杂度: 38
- 🔄 `selectChat()` L422: 认知复杂度: 16
- 🔄 `sendRecording()` L640: 认知复杂度: 44
- 🔄 `msgFlow()` L750: 认知复杂度: 46
- 🔄 `parseControlTags()` L166: 嵌套深度: 4
- 🔄 `selectChat()` L422: 嵌套深度: 4
- 🔄 `sendRecording()` L640: 嵌套深度: 4
- 🔄 `msgFlow()` L750: 嵌套深度: 4
- 📏 `sendRecording()` L640: 105 代码量
- 📏 `msgFlow()` L750: 131 代码量
- 🏗️ `parseControlTags()` L166: 中等嵌套: 4
- 🏗️ `selectChat()` L422: 中等嵌套: 4
- 🏗️ `sendRecording()` L640: 中等嵌套: 4
- 🏗️ `msgFlow()` L750: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1338 行
- 🏗️ L1: 函数过多: 53
- ❌ L146: 未处理的易出错调用
- ❌ L208: 未处理的易出错调用
- ❌ L395: 未处理的易出错调用
- ❌ L398: 未处理的易出错调用
- ❌ L427: 未处理的易出错调用
- ❌ L451: 未处理的易出错调用
- ❌ L470: 未处理的易出错调用
- ❌ L487: 未处理的易出错调用
- ❌ L498: 未处理的易出错调用
- ❌ L509: 未处理的易出错调用
- ❌ L515: 未处理的易出错调用
- ❌ L516: 未处理的易出错调用
- ❌ L562: 未处理的易出错调用
- ❌ L563: 未处理的易出错调用
- ❌ L571: 未处理的易出错调用
- ❌ L573: 未处理的易出错调用
- ❌ L580: 未处理的易出错调用
- ❌ L582: 未处理的易出错调用
- ❌ L665: 未处理的易出错调用
- ❌ L739: 未处理的易出错调用
- ❌ L778: 未处理的易出错调用
- ❌ L876: 未处理的易出错调用
- ❌ L902: 未处理的易出错调用
- ❌ L1007: 未处理的易出错调用
- ❌ L1221: 未处理的易出错调用
- ❌ L1222: 未处理的易出错调用
- ❌ L1253: 未处理的易出错调用
- ❌ L1256: 未处理的易出错调用
- ❌ L1280: 未处理的易出错调用
- ❌ L1282: 未处理的易出错调用
- ❌ L1287: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 4.5, 最大: 38
- 认知复杂度: 平均: 6.5, 最大: 46
- 嵌套深度: 平均: 1.0, 最大: 4
- 函数长度: 平均: 17.9 行, 最大: 131 行
- 文件长度: 1217 代码量 (1338 总计)
- 参数数量: 平均: 0.7, 最大: 3
- 代码重复: 3.8% 重复 (2/53)
- 结构分析: 6 个结构问题
- 错误处理: 31/49 个错误被忽略 (63.3%)
- 注释比例: 3.3% (40/1217)
- 命名规范: 无命名违规

### 7. plugins/builtin/agent_plugin.py

**糟糕指数: 33.79**

> 行数: 321 总计, 254 代码, 10 注释 | 函数: 8 | 类: 1

**问题**: 🔄 复杂度问题: 7, ⚠️ 其他问题: 3, 🏗️ 结构问题: 3, ❌ 错误处理问题: 17, 📝 注释问题: 1, 🏷️ 命名问题: 6

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_run_agent_loop` | L107-194 | 88 | 21 | 3 | 2 | ✓ |
| `_format_tool_result` | L261-320 | 60 | 21 | 4 | 3 | ✓ |
| `_execute_tools` | L198-238 | 41 | 14 | 2 | 3 | ✓ |
| `_extract_impressions` | L240-258 | 19 | 6 | 3 | 3 | ✓ |
| `_run_single_pass` | L84-103 | 20 | 5 | 1 | 2 | ✓ |
| `on_hook` | L71-80 | 10 | 4 | 1 | 3 | ✗ |
| `on_load` | L65-69 | 5 | 3 | 1 | 1 | ✗ |
| `__init__` | L47-63 | 17 | 1 | 0 | 8 | ✗ |

**全部问题 (36)**

- 🔄 `_run_agent_loop()` L107: 复杂度: 21
- 🔄 `_execute_tools()` L198: 复杂度: 14
- 🔄 `_format_tool_result()` L261: 复杂度: 21
- 🔄 `_run_agent_loop()` L107: 认知复杂度: 27
- 🔄 `_execute_tools()` L198: 认知复杂度: 18
- 🔄 `_format_tool_result()` L261: 认知复杂度: 29
- 🔄 `_format_tool_result()` L261: 嵌套深度: 4
- 📏 `_run_agent_loop()` L107: 88 代码量
- 📏 `_format_tool_result()` L261: 60 代码量
- 📏 `__init__()` L47: 8 参数数量
- 🏗️ `_run_agent_loop()` L107: 中等嵌套: 3
- 🏗️ `_extract_impressions()` L240: 中等嵌套: 3
- 🏗️ `_format_tool_result()` L261: 中等嵌套: 4
- ❌ L137: 未处理的易出错调用
- ❌ L164: 未处理的易出错调用
- ❌ L266: 未处理的易出错调用
- ❌ L272: 未处理的易出错调用
- ❌ L273: 未处理的易出错调用
- ❌ L274: 未处理的易出错调用
- ❌ L276: 未处理的易出错调用
- ❌ L283: 未处理的易出错调用
- ❌ L292: 未处理的易出错调用
- ❌ L293: 未处理的易出错调用
- ❌ L297: 未处理的易出错调用
- ❌ L298: 未处理的易出错调用
- ❌ L303: 未处理的易出错调用
- ❌ L305: 未处理的易出错调用
- ❌ L306: 未处理的易出错调用
- ❌ L307: 未处理的易出错调用
- ❌ L311: 未处理的易出错调用
- 🏷️ `__init__()` L47: "__init__" - snake_case
- 🏷️ `_run_single_pass()` L84: "_run_single_pass" - snake_case
- 🏷️ `_run_agent_loop()` L107: "_run_agent_loop" - snake_case
- 🏷️ `_execute_tools()` L198: "_execute_tools" - snake_case
- 🏷️ `_extract_impressions()` L240: "_extract_impressions" - snake_case
- 🏷️ `_format_tool_result()` L261: "_format_tool_result" - snake_case

**详情**:
- 循环复杂度: 平均: 9.4, 最大: 21
- 认知复杂度: 平均: 13.1, 最大: 29
- 嵌套深度: 平均: 1.9, 最大: 4
- 函数长度: 平均: 32.5 行, 最大: 88 行
- 文件长度: 254 代码量 (321 总计)
- 参数数量: 平均: 3.1, 最大: 8
- 代码重复: 0.0% 重复 (0/8)
- 结构分析: 3 个结构问题
- 错误处理: 17/34 个错误被忽略 (50.0%)
- 注释比例: 3.9% (10/254)
- 命名规范: 发现 6 个违规

### 8. tasks.py

**糟糕指数: 33.36**

> 行数: 868 总计, 637 代码, 84 注释 | 函数: 30 | 类: 6

**问题**: 🔄 复杂度问题: 6, ⚠️ 其他问题: 6, 🏗️ 结构问题: 4, ❌ 错误处理问题: 17, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_execute_action_task` | L518-683 | 166 | 21 | 4 | 2 | ✓ |
| `_load_persistent_tasks` | L207-254 | 48 | 9 | 4 | 1 | ✓ |
| `_save_task` | L256-291 | 36 | 8 | 2 | 2 | ✓ |
| `analyze_complexity` | L785-851 | 67 | 8 | 1 | 3 | ✓ |
| `_update_task_status` | L293-311 | 19 | 7 | 3 | 5 | ✓ |
| `from_dict` | L95-121 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_task_internal` | L413-428 | 16 | 6 | 2 | 2 | ✓ |
| `create_task` | L348-375 | 28 | 5 | 1 | 7 | ✓ |
| `cancel_task` | L737-757 | 21 | 5 | 2 | 2 | ✓ |
| `to_dict` | L76-92 | 17 | 4 | 0 | 1 | ✓ |
| `_schedule_reminder_task` | L313-339 | 22 | 3 | 1 | 2 | ✓ |
| `_run_scheduler` | L341-346 | 6 | 3 | 1 | 1 | ✓ |
| `get_user_tasks` | L726-735 | 10 | 3 | 2 | 3 | ✓ |
| `get_task_manager` | L857-862 | 6 | 3 | 1 | 1 | ✓ |
| `_init_db` | L151-205 | 55 | 2 | 1 | 1 | ✓ |
| `execute_task` | L377-393 | 17 | 2 | 1 | 2 | ✓ |
| `execute_action_sync` | L395-411 | 17 | 2 | 1 | 4 | ✓ |
| `_execute_reasoner_task` | L430-473 | 44 | 2 | 0 | 2 | ✓ |
| `_save_task_result` | L685-696 | 12 | 2 | 1 | 3 | ✓ |
| `_handle_task_result` | L698-710 | 13 | 2 | 1 | 3 | ✓ |
| `_notify_task_completion` | L712-719 | 8 | 2 | 1 | 3 | ✓ |
| `get_task` | L721-724 | 4 | 2 | 1 | 2 | ✓ |
| `__init__` | L52-74 | 23 | 1 | 0 | 8 | ✗ |
| `__init__` | L127-149 | 23 | 1 | 0 | 3 | ✗ |
| `reminder_job` | L324-328 | 5 | 1 | 0 | 0 | ✗ |
| `_execute_reminder_task` | L475-499 | 25 | 1 | 0 | 2 | ✓ |
| `_execute_analysis_task` | L501-516 | 16 | 1 | 0 | 2 | ✓ |
| `shutdown` | L759-763 | 5 | 1 | 0 | 1 | ✓ |
| `__init__` | L769-783 | 15 | 1 | 0 | 1 | ✗ |
| `set_task_manager` | L864-867 | 4 | 1 | 0 | 1 | ✓ |

**全部问题 (42)**

- 🔄 `_execute_action_task()` L518: 复杂度: 21
- 🔄 `_load_persistent_tasks()` L207: 认知复杂度: 17
- 🔄 `_update_task_status()` L293: 认知复杂度: 13
- 🔄 `_execute_action_task()` L518: 认知复杂度: 29
- 🔄 `_load_persistent_tasks()` L207: 嵌套深度: 4
- 🔄 `_execute_action_task()` L518: 嵌套深度: 4
- 📏 `_init_db()` L151: 55 代码量
- 📏 `_execute_action_task()` L518: 166 代码量
- 📏 `analyze_complexity()` L785: 67 代码量
- 📏 `__init__()` L52: 8 参数数量
- 📏 `create_task()` L348: 7 参数数量
- 🏗️ `_load_persistent_tasks()` L207: 中等嵌套: 4
- 🏗️ `_update_task_status()` L293: 中等嵌套: 3
- 🏗️ `_execute_action_task()` L518: 中等嵌套: 4
- 🏗️ L1: 导入过多: 21
- ❌ L115: 未处理的易出错调用
- ❌ L117: 未处理的易出错调用
- ❌ L156: 未处理的易出错调用
- ❌ L176: 未处理的易出错调用
- ❌ L187: 未处理的易出错调用
- ❌ L200: 未处理的易出错调用
- ❌ L204: 未处理的易出错调用
- ❌ L268: 未处理的易出错调用
- ❌ L288: 未处理的易出错调用
- ❌ L291: 未处理的易出错调用
- ❌ L565: 未处理的易出错调用
- ❌ L617: 未处理的易出错调用
- ❌ L658: 未处理的易出错调用
- ❌ L689: 未处理的易出错调用
- ❌ L693: 未处理的易出错调用
- ❌ L696: 未处理的易出错调用
- ❌ L719: 未处理的易出错调用
- 🏷️ `__init__()` L52: "__init__" - snake_case
- 🏷️ `__init__()` L127: "__init__" - snake_case
- 🏷️ `_init_db()` L151: "_init_db" - snake_case
- 🏷️ `_load_persistent_tasks()` L207: "_load_persistent_tasks" - snake_case
- 🏷️ `_save_task()` L256: "_save_task" - snake_case
- 🏷️ `_update_task_status()` L293: "_update_task_status" - snake_case
- 🏷️ `_schedule_reminder_task()` L313: "_schedule_reminder_task" - snake_case
- 🏷️ `_run_scheduler()` L341: "_run_scheduler" - snake_case
- 🏷️ `_execute_task_internal()` L413: "_execute_task_internal" - snake_case
- 🏷️ `_execute_reasoner_task()` L430: "_execute_reasoner_task" - snake_case

**详情**:
- 循环复杂度: 平均: 3.8, 最大: 21
- 认知复杂度: 平均: 6.0, 最大: 29
- 嵌套深度: 平均: 1.1, 最大: 4
- 函数长度: 平均: 25.8 行, 最大: 166 行
- 文件长度: 637 代码量 (868 总计)
- 参数数量: 平均: 2.4, 最大: 8
- 代码重复: 0.0% 重复 (0/30)
- 结构分析: 4 个结构问题
- 错误处理: 17/40 个错误被忽略 (42.5%)
- 注释比例: 13.2% (84/637)
- 命名规范: 发现 17 个违规

### 9. tests/test_ncm_music.py

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

### 10. models.py

**糟糕指数: 24.27**

> 行数: 523 总计, 434 代码, 11 注释 | 函数: 28 | 类: 3

**问题**: 🔄 复杂度问题: 6, ⚠️ 其他问题: 7, 📋 重复问题: 3, 🏗️ 结构问题: 2, ❌ 错误处理问题: 2, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_llm` | L412-454 | 43 | 15 | 4 | 7 | ✓ |
| `_call_and_append` | L90-147 | 58 | 9 | 2 | 1 | ✓ |
| `__init__` | L386-410 | 25 | 7 | 1 | 8 | ✗ |
| `_is_no_model_error` | L247-255 | 9 | 6 | 1 | 1 | ✓ |
| `_call_chat_api` | L259-277 | 19 | 6 | 4 | 2 | ✓ |
| `describe_image` | L339-371 | 33 | 6 | 1 | 5 | ✓ |
| `_is_no_model_error` | L500-508 | 9 | 6 | 1 | 1 | ✓ |
| `__init__` | L26-76 | 51 | 5 | 1 | 8 | ✓ |
| `summarize_text` | L456-477 | 22 | 5 | 1 | 3 | ✓ |
| `summarize_dialog` | L510-522 | 13 | 5 | 2 | 3 | ✓ |
| `__init__` | L186-221 | 36 | 4 | 1 | 7 | ✓ |
| `send_message` | L279-286 | 8 | 4 | 1 | 2 | ✓ |
| `send_message` | L78-84 | 7 | 3 | 1 | 2 | ✓ |
| `_ensure_model_loaded` | L223-244 | 22 | 3 | 1 | 1 | ✓ |
| `_call_and_append` | L292-310 | 19 | 3 | 1 | 1 | ✗ |
| `_auto_load_model` | L479-497 | 19 | 3 | 1 | 1 | ✓ |
| `continue_conversation` | L86-88 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L149-152 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L154-160 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L162-169 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L171-174 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L176-177 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L288-290 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L312-315 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L317-323 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L325-332 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L334-337 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L373-374 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (29)**

- 🔄 `_call_llm()` L412: 复杂度: 15
- 🔄 `_call_and_append()` L90: 认知复杂度: 13
- 🔄 `_call_chat_api()` L259: 认知复杂度: 14
- 🔄 `_call_llm()` L412: 认知复杂度: 23
- 🔄 `_call_chat_api()` L259: 嵌套深度: 4
- 🔄 `_call_llm()` L412: 嵌套深度: 4
- 📏 `__init__()` L26: 51 代码量
- 📏 `_call_and_append()` L90: 58 代码量
- 📏 `__init__()` L26: 8 参数数量
- 📏 `__init__()` L186: 7 参数数量
- 📏 `__init__()` L386: 8 参数数量
- 📏 `_call_llm()` L412: 7 参数数量
- 📋 `_ensure_model_loaded()` L223: 重复模式: _ensure_model_loaded, _auto_load_model
- 📋 `_is_no_model_error()` L247: 重复模式: _is_no_model_error, _is_no_model_error
- 📋 `_call_chat_api()` L259: 重复模式: _call_chat_api, _call_llm
- 🏗️ `_call_chat_api()` L259: 中等嵌套: 4
- 🏗️ `_call_llm()` L412: 中等嵌套: 4
- ❌ L240: 未处理的易出错调用
- ❌ L493: 未处理的易出错调用
- 🏷️ `__init__()` L26: "__init__" - snake_case
- 🏷️ `_call_and_append()` L90: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L176: "__repr__" - snake_case
- 🏷️ `__init__()` L186: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L223: "_ensure_model_loaded" - snake_case
- 🏷️ `_is_no_model_error()` L247: "_is_no_model_error" - snake_case
- 🏷️ `_call_chat_api()` L259: "_call_chat_api" - snake_case
- 🏷️ `_call_and_append()` L292: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L373: "__repr__" - snake_case
- 🏷️ `__init__()` L386: "__init__" - snake_case

**详情**:
- 循环复杂度: 平均: 3.6, 最大: 15
- 认知复杂度: 平均: 5.4, 最大: 23
- 嵌套深度: 平均: 0.9, 最大: 4
- 函数长度: 平均: 16.0 行, 最大: 58 行
- 文件长度: 434 代码量 (523 总计)
- 参数数量: 平均: 2.5, 最大: 8
- 代码重复: 10.7% 重复 (3/28)
- 结构分析: 2 个结构问题
- 错误处理: 2/16 个错误被忽略 (12.5%)
- 注释比例: 2.5% (11/434)
- 命名规范: 发现 13 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `create_engine_with_defaults` | engine.py | 43 | 2 | 233 |
| `format_tool_result` | utils/formatter.py | 41 | 4 | 91 |
| `process_stream` | plugins/pipeline.py | 40 | 5 | 206 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `_init_plugins` | engine.py | 37 | 2 | 173 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `search_memories` | chatdbmgr.py | 22 | 5 | 83 |
| `run_all` | plugins/pipeline.py | 22 | 6 | 58 |
| `_execute_action_task` | tasks.py | 21 | 4 | 166 |
| `_run_agent_loop` | plugins/builtin/agent_plugin.py | 21 | 3 | 88 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*