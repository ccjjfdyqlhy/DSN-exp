# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-83%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **83.26/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 136 |
| 已跳过 | 566 |
| 耗时 | 748ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 22587 |
| 总注释行数 | 1181 |
| 整体注释比例 | 5.2% |
| 平均文件大小 | 209 行 |
| 最大文件 | `psychoscope/static/js/app.js` (1453) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 134 |
| JavaScript | 2 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 8.81% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 12.70% | 0.0% | 67.0% | 8.0% | ✓✓ |
| 嵌套深度 | 2.76% | 0.0% | 37.5% | 0.0% | ✓✓ |
| 函数长度 | 5.58% | 0.0% | 49.8% | 0.6% | ✓✓ |
| 文件长度 | 2.38% | 0.0% | 88.3% | 0.0% | ✓✓ |
| 参数数量 | 14.09% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 4.12% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.04% | 0.0% | 40.5% | 0.0% | ✓✓ |
| 错误处理 | 32.62% | 0.0% | 98.8% | 6.1% | ✓ |
| 注释比例 | 35.36% | 0.0% | 100.0% | 28.8% | ○ |
| 命名规范 | 26.82% | 0.0% | 94.7% | 22.6% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. engine.py

**糟糕指数: 44.12**

> 行数: 1010 总计, 869 代码, 18 注释 | 函数: 38 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 📋 重复问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L777-1009 | 233 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L412-452 | 41 | 16 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L539-580 | 42 | 11 | 2 | 1 | ✗ |
| `_register_personality_plugins` | L517-537 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L582-602 | 21 | 9 | 2 | 1 | ✗ |
| `build_context` | L615-645 | 31 | 9 | 1 | 8 | ✓ |
| `chat` | L647-683 | 37 | 9 | 2 | 8 | ✓ |
| `chat_stream` | L685-704 | 20 | 8 | 1 | 8 | ✓ |
| `_generate_result_message` | L255-292 | 38 | 7 | 2 | 3 | ✗ |
| `_register_context_plugins` | L499-515 | 17 | 7 | 1 | 1 | ✗ |
| `run_scheduled` | L714-751 | 31 | 7 | 2 | 1 | ✓ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_handle_engine_action_completion` | L214-228 | 15 | 6 | 2 | 4 | ✗ |
| `_retry_engine_action` | L294-315 | 22 | 6 | 2 | 4 | ✗ |
| `_init_world` | L335-360 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L380-396 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L398-410 | 13 | 6 | 3 | 1 | ✓ |
| `get_info` | L755-763 | 9 | 6 | 0 | 1 | ✗ |
| `_process_task_completion` | L186-200 | 15 | 5 | 3 | 1 | ✗ |
| `_dispatch_task_completion` | L202-212 | 11 | 5 | 2 | 3 | ✗ |
| `_init_memory` | L317-333 | 17 | 4 | 1 | 1 | ✗ |
| `from_subapp` | L74-90 | 17 | 3 | 0 | 1 | ✗ |
| `__init__` | L104-135 | 32 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L163-182 | 20 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L241-253 | 13 | 3 | 1 | 3 | ✗ |
| `_init_tts` | L362-378 | 17 | 3 | 2 | 1 | ✗ |
| `_init_plugins` | L454-464 | 11 | 3 | 0 | 1 | ✗ |
| `_plugin_enabled` | L466-471 | 6 | 3 | 1 | 2 | ✗ |
| `_init_database` | L156-161 | 6 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L230-239 | 10 | 2 | 1 | 3 | ✗ |
| `_register_filter_plugins` | L473-480 | 8 | 2 | 1 | 1 | ✗ |
| `_register_model_plugin` | L482-497 | 16 | 2 | 1 | 1 | ✗ |
| `create_chat` | L706-707 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L709-710 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L726-732 | 7 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L139-154 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L604-611 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L768-774 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (38)**

- 🔄 `_init_prompt()` L412: 复杂度: 16
- 🔄 `_register_execution_plugins()` L539: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L777: 复杂度: 43
- 🔄 `_init_prompt()` L412: 认知复杂度: 24
- 🔄 `_register_personality_plugins()` L517: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L539: 认知复杂度: 15
- 🔄 `_register_output_plugins()` L582: 认知复杂度: 13
- 🔄 `chat()` L647: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L777: 认知复杂度: 47
- 🔄 `_init_prompt()` L412: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L777: 233 代码量
- 📏 `build_context()` L615: 8 参数数量
- 📏 `chat()` L647: 8 参数数量
- 📏 `chat_stream()` L685: 8 参数数量
- 📏 `create_engine_with_defaults()` L777: 12 参数数量
- 📋 `_init_database()` L156: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L241: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 📋 `_init_tts()` L362: 重复模式: _init_tts, _register_output_plugins
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L186: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L398: 中等嵌套: 3
- 🏗️ `_init_prompt()` L412: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1010 行
- 🏗️ L1: 导入过多: 79
- ❌ L215: 未处理的易出错调用
- ❌ L225: 未处理的易出错调用
- ❌ L271: 未处理的易出错调用
- ❌ L730: 未处理的易出错调用
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
- 循环复杂度: 平均: 6.0, 最大: 43
- 认知复杂度: 平均: 8.7, 最大: 47
- 嵌套深度: 平均: 1.3, 最大: 4
- 函数长度: 平均: 23.2 行, 最大: 233 行
- 文件长度: 869 代码量 (1010 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 13.2% 重复 (5/38)
- 结构分析: 6 个结构问题
- 错误处理: 4/23 个错误被忽略 (17.4%)
- 注释比例: 2.1% (18/869)
- 命名规范: 发现 27 个违规

### 2. plugins/pipeline.py

**糟糕指数: 38.28**

> 行数: 614 总计, 496 代码, 25 注释 | 函数: 15 | 类: 1

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 5, 🏗️ 结构问题: 6, ❌ 错误处理问题: 12, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L411-613 | 203 | 40 | 5 | 3 | ✓ |
| `_poll_pending_tasks` | L370-399 | 30 | 18 | 5 | 4 | ✗ |
| `process` | L151-217 | 67 | 13 | 3 | 2 | ✓ |
| `_synthesize_lines_sync` | L284-337 | 54 | 12 | 3 | 2 | ✓ |
| `_invoke` | L27-56 | 30 | 7 | 2 | 0 | ✗ |
| `_dispatch_pre_process` | L234-271 | 38 | 7 | 1 | 2 | ✓ |
| `_run_all_plugins` | L348-368 | 21 | 7 | 2 | 5 | ✗ |
| `_task_completion_llm_reply` | L22-82 | 31 | 6 | 2 | 5 | ✓ |
| `_extract_narrations` | L85-100 | 16 | 4 | 3 | 1 | ✓ |
| `_assemble_prompt` | L219-230 | 12 | 3 | 1 | 2 | ✓ |
| `_bridge_progress` | L340-346 | 7 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L103-108 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L111-118 | 8 | 2 | 1 | 1 | ✗ |
| `__init__` | L135-147 | 13 | 1 | 0 | 6 | ✗ |
| `_synthesize_lines` | L275-282 | 8 | 1 | 0 | 2 | ✓ |

**全部问题 (42)**

- 🔄 `process()` L151: 复杂度: 13
- 🔄 `_synthesize_lines_sync()` L284: 复杂度: 12
- 🔄 `_poll_pending_tasks()` L370: 复杂度: 18
- 🔄 `process_stream()` L411: 复杂度: 40
- 🔄 `process()` L151: 认知复杂度: 19
- 🔄 `_synthesize_lines_sync()` L284: 认知复杂度: 18
- 🔄 `_poll_pending_tasks()` L370: 认知复杂度: 28
- 🔄 `process_stream()` L411: 认知复杂度: 50
- 🔄 `_poll_pending_tasks()` L370: 嵌套深度: 5
- 🔄 `process_stream()` L411: 嵌套深度: 5
- 📏 `process()` L151: 67 代码量
- 📏 `_synthesize_lines_sync()` L284: 54 代码量
- 📏 `process_stream()` L411: 203 代码量
- 📏 `__init__()` L135: 6 参数数量
- 🏗️ `_extract_narrations()` L85: 中等嵌套: 3
- 🏗️ `process()` L151: 中等嵌套: 3
- 🏗️ `_synthesize_lines_sync()` L284: 中等嵌套: 3
- 🏗️ `_poll_pending_tasks()` L370: 嵌套过深: 5
- 🏗️ `process_stream()` L411: 嵌套过深: 5
- 🏗️ L1: 导入过多: 21
- ❌ L78: 未处理的易出错调用
- ❌ L207: 未处理的易出错调用
- ❌ L346: 未处理的易出错调用
- ❌ L352: 未处理的易出错调用
- ❌ L367: 未处理的易出错调用
- ❌ L368: 未处理的易出错调用
- ❌ L373: 未处理的易出错调用
- ❌ L395: 未处理的易出错调用
- ❌ L528: 未处理的易出错调用
- ❌ L542: 未处理的易出错调用
- ❌ L572: 未处理的易出错调用
- ❌ L608: 未处理的易出错调用
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
- 循环复杂度: 平均: 8.4, 最大: 40
- 认知复杂度: 平均: 12.5, 最大: 50
- 嵌套深度: 平均: 2.1, 最大: 5
- 函数长度: 平均: 36.3 行, 最大: 203 行
- 文件长度: 496 代码量 (614 总计)
- 参数数量: 平均: 2.5, 最大: 6
- 代码重复: 0.0% 重复 (0/15)
- 结构分析: 6 个结构问题
- 错误处理: 12/32 个错误被忽略 (37.5%)
- 注释比例: 5.0% (25/496)
- 命名规范: 发现 13 个违规

### 3. main.py

**糟糕指数: 37.63**

> 行数: 1073 总计, 876 代码, 11 注释 | 函数: 47 | 类: 1

**问题**: 🔄 复杂度问题: 13, ⚠️ 其他问题: 15, 🏗️ 结构问题: 6, ❌ 错误处理问题: 13, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L947-1068 | 112 | 19 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L606-680 | 75 | 14 | 2 | 4 | ✓ |
| `_cmd_plugin` | L451-504 | 54 | 11 | 2 | 2 | ✓ |
| `_env_write` | L84-111 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L919-944 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L194-232 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L235-271 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_memory` | L507-531 | 25 | 9 | 2 | 3 | ✓ |
| `_cmd_persona` | L786-817 | 32 | 9 | 1 | 2 | ✓ |
| `_persona_status` | L820-854 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_config` | L312-344 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L534-567 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L570-603 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L683-709 | 27 | 6 | 1 | 2 | ✓ |
| `_env_backup_rotate` | L46-56 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L297-309 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L347-366 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L369-396 | 28 | 5 | 1 | 3 | ✓ |
| `_execute_command` | L723-738 | 16 | 5 | 2 | 8 | ✗ |
| `_persona_list` | L885-916 | 32 | 5 | 1 | 1 | ✗ |
| `_env_backup_restore` | L59-73 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L286-294 | 9 | 4 | 2 | 2 | ✗ |
| `_handle_steward_chat` | L1025-1034 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L76-81 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L145-155 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L158-163 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L177-191 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L399-415 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L867-878 | 12 | 3 | 2 | 0 | ✗ |
| `append_log` | L114-117 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L120-122 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L125-138 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L750-751 | 2 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L857-881 | 13 | 2 | 1 | 2 | ✗ |
| `emit` | L132-133 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L418-420 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L423-448 | 26 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L712-720 | 9 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L741-742 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L744-745 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L747-748 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L753-754 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L756-757 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L759-760 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L762-763 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L765-766 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L768-769 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (56)**

- 🔄 `_cmd_plugin()` L451: 复杂度: 11
- 🔄 `_cmd_memory_list()` L606: 复杂度: 14
- 🔄 `main()` L947: 复杂度: 19
- 🔄 `_env_write()` L84: 认知复杂度: 20
- 🔄 `_cmd_users()` L194: 认知复杂度: 13
- 🔄 `_cmd_status()` L235: 认知复杂度: 13
- 🔄 `_cmd_plugin()` L451: 认知复杂度: 15
- 🔄 `_cmd_memory()` L507: 认知复杂度: 13
- 🔄 `_cmd_memory_list()` L606: 认知复杂度: 18
- 🔄 `_persona_status()` L820: 认知复杂度: 14
- 🔄 `_persona_materials()` L919: 认知复杂度: 14
- 🔄 `main()` L947: 认知复杂度: 25
- 🔄 `_env_write()` L84: 嵌套深度: 5
- 📏 `_cmd_plugin()` L451: 54 代码量
- 📏 `_cmd_memory_list()` L606: 75 代码量
- 📏 `main()` L947: 112 代码量
- 📏 `_execute_command()` L723: 8 参数数量
- 📏 `_h_newbind()` L741: 7 参数数量
- 📏 `_h_users()` L744: 7 参数数量
- 📏 `_h_status()` L747: 7 参数数量
- 📏 `_h_plugin()` L750: 7 参数数量
- 📏 `_h_memory()` L753: 7 参数数量
- 📏 `_h_prompt()` L756: 7 参数数量
- 📏 `_h_config()` L759: 7 参数数量
- 📏 `_h_listconfig()` L762: 7 参数数量
- 📏 `_h_persona()` L765: 7 参数数量
- 📏 `_h_help()` L768: 7 参数数量
- 🏗️ `_env_backup_rotate()` L46: 中等嵌套: 3
- 🏗️ `_env_write()` L84: 嵌套过深: 5
- 🏗️ `_persona_status()` L820: 中等嵌套: 3
- 🏗️ `main()` L947: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1073 行
- 🏗️ L1: 导入过多: 22
- ❌ L220: 未处理的易出错调用
- ❌ L228: 未处理的易出错调用
- ❌ L499: 未处理的易出错调用
- ❌ L663: 未处理的易出错调用
- ❌ L673: 未处理的易出错调用
- ❌ L674: 未处理的易出错调用
- ❌ L675: 未处理的易出错调用
- ❌ L676: 未处理的易出错调用
- ❌ L677: 未处理的易出错调用
- ❌ L852: 未处理的易出错调用
- ❌ L907: 未处理的易出错调用
- ❌ L908: 未处理的易出错调用
- ❌ L909: 未处理的易出错调用
- 🏷️ `_env_backup_rotate()` L46: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L59: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L76: "_env_backup_count" - snake_case
- 🏷️ `_env_write()` L84: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L125: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L145: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L158: "_disable_console_logging" - snake_case
- 🏷️ `_cmd_newbind()` L177: "_cmd_newbind" - snake_case
- 🏷️ `_cmd_users()` L194: "_cmd_users" - snake_case
- 🏷️ `_cmd_status()` L235: "_cmd_status" - snake_case

**详情**:
- 循环复杂度: 平均: 4.6, 最大: 19
- 认知复杂度: 平均: 7.1, 最大: 25
- 嵌套深度: 平均: 1.3, 最大: 5
- 函数长度: 平均: 19.2 行, 最大: 112 行
- 文件长度: 876 代码量 (1073 总计)
- 参数数量: 平均: 2.7, 最大: 8
- 代码重复: 0.0% 重复 (0/47)
- 结构分析: 6 个结构问题
- 错误处理: 13/31 个错误被忽略 (41.9%)
- 注释比例: 1.3% (11/876)
- 命名规范: 发现 44 个违规

### 4. chatdbmgr.py

**糟糕指数: 34.45**

> 行数: 807 总计, 719 代码, 24 注释 | 函数: 30 | 类: 1

**问题**: 🔄 复杂度问题: 8, ⚠️ 其他问题: 8, 📋 重复问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 60, 📝 注释问题: 1, 🏷️ 命名问题: 7

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_score_memory_row` | L478-515 | 38 | 14 | 3 | 8 | ✗ |
| `search_memories` | L441-476 | 36 | 9 | 2 | 6 | ✗ |
| `append_messages` | L755-806 | 52 | 9 | 3 | 7 | ✓ |
| `_tokenize` | L17-30 | 14 | 7 | 4 | 1 | ✓ |
| `get_messages_by_rounds` | L517-552 | 36 | 6 | 3 | 4 | ✓ |
| `save_chat_history` | L629-664 | 36 | 6 | 3 | 4 | ✓ |
| `_init_db` | L111-286 | 176 | 5 | 4 | 1 | ✓ |
| `get_impressions` | L341-359 | 19 | 4 | 2 | 5 | ✗ |
| `save_memory` | L400-418 | 19 | 4 | 1 | 8 | ✓ |
| `get_next_round_index` | L583-595 | 13 | 4 | 1 | 2 | ✓ |
| `update_impression` | L309-328 | 20 | 3 | 1 | 2 | ✗ |
| `count_impressions` | L361-370 | 10 | 3 | 1 | 2 | ✗ |
| `get_memories` | L420-439 | 20 | 3 | 1 | 3 | ✓ |
| `get_last_message_ids` | L554-568 | 15 | 3 | 2 | 3 | ✓ |
| `get_memory_count` | L570-581 | 12 | 3 | 1 | 3 | ✓ |
| `get_chat_history` | L666-686 | 21 | 3 | 2 | 3 | ✓ |
| `replace_last_assistant` | L717-738 | 22 | 3 | 2 | 4 | ✓ |
| `__init__` | L40-57 | 18 | 2 | 1 | 3 | ✗ |
| `_get_connection` | L59-65 | 7 | 2 | 1 | 1 | ✓ |
| `close_connection` | L67-71 | 5 | 2 | 1 | 1 | ✓ |
| `_migrate_add_column` | L74-80 | 7 | 2 | 1 | 4 | ✓ |
| `_migrate_messages_role` | L83-109 | 27 | 2 | 1 | 1 | ✓ |
| `add_impression` | L292-307 | 16 | 2 | 1 | 7 | ✗ |
| `delete_impression` | L330-339 | 10 | 2 | 1 | 2 | ✗ |
| `get_impression_categories` | L372-382 | 11 | 2 | 1 | 2 | ✗ |
| `add_or_update_user` | L384-398 | 15 | 2 | 1 | 3 | ✓ |
| `delete_oldest_memory` | L597-612 | 16 | 2 | 1 | 4 | ✓ |
| `create_chat` | L614-627 | 14 | 2 | 1 | 3 | ✓ |
| `list_chats` | L688-715 | 28 | 2 | 1 | 2 | ✓ |
| `delete_chat` | L740-753 | 14 | 2 | 1 | 3 | ✓ |

**全部问题 (91)**

- 🔄 `_score_memory_row()` L478: 复杂度: 14
- 🔄 `_tokenize()` L17: 认知复杂度: 15
- 🔄 `_init_db()` L111: 认知复杂度: 13
- 🔄 `search_memories()` L441: 认知复杂度: 13
- 🔄 `_score_memory_row()` L478: 认知复杂度: 20
- 🔄 `append_messages()` L755: 认知复杂度: 15
- 🔄 `_tokenize()` L17: 嵌套深度: 4
- 🔄 `_init_db()` L111: 嵌套深度: 4
- 📏 `_init_db()` L111: 176 代码量
- 📏 `append_messages()` L755: 52 代码量
- 📏 `add_impression()` L292: 7 参数数量
- 📏 `save_memory()` L400: 8 参数数量
- 📏 `search_memories()` L441: 6 参数数量
- 📏 `_score_memory_row()` L478: 8 参数数量
- 📏 `append_messages()` L755: 7 参数数量
- 📋 `_get_connection()` L59: 重复模式: _get_connection, get_memories, get_memory_count, delete_oldest_memory, delete_chat
- 📋 `add_impression()` L292: 重复模式: add_impression, get_next_round_index
- 📋 `count_impressions()` L361: 重复模式: count_impressions, get_impression_categories
- 🏗️ `_tokenize()` L17: 中等嵌套: 4
- 🏗️ `_init_db()` L111: 中等嵌套: 4
- 🏗️ `_score_memory_row()` L478: 中等嵌套: 3
- 🏗️ `get_messages_by_rounds()` L517: 中等嵌套: 3
- 🏗️ `save_chat_history()` L629: 中等嵌套: 3
- 🏗️ `append_messages()` L755: 中等嵌套: 3
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
- ❌ L148: 未处理的易出错调用
- ❌ L162: 未处理的易出错调用
- ❌ L165: 未处理的易出错调用
- ❌ L177: 未处理的易出错调用
- ❌ L184: 未处理的易出错调用
- ❌ L191: 未处理的易出错调用
- ❌ L197: 未处理的易出错调用
- ❌ L202: 未处理的易出错调用
- ❌ L216: 未处理的易出错调用
- ❌ L217: 未处理的易出错调用
- ❌ L220: 未处理的易出错调用
- ❌ L232: 未处理的易出错调用
- ❌ L248: 未处理的易出错调用
- ❌ L257: 未处理的易出错调用
- ❌ L266: 未处理的易出错调用
- ❌ L281: 未处理的易出错调用
- ❌ L285: 未处理的易出错调用
- ❌ L302: 未处理的易出错调用
- ❌ L306: 未处理的易出错调用
- ❌ L319: 未处理的易出错调用
- ❌ L323: 未处理的易出错调用
- ❌ L327: 未处理的易出错调用
- ❌ L334: 未处理的易出错调用
- ❌ L338: 未处理的易出错调用
- ❌ L388: 未处理的易出错调用
- ❌ L393: 未处理的易出错调用
- ❌ L397: 未处理的易出错调用
- ❌ L412: 未处理的易出错调用
- ❌ L417: 未处理的易出错调用
- ❌ L601: 未处理的易出错调用
- ❌ L607: 未处理的易出错调用
- ❌ L611: 未处理的易出错调用
- ❌ L622: 未处理的易出错调用
- ❌ L626: 未处理的易出错调用
- ❌ L638: 未处理的易出错调用
- ❌ L658: 未处理的易出错调用
- ❌ L663: 未处理的易出错调用
- ❌ L729: 未处理的易出错调用
- ❌ L733: 未处理的易出错调用
- ❌ L737: 未处理的易出错调用
- ❌ L748: 未处理的易出错调用
- ❌ L752: 未处理的易出错调用
- ❌ L792: 未处理的易出错调用
- ❌ L801: 未处理的易出错调用
- ❌ L805: 未处理的易出错调用
- 🏷️ `_tokenize()` L17: "_tokenize" - snake_case
- 🏷️ `__init__()` L40: "__init__" - snake_case
- 🏷️ `_get_connection()` L59: "_get_connection" - snake_case
- 🏷️ `_migrate_add_column()` L74: "_migrate_add_column" - snake_case
- 🏷️ `_migrate_messages_role()` L83: "_migrate_messages_role" - snake_case
- 🏷️ `_init_db()` L111: "_init_db" - snake_case
- 🏷️ `_score_memory_row()` L478: "_score_memory_row" - snake_case

**详情**:
- 循环复杂度: 平均: 3.8, 最大: 14
- 认知复杂度: 平均: 7.1, 最大: 20
- 嵌套深度: 平均: 1.6, 最大: 4
- 函数长度: 平均: 24.9 行, 最大: 176 行
- 文件长度: 719 代码量 (807 总计)
- 参数数量: 平均: 3.4, 最大: 8
- 代码重复: 20.0% 重复 (6/30)
- 结构分析: 6 个结构问题
- 错误处理: 60/89 个错误被忽略 (67.4%)
- 注释比例: 3.3% (24/719)
- 命名规范: 发现 7 个违规

### 5. psychoscope/static/js/app.js

**糟糕指数: 34.43**

> 行数: 1453 总计, 1325 代码, 41 注释 | 函数: 57 | 类: 0

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 32, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `msgFlow` | L750-880 | 131 | 38 | 4 | 1 | ✗ |
| `sendRecording` | L640-744 | 105 | 36 | 4 | 2 | ✗ |
| `init` | L1420-1450 | 31 | 10 | 2 | 0 | ✓ |
| `openMaintenanceSSE` | L1015-1075 | 61 | 9 | 2 | 0 | ✗ |
| `selectChat` | L422-465 | 44 | 8 | 4 | 1 | ✗ |
| `tryPairLogin` | L347-366 | 20 | 7 | 1 | 0 | ✗ |
| `showTimingLine` | L970-988 | 19 | 7 | 2 | 2 | ✗ |
| `showKeyHints` | L1273-1327 | 55 | 7 | 1 | 0 | ✗ |
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
| `showConfirm` | L1363-1388 | 26 | 4 | 1 | 0 | ✗ |
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
| `renderMaintTasks` | L1077-1085 | 9 | 3 | 0 | 0 | ✗ |
| `updateMaintProgress` | L1087-1099 | 13 | 3 | 1 | 0 | ✗ |
| `hideConfirm` | L1390-1405 | 16 | 3 | 1 | 0 | ✗ |
| `toggleTheme` | L19-21 | 3 | 2 | 0 | 0 | ✗ |
| `addLineStatic` | L232-247 | 16 | 2 | 1 | 3 | ✗ |
| `newChat` | L466-473 | 8 | 2 | 1 | 0 | ✗ |
| `removeImage` | L494-501 | 8 | 2 | 1 | 0 | ✗ |
| `cancelRecording` | L567-575 | 9 | 2 | 1 | 0 | ✗ |
| `uncancelRecording` | L577-585 | 9 | 2 | 1 | 0 | ✗ |
| `sendMessage` | L882-894 | 13 | 2 | 1 | 0 | ✗ |
| `toggleTTS` | L909-913 | 5 | 2 | 0 | 0 | ✓ |
| `checkMaintStatus` | L1101-1110 | 10 | 2 | 1 | 0 | ✗ |
| `hideKeyHints` | L1329-1337 | 9 | 2 | 1 | 0 | ✗ |
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
| `createKeyCapSVG` | L1257-1267 | 11 | 1 | 0 | 1 | ✓ |
| `doConfirm` | L1407-1411 | 5 | 1 | 0 | 0 | ✗ |

**全部问题 (49)**

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
- 🏗️ L1: 文件过大: 1453 行
- 🏗️ L1: 函数过多: 57
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
- ❌ L1102: 未处理的易出错调用
- ❌ L1120: 未处理的易出错调用
- ❌ L1334: 未处理的易出错调用
- ❌ L1335: 未处理的易出错调用
- ❌ L1366: 未处理的易出错调用
- ❌ L1369: 未处理的易出错调用
- ❌ L1393: 未处理的易出错调用
- ❌ L1395: 未处理的易出错调用
- ❌ L1400: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 4.4, 最大: 38
- 认知复杂度: 平均: 6.5, 最大: 46
- 嵌套深度: 平均: 1.0, 最大: 4
- 函数长度: 平均: 18.3 行, 最大: 131 行
- 文件长度: 1325 代码量 (1453 总计)
- 参数数量: 平均: 0.6, 最大: 3
- 代码重复: 3.5% 重复 (2/57)
- 结构分析: 6 个结构问题
- 错误处理: 32/56 个错误被忽略 (57.1%)
- 注释比例: 3.1% (41/1325)
- 命名规范: 无命名违规

### 6. tests/test_ncm_music.py

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

### 7. plugins/builtin/agent_plugin.py

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

### 8. stationed.py

**糟糕指数: 23.66**

> 行数: 237 总计, 187 代码, 16 注释 | 函数: 6 | 类: 1

**问题**: 🔄 复杂度问题: 3, ⚠️ 其他问题: 2, 🏗️ 结构问题: 2, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 5

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_collect_state` | L103-179 | 77 | 19 | 5 | 3 | ✓ |
| `_get_or_create_chat` | L76-101 | 26 | 6 | 2 | 2 | ✗ |
| `chat` | L197-236 | 40 | 6 | 3 | 4 | ✓ |
| `_create_steward_client` | L37-61 | 25 | 3 | 1 | 1 | ✓ |
| `_load_history` | L181-195 | 15 | 3 | 1 | 2 | ✓ |
| `__init__` | L67-74 | 8 | 1 | 0 | 2 | ✗ |

**全部问题 (12)**

- 🔄 `_collect_state()` L103: 复杂度: 19
- 🔄 `_collect_state()` L103: 认知复杂度: 29
- 🔄 `_collect_state()` L103: 嵌套深度: 5
- 📏 `_collect_state()` L103: 77 代码量
- 🏗️ `_collect_state()` L103: 嵌套过深: 5
- 🏗️ `chat()` L197: 中等嵌套: 3
- ❌ L96: 未处理的易出错调用
- 🏷️ `_create_steward_client()` L37: "_create_steward_client" - snake_case
- 🏷️ `__init__()` L67: "__init__" - snake_case
- 🏷️ `_get_or_create_chat()` L76: "_get_or_create_chat" - snake_case
- 🏷️ `_collect_state()` L103: "_collect_state" - snake_case
- 🏷️ `_load_history()` L181: "_load_history" - snake_case

**详情**:
- 循环复杂度: 平均: 6.3, 最大: 19
- 认知复杂度: 平均: 10.3, 最大: 29
- 嵌套深度: 平均: 2.0, 最大: 5
- 函数长度: 平均: 31.8 行, 最大: 77 行
- 文件长度: 187 代码量 (237 总计)
- 参数数量: 平均: 2.3, 最大: 4
- 代码重复: 0.0% 重复 (0/6)
- 结构分析: 2 个结构问题
- 错误处理: 1/13 个错误被忽略 (7.7%)
- 注释比例: 8.6% (16/187)
- 命名规范: 发现 5 个违规

### 9. subapps/self_evolution/entry.py

**糟糕指数: 22.64**

> 行数: 134 总计, 102 代码, 3 注释 | 函数: 2 | 类: 0

**问题**: 🔄 复杂度问题: 2, ⚠️ 其他问题: 1, 🏗️ 结构问题: 1, ❌ 错误处理问题: 1, 📝 注释问题: 1

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L22-129 | 96 | 18 | 3 | 0 | ✗ |
| `daily_job` | L100-111 | 12 | 2 | 1 | 0 | ✗ |

**全部问题 (5)**

- 🔄 `main()` L22: 复杂度: 18
- 🔄 `main()` L22: 认知复杂度: 24
- 📏 `main()` L22: 96 代码量
- 🏗️ `main()` L22: 中等嵌套: 3
- ❌ L107: 未处理的易出错调用

**详情**:
- 循环复杂度: 平均: 10.0, 最大: 18
- 认知复杂度: 平均: 14.0, 最大: 24
- 嵌套深度: 平均: 2.0, 最大: 3
- 函数长度: 平均: 54.0 行, 最大: 96 行
- 文件长度: 102 代码量 (134 总计)
- 参数数量: 平均: 0.0, 最大: 0
- 代码重复: 未发现函数
- 结构分析: 1 个结构问题
- 错误处理: 1/3 个错误被忽略 (33.3%)
- 注释比例: 2.9% (3/102)
- 命名规范: 无命名违规

### 10. models.py

**糟糕指数: 21.04**

> 行数: 497 总计, 406 代码, 11 注释 | 函数: 28 | 类: 3

**问题**: 🔄 复杂度问题: 6, ⚠️ 其他问题: 7, 🏗️ 结构问题: 2, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_llm` | L414-456 | 43 | 15 | 4 | 7 | ✓ |
| `_call_and_append` | L123-180 | 58 | 9 | 2 | 1 | ✓ |
| `__init__` | L388-412 | 25 | 7 | 1 | 8 | ✗ |
| `_is_no_model_error` | L12-20 | 9 | 6 | 1 | 1 | ✓ |
| `_call_chat_api` | L261-279 | 19 | 6 | 4 | 2 | ✓ |
| `describe_image` | L341-373 | 33 | 6 | 1 | 5 | ✓ |
| `__init__` | L59-109 | 51 | 5 | 1 | 8 | ✓ |
| `summarize_text` | L458-479 | 22 | 5 | 1 | 3 | ✓ |
| `summarize_dialog` | L484-496 | 13 | 5 | 2 | 3 | ✓ |
| `__init__` | L219-254 | 36 | 4 | 1 | 7 | ✓ |
| `send_message` | L281-288 | 8 | 4 | 1 | 2 | ✓ |
| `_load_lmstudio_model` | L23-42 | 20 | 3 | 1 | 4 | ✓ |
| `send_message` | L111-117 | 7 | 3 | 1 | 2 | ✓ |
| `_call_and_append` | L294-312 | 19 | 3 | 1 | 1 | ✗ |
| `continue_conversation` | L119-121 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L182-185 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L187-193 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L195-202 | 8 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L204-207 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L209-210 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L256-257 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L290-292 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L314-317 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L319-325 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L327-334 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L336-339 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L375-376 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L481-482 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (25)**

- 🔄 `_call_llm()` L414: 复杂度: 15
- 🔄 `_call_and_append()` L123: 认知复杂度: 13
- 🔄 `_call_chat_api()` L261: 认知复杂度: 14
- 🔄 `_call_llm()` L414: 认知复杂度: 23
- 🔄 `_call_chat_api()` L261: 嵌套深度: 4
- 🔄 `_call_llm()` L414: 嵌套深度: 4
- 📏 `__init__()` L59: 51 代码量
- 📏 `_call_and_append()` L123: 58 代码量
- 📏 `__init__()` L59: 8 参数数量
- 📏 `__init__()` L219: 7 参数数量
- 📏 `__init__()` L388: 8 参数数量
- 📏 `_call_llm()` L414: 7 参数数量
- 🏗️ `_call_chat_api()` L261: 中等嵌套: 4
- 🏗️ `_call_llm()` L414: 中等嵌套: 4
- ❌ L38: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L12: "_is_no_model_error" - snake_case
- 🏷️ `_load_lmstudio_model()` L23: "_load_lmstudio_model" - snake_case
- 🏷️ `__init__()` L59: "__init__" - snake_case
- 🏷️ `_call_and_append()` L123: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L209: "__repr__" - snake_case
- 🏷️ `__init__()` L219: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L256: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L261: "_call_chat_api" - snake_case
- 🏷️ `_call_and_append()` L294: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L375: "__repr__" - snake_case

**详情**:
- 循环复杂度: 平均: 3.4, 最大: 15
- 认知复杂度: 平均: 5.0, 最大: 23
- 嵌套深度: 平均: 0.8, 最大: 4
- 函数长度: 平均: 15.1 行, 最大: 58 行
- 文件长度: 406 代码量 (497 总计)
- 参数数量: 平均: 2.6, 最大: 8
- 代码重复: 3.6% 重复 (1/28)
- 结构分析: 2 个结构问题
- 错误处理: 1/14 个错误被忽略 (7.1%)
- 注释比例: 2.7% (11/406)
- 命名规范: 发现 13 个违规

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `create_engine_with_defaults` | engine.py | 43 | 2 | 233 |
| `process_stream` | plugins/pipeline.py | 40 | 5 | 203 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `_run_agent_loop` | plugins/builtin/agent_plugin.py | 21 | 3 | 88 |
| `_collect_state` | stationed.py | 19 | 5 | 77 |
| `main` | main.py | 19 | 3 | 112 |
| `generate_personality_prompt` | prompt/_personality_v1_legacy.py | 19 | 2 | 65 |
| `main` | tests/test_ncm_music.py | 18 | 3 | 97 |
| `_poll_pending_tasks` | plugins/pipeline.py | 18 | 5 | 30 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*