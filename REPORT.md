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
| **糟糕指数** | **82.59/100** |
| 屎山等级 | 😐 微臭青年 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 149 |
| 已跳过 | 243 |
| 耗时 | 843ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 24618 |
| 总注释行数 | 1275 |
| 整体注释比例 | 5.2% |
| 平均文件大小 | 207 行 |
| 最大文件 | `psychoscope/static/js/app.js` (1497) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 146 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 8.98% | 0.0% | 80.0% | 4.0% | ✓✓ |
| 认知复杂度 | 12.63% | 0.0% | 67.0% | 8.0% | ✓✓ |
| 嵌套深度 | 2.97% | 0.0% | 37.5% | 0.0% | ✓✓ |
| 函数长度 | 5.58% | 0.0% | 49.9% | 0.0% | ✓✓ |
| 文件长度 | 2.50% | 0.0% | 89.2% | 0.0% | ✓✓ |
| 参数数量 | 13.65% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 3.54% | 0.0% | 65.0% | 0.0% | ✓✓ |
| 结构分析 | 4.41% | 0.0% | 59.5% | 0.0% | ✓✓ |
| 错误处理 | 33.77% | 0.0% | 98.8% | 6.7% | ✓ |
| 注释比例 | 35.78% | 0.0% | 100.0% | 29.9% | ○ |
| 命名规范 | 26.76% | 0.0% | 94.7% | 22.2% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. engine.py

**糟糕指数: 43.19**

> 行数: 1022 总计, 879 代码, 19 注释 | 函数: 38 | 类: 2

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 6, 📋 重复问题: 2, 🏗️ 结构问题: 6, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_engine_with_defaults` | L785-1021 | 237 | 43 | 2 | 12 | ✓ |
| `_init_prompt` | L412-452 | 41 | 16 | 4 | 1 | ✗ |
| `_register_execution_plugins` | L542-582 | 41 | 11 | 2 | 1 | ✗ |
| `build_context` | L620-653 | 34 | 10 | 1 | 8 | ✓ |
| `_register_personality_plugins` | L520-540 | 21 | 9 | 2 | 1 | ✗ |
| `_register_output_plugins` | L584-607 | 24 | 9 | 2 | 1 | ✗ |
| `chat` | L655-691 | 37 | 9 | 2 | 8 | ✓ |
| `_register_context_plugins` | L499-518 | 20 | 8 | 1 | 1 | ✗ |
| `chat_stream` | L693-712 | 20 | 8 | 1 | 8 | ✓ |
| `_generate_result_message` | L255-292 | 38 | 7 | 2 | 3 | ✗ |
| `run_scheduled` | L722-759 | 31 | 7 | 2 | 1 | ✓ |
| `_get_event_loop` | L42-48 | 7 | 6 | 3 | 0 | ✗ |
| `_handle_engine_action_completion` | L214-228 | 15 | 6 | 2 | 4 | ✗ |
| `_retry_engine_action` | L294-315 | 22 | 6 | 2 | 4 | ✗ |
| `_init_world` | L335-360 | 26 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L380-396 | 17 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L398-410 | 13 | 6 | 3 | 1 | ✓ |
| `get_info` | L763-771 | 9 | 6 | 0 | 1 | ✗ |
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
| `create_chat` | L714-715 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L717-718 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L734-740 | 7 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L139-154 | 16 | 1 | 0 | 1 | ✗ |
| `_init_pipeline` | L609-616 | 8 | 1 | 0 | 1 | ✗ |
| `create_engine` | L776-782 | 7 | 1 | 0 | 1 | ✓ |

**全部问题 (37)**

- 🔄 `_init_prompt()` L412: 复杂度: 16
- 🔄 `_register_execution_plugins()` L542: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L785: 复杂度: 43
- 🔄 `_init_prompt()` L412: 认知复杂度: 24
- 🔄 `_register_personality_plugins()` L520: 认知复杂度: 13
- 🔄 `_register_execution_plugins()` L542: 认知复杂度: 15
- 🔄 `_register_output_plugins()` L584: 认知复杂度: 13
- 🔄 `chat()` L655: 认知复杂度: 13
- 🔄 `create_engine_with_defaults()` L785: 认知复杂度: 47
- 🔄 `_init_prompt()` L412: 嵌套深度: 4
- 📏 `create_engine_with_defaults()` L785: 237 代码量
- 📏 `build_context()` L620: 8 参数数量
- 📏 `chat()` L655: 8 参数数量
- 📏 `chat_stream()` L693: 8 参数数量
- 📏 `create_engine_with_defaults()` L785: 12 参数数量
- 📋 `_init_database()` L156: 重复模式: _init_database, _process_task_completion, _register_personality_plugins
- 📋 `_handle_reasoner_completion()` L241: 重复模式: _handle_reasoner_completion, _register_context_plugins, _init_pipeline
- 🏗️ `_get_event_loop()` L42: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L186: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L398: 中等嵌套: 3
- 🏗️ `_init_prompt()` L412: 中等嵌套: 4
- 🏗️ L1: 文件过大: 1022 行
- 🏗️ L1: 导入过多: 81
- ❌ L215: 未处理的易出错调用
- ❌ L225: 未处理的易出错调用
- ❌ L271: 未处理的易出错调用
- ❌ L738: 未处理的易出错调用
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
- 认知复杂度: 平均: 8.8, 最大: 47
- 嵌套深度: 平均: 1.3, 最大: 4
- 函数长度: 平均: 23.5 行, 最大: 237 行
- 文件长度: 879 代码量 (1022 总计)
- 参数数量: 平均: 2.3, 最大: 12
- 代码重复: 10.5% 重复 (4/38)
- 结构分析: 6 个结构问题
- 错误处理: 4/24 个错误被忽略 (16.7%)
- 注释比例: 2.2% (19/879)
- 命名规范: 发现 27 个违规

### 2. main.py

**糟糕指数: 39.99**

> 行数: 1279 总计, 1039 代码, 17 注释 | 函数: 53 | 类: 1

**问题**: 🔄 复杂度问题: 17, ⚠️ 其他问题: 16, 🏗️ 结构问题: 8, ❌ 错误处理问题: 13, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L1152-1274 | 113 | 19 | 3 | 0 | ✗ |
| `_cmd_memory_list` | L610-684 | 75 | 14 | 2 | 4 | ✓ |
| `_cmd_hibernate_check` | L1045-1111 | 67 | 14 | 3 | 1 | ✗ |
| `_cmd_plugin` | L455-508 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L794-833 | 40 | 11 | 2 | 2 | ✓ |
| `_env_write` | L84-111 | 28 | 10 | 5 | 2 | ✓ |
| `_persona_materials` | L935-960 | 26 | 10 | 2 | 2 | ✗ |
| `_cmd_users` | L194-232 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L235-271 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_memory` | L511-535 | 25 | 9 | 2 | 3 | ✓ |
| `_persona_status` | L836-870 | 35 | 8 | 3 | 2 | ✗ |
| `_cmd_hibernate` | L1014-1042 | 29 | 8 | 1 | 2 | ✗ |
| `_cmd_config` | L312-344 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_memory_users` | L538-571 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L574-607 | 34 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L687-713 | 27 | 6 | 1 | 2 | ✓ |
| `_execute_command` | L727-746 | 20 | 6 | 2 | 9 | ✗ |
| `_cmd_hibernate_archive` | L1114-1142 | 29 | 6 | 2 | 2 | ✗ |
| `_env_backup_rotate` | L46-56 | 11 | 5 | 3 | 0 | ✓ |
| `_try_convert` | L297-309 | 13 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L347-366 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L369-396 | 28 | 5 | 1 | 3 | ✓ |
| `_persona_list` | L901-932 | 32 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L963-989 | 27 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L59-73 | 15 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L286-294 | 9 | 4 | 2 | 2 | ✗ |
| `_handle_steward_chat` | L1231-1240 | 10 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L76-81 | 6 | 3 | 2 | 0 | ✗ |
| `_enable_console_logging` | L145-155 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L158-163 | 6 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L177-191 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L399-415 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L883-894 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L999-1011 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L114-117 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L120-122 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L125-138 | 12 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L758-759 | 2 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L873-897 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L1145-1149 | 5 | 2 | 1 | 1 | ✗ |
| `emit` | L132-133 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L418-420 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L423-452 | 30 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L716-724 | 9 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L749-750 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L752-753 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L755-756 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L761-762 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L764-765 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L767-768 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L770-771 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L773-774 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L776-777 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (63)**

- 🔄 `_cmd_plugin()` L455: 复杂度: 11
- 🔄 `_cmd_memory_list()` L610: 复杂度: 14
- 🔄 `_cmd_persona()` L794: 复杂度: 11
- 🔄 `_cmd_hibernate_check()` L1045: 复杂度: 14
- 🔄 `main()` L1152: 复杂度: 19
- 🔄 `_env_write()` L84: 认知复杂度: 20
- 🔄 `_cmd_users()` L194: 认知复杂度: 13
- 🔄 `_cmd_status()` L235: 认知复杂度: 13
- 🔄 `_cmd_plugin()` L455: 认知复杂度: 15
- 🔄 `_cmd_memory()` L511: 认知复杂度: 13
- 🔄 `_cmd_memory_list()` L610: 认知复杂度: 18
- 🔄 `_cmd_persona()` L794: 认知复杂度: 15
- 🔄 `_persona_status()` L836: 认知复杂度: 14
- 🔄 `_persona_materials()` L935: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L1045: 认知复杂度: 20
- 🔄 `main()` L1152: 认知复杂度: 25
- 🔄 `_env_write()` L84: 嵌套深度: 5
- 📏 `_cmd_plugin()` L455: 54 代码量
- 📏 `_cmd_memory_list()` L610: 75 代码量
- 📏 `_cmd_hibernate_check()` L1045: 67 代码量
- 📏 `main()` L1152: 113 代码量
- 📏 `_execute_command()` L727: 9 参数数量
- 📏 `_h_newbind()` L749: 7 参数数量
- 📏 `_h_users()` L752: 7 参数数量
- 📏 `_h_status()` L755: 7 参数数量
- 📏 `_h_plugin()` L758: 7 参数数量
- 📏 `_h_memory()` L761: 7 参数数量
- 📏 `_h_prompt()` L764: 7 参数数量
- 📏 `_h_config()` L767: 7 参数数量
- 📏 `_h_listconfig()` L770: 7 参数数量
- 📏 `_h_persona()` L773: 7 参数数量
- 📏 `_h_help()` L776: 7 参数数量
- 🏗️ `_env_backup_rotate()` L46: 中等嵌套: 3
- 🏗️ `_env_write()` L84: 嵌套过深: 5
- 🏗️ `_persona_status()` L836: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L1045: 中等嵌套: 3
- 🏗️ `main()` L1152: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1279 行
- 🏗️ L1: 函数过多: 53
- 🏗️ L1: 导入过多: 26
- ❌ L220: 未处理的易出错调用
- ❌ L228: 未处理的易出错调用
- ❌ L503: 未处理的易出错调用
- ❌ L667: 未处理的易出错调用
- ❌ L677: 未处理的易出错调用
- ❌ L678: 未处理的易出错调用
- ❌ L679: 未处理的易出错调用
- ❌ L680: 未处理的易出错调用
- ❌ L681: 未处理的易出错调用
- ❌ L868: 未处理的易出错调用
- ❌ L923: 未处理的易出错调用
- ❌ L924: 未处理的易出错调用
- ❌ L925: 未处理的易出错调用
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
- 循环复杂度: 平均: 4.8, 最大: 19
- 认知复杂度: 平均: 7.5, 最大: 25
- 嵌套深度: 平均: 1.3, 最大: 5
- 函数长度: 平均: 20.6 行, 最大: 113 行
- 文件长度: 1039 代码量 (1279 总计)
- 参数数量: 平均: 2.6, 最大: 9
- 代码重复: 3.8% 重复 (2/53)
- 结构分析: 8 个结构问题
- 错误处理: 13/34 个错误被忽略 (38.2%)
- 注释比例: 1.6% (17/1039)
- 命名规范: 发现 50 个违规

### 3. plugins/pipeline.py

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

### 4. chatdbmgr.py

**糟糕指数: 35.35**

> 行数: 839 总计, 749 代码, 24 注释 | 函数: 32 | 类: 1

**问题**: 🔄 复杂度问题: 8, ⚠️ 其他问题: 8, 📋 重复问题: 3, 🏗️ 结构问题: 6, ❌ 错误处理问题: 64, 📝 注释问题: 1, 🏷️ 命名问题: 7

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_score_memory_row` | L485-522 | 38 | 14 | 3 | 8 | ✗ |
| `search_memories` | L448-483 | 36 | 9 | 2 | 6 | ✗ |
| `append_messages` | L762-813 | 52 | 9 | 3 | 7 | ✓ |
| `_tokenize` | L17-30 | 14 | 7 | 4 | 1 | ✓ |
| `get_messages_by_rounds` | L524-559 | 36 | 6 | 3 | 4 | ✓ |
| `save_chat_history` | L636-671 | 36 | 6 | 3 | 4 | ✓ |
| `_init_db` | L111-293 | 183 | 5 | 4 | 1 | ✓ |
| `get_impressions` | L348-366 | 19 | 4 | 2 | 5 | ✗ |
| `save_memory` | L407-425 | 19 | 4 | 1 | 8 | ✓ |
| `get_next_round_index` | L590-602 | 13 | 4 | 1 | 2 | ✓ |
| `update_impression` | L316-335 | 20 | 3 | 1 | 2 | ✗ |
| `count_impressions` | L368-377 | 10 | 3 | 1 | 2 | ✗ |
| `get_memories` | L427-446 | 20 | 3 | 1 | 3 | ✓ |
| `get_last_message_ids` | L561-575 | 15 | 3 | 2 | 3 | ✓ |
| `get_memory_count` | L577-588 | 12 | 3 | 1 | 3 | ✓ |
| `get_chat_history` | L673-693 | 21 | 3 | 2 | 3 | ✓ |
| `replace_last_assistant` | L724-745 | 22 | 3 | 2 | 4 | ✓ |
| `load_kv` | L829-838 | 10 | 3 | 1 | 2 | ✗ |
| `__init__` | L40-57 | 18 | 2 | 1 | 3 | ✗ |
| `_get_connection` | L59-65 | 7 | 2 | 1 | 1 | ✓ |
| `close_connection` | L67-71 | 5 | 2 | 1 | 1 | ✓ |
| `_migrate_add_column` | L74-80 | 7 | 2 | 1 | 4 | ✓ |
| `_migrate_messages_role` | L83-109 | 27 | 2 | 1 | 1 | ✓ |
| `add_impression` | L299-314 | 16 | 2 | 1 | 7 | ✗ |
| `delete_impression` | L337-346 | 10 | 2 | 1 | 2 | ✗ |
| `get_impression_categories` | L379-389 | 11 | 2 | 1 | 2 | ✗ |
| `add_or_update_user` | L391-405 | 15 | 2 | 1 | 3 | ✓ |
| `delete_oldest_memory` | L604-619 | 16 | 2 | 1 | 4 | ✓ |
| `create_chat` | L621-634 | 14 | 2 | 1 | 3 | ✓ |
| `list_chats` | L695-722 | 28 | 2 | 1 | 2 | ✓ |
| `delete_chat` | L747-760 | 14 | 2 | 1 | 3 | ✓ |
| `save_kv` | L815-827 | 13 | 2 | 1 | 3 | ✗ |

**全部问题 (95)**

- 🔄 `_score_memory_row()` L485: 复杂度: 14
- 🔄 `_tokenize()` L17: 认知复杂度: 15
- 🔄 `_init_db()` L111: 认知复杂度: 13
- 🔄 `search_memories()` L448: 认知复杂度: 13
- 🔄 `_score_memory_row()` L485: 认知复杂度: 20
- 🔄 `append_messages()` L762: 认知复杂度: 15
- 🔄 `_tokenize()` L17: 嵌套深度: 4
- 🔄 `_init_db()` L111: 嵌套深度: 4
- 📏 `_init_db()` L111: 183 代码量
- 📏 `append_messages()` L762: 52 代码量
- 📏 `add_impression()` L299: 7 参数数量
- 📏 `save_memory()` L407: 8 参数数量
- 📏 `search_memories()` L448: 6 参数数量
- 📏 `_score_memory_row()` L485: 8 参数数量
- 📏 `append_messages()` L762: 7 参数数量
- 📋 `_get_connection()` L59: 重复模式: _get_connection, get_memories, get_memory_count, delete_oldest_memory, delete_chat
- 📋 `add_impression()` L299: 重复模式: add_impression, get_next_round_index
- 📋 `count_impressions()` L368: 重复模式: count_impressions, get_impression_categories, load_kv
- 🏗️ `_tokenize()` L17: 中等嵌套: 4
- 🏗️ `_init_db()` L111: 中等嵌套: 4
- 🏗️ `_score_memory_row()` L485: 中等嵌套: 3
- 🏗️ `get_messages_by_rounds()` L524: 中等嵌套: 3
- 🏗️ `save_chat_history()` L636: 中等嵌套: 3
- 🏗️ `append_messages()` L762: 中等嵌套: 3
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
- ❌ L280: 未处理的易出错调用
- ❌ L288: 未处理的易出错调用
- ❌ L292: 未处理的易出错调用
- ❌ L309: 未处理的易出错调用
- ❌ L313: 未处理的易出错调用
- ❌ L326: 未处理的易出错调用
- ❌ L330: 未处理的易出错调用
- ❌ L334: 未处理的易出错调用
- ❌ L341: 未处理的易出错调用
- ❌ L345: 未处理的易出错调用
- ❌ L395: 未处理的易出错调用
- ❌ L400: 未处理的易出错调用
- ❌ L404: 未处理的易出错调用
- ❌ L419: 未处理的易出错调用
- ❌ L424: 未处理的易出错调用
- ❌ L608: 未处理的易出错调用
- ❌ L614: 未处理的易出错调用
- ❌ L618: 未处理的易出错调用
- ❌ L629: 未处理的易出错调用
- ❌ L633: 未处理的易出错调用
- ❌ L645: 未处理的易出错调用
- ❌ L665: 未处理的易出错调用
- ❌ L670: 未处理的易出错调用
- ❌ L736: 未处理的易出错调用
- ❌ L740: 未处理的易出错调用
- ❌ L744: 未处理的易出错调用
- ❌ L755: 未处理的易出错调用
- ❌ L759: 未处理的易出错调用
- ❌ L799: 未处理的易出错调用
- ❌ L808: 未处理的易出错调用
- ❌ L812: 未处理的易出错调用
- ❌ L818: 未处理的易出错调用
- ❌ L822: 未处理的易出错调用
- ❌ L826: 未处理的易出错调用
- 🏷️ `_tokenize()` L17: "_tokenize" - snake_case
- 🏷️ `__init__()` L40: "__init__" - snake_case
- 🏷️ `_get_connection()` L59: "_get_connection" - snake_case
- 🏷️ `_migrate_add_column()` L74: "_migrate_add_column" - snake_case
- 🏷️ `_migrate_messages_role()` L83: "_migrate_messages_role" - snake_case
- 🏷️ `_init_db()` L111: "_init_db" - snake_case
- 🏷️ `_score_memory_row()` L485: "_score_memory_row" - snake_case

**详情**:
- 循环复杂度: 平均: 3.8, 最大: 14
- 认知复杂度: 平均: 6.9, 最大: 20
- 嵌套深度: 平均: 1.6, 最大: 4
- 函数长度: 平均: 24.3 行, 最大: 183 行
- 文件长度: 749 代码量 (839 总计)
- 参数数量: 平均: 3.3, 最大: 8
- 代码重复: 21.9% 重复 (7/32)
- 结构分析: 6 个结构问题
- 错误处理: 64/94 个错误被忽略 (68.1%)
- 注释比例: 3.2% (24/749)
- 命名规范: 发现 7 个违规

### 5. psychoscope/static/js/app.js

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

### 6. psychoscope/minimal.py

**糟糕指数: 33.89**

> 行数: 682 总计, 586 代码, 1 注释 | 函数: 31 | 类: 3

**问题**: 🔄 复杂度问题: 15, ⚠️ 其他问题: 3, 🏗️ 结构问题: 9, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L553-679 | 120 | 26 | 6 | 0 | ✗ |
| `authenticate` | L167-248 | 82 | 14 | 2 | 3 | ✗ |
| `_handle_sse_stream` | L308-341 | 34 | 11 | 3 | 2 | ✗ |
| `stop_and_send` | L381-413 | 33 | 10 | 2 | 1 | ✗ |
| `_capture_loop` | L415-445 | 31 | 9 | 3 | 1 | ✗ |
| `_loop` | L471-497 | 27 | 9 | 5 | 1 | ✗ |
| `iter_sse_lines` | L106-123 | 18 | 8 | 3 | 1 | ✗ |
| `_audio_worker` | L149-165 | 17 | 7 | 3 | 1 | ✗ |
| `_detect_tts_sample_rate` | L70-83 | 14 | 6 | 5 | 0 | ✓ |
| `_verify_api_key` | L250-267 | 18 | 5 | 3 | 1 | ✗ |
| `send_audio` | L286-306 | 21 | 4 | 2 | 2 | ✗ |
| `start` | L359-379 | 21 | 4 | 1 | 1 | ✗ |
| `load_config` | L125-131 | 7 | 3 | 2 | 0 | ✗ |
| `__init__` | L137-147 | 11 | 3 | 1 | 3 | ✗ |
| `print_personality` | L518-543 | 26 | 3 | 2 | 1 | ✗ |
| `setup_logging` | L45-65 | 21 | 2 | 1 | 0 | ✗ |
| `raw_pcm_to_wav_b64` | L96-104 | 9 | 2 | 1 | 2 | ✗ |
| `_headers` | L269-272 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L453-458 | 6 | 2 | 1 | 1 | ✗ |
| `stop` | L460-463 | 4 | 2 | 1 | 1 | ✗ |
| `get` | L465-469 | 5 | 2 | 1 | 2 | ✗ |
| `print_header` | L499-516 | 18 | 2 | 0 | 1 | ✗ |
| `toggle_standby` | L545-551 | 7 | 2 | 1 | 1 | ✗ |
| `on_sigint` | L609-615 | 7 | 2 | 1 | 2 | ✗ |
| `save_config` | L133-134 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L274-276 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L278-280 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L282-284 | 3 | 1 | 0 | 2 | ✗ |
| `__init__` | L344-353 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L356-357 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L448-451 | 4 | 1 | 0 | 1 | ✗ |

**全部问题 (43)**

- 🔄 `authenticate()` L167: 复杂度: 14
- 🔄 `_handle_sse_stream()` L308: 复杂度: 11
- 🔄 `main()` L553: 复杂度: 26
- 🔄 `_detect_tts_sample_rate()` L70: 认知复杂度: 16
- 🔄 `iter_sse_lines()` L106: 认知复杂度: 14
- 🔄 `_audio_worker()` L149: 认知复杂度: 13
- 🔄 `authenticate()` L167: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L308: 认知复杂度: 17
- 🔄 `stop_and_send()` L381: 认知复杂度: 14
- 🔄 `_capture_loop()` L415: 认知复杂度: 15
- 🔄 `_loop()` L471: 认知复杂度: 19
- 🔄 `main()` L553: 认知复杂度: 38
- 🔄 `_detect_tts_sample_rate()` L70: 嵌套深度: 5
- 🔄 `_loop()` L471: 嵌套深度: 5
- 🔄 `main()` L553: 嵌套深度: 6
- 📏 `authenticate()` L167: 82 代码量
- 📏 `main()` L553: 120 代码量
- 🏗️ `_detect_tts_sample_rate()` L70: 嵌套过深: 5
- 🏗️ `iter_sse_lines()` L106: 中等嵌套: 3
- 🏗️ `_audio_worker()` L149: 中等嵌套: 3
- 🏗️ `_verify_api_key()` L250: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L308: 中等嵌套: 3
- 🏗️ `_capture_loop()` L415: 中等嵌套: 3
- 🏗️ `_loop()` L471: 嵌套过深: 5
- 🏗️ `main()` L553: 嵌套过深: 6
- 🏗️ L1: 导入过多: 25
- ❌ L75: 未处理的易出错调用
- ❌ L99: 未处理的易出错调用
- ❌ L334: 未处理的易出错调用
- ❌ L399: 未处理的易出错调用
- ❌ L484: 未处理的易出错调用
- ❌ L493: 未处理的易出错调用
- ❌ L539: 未处理的易出错调用
- 🏷️ `_detect_tts_sample_rate()` L70: "_detect_tts_sample_rate" - snake_case
- 🏷️ `__init__()` L137: "__init__" - snake_case
- 🏷️ `_audio_worker()` L149: "_audio_worker" - snake_case
- 🏷️ `_verify_api_key()` L250: "_verify_api_key" - snake_case
- 🏷️ `_headers()` L269: "_headers" - snake_case
- 🏷️ `_http_get()` L274: "_http_get" - snake_case
- 🏷️ `_http_post()` L278: "_http_post" - snake_case
- 🏷️ `_http_post_stream()` L282: "_http_post_stream" - snake_case
- 🏷️ `_handle_sse_stream()` L308: "_handle_sse_stream" - snake_case
- 🏷️ `__init__()` L344: "__init__" - snake_case

**详情**:
- 循环复杂度: 平均: 4.7, 最大: 26
- 认知复杂度: 平均: 8.0, 最大: 38
- 嵌套深度: 平均: 1.6, 最大: 6
- 函数长度: 平均: 19.0 行, 最大: 120 行
- 文件长度: 586 代码量 (682 总计)
- 参数数量: 平均: 1.3, 最大: 3
- 代码重复: 3.2% 重复 (1/31)
- 结构分析: 9 个结构问题
- 错误处理: 7/61 个错误被忽略 (11.5%)
- 注释比例: 0.2% (1/586)
- 命名规范: 发现 13 个违规

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

### 8. plugins/builtin/agent_plugin.py

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

### 9. memory/core.py

**糟糕指数: 27.50**

> 行数: 452 总计, 368 代码, 22 注释 | 函数: 18 | 类: 1

**问题**: 🔄 复杂度问题: 11, ⚠️ 其他问题: 5, 📋 重复问题: 2, 🏗️ 结构问题: 3, ❌ 错误处理问题: 7, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L173-247 | 75 | 18 | 4 | 6 | ✗ |
| `_format_detail_results` | L414-451 | 38 | 13 | 4 | 2 | ✗ |
| `_format_search_results` | L381-411 | 31 | 11 | 2 | 3 | ✗ |
| `handle_tags` | L258-285 | 28 | 9 | 2 | 4 | ✗ |
| `_format_timedelta` | L356-378 | 23 | 9 | 2 | 1 | ✗ |
| `_handle_recall` | L287-308 | 22 | 7 | 3 | 4 | ✗ |
| `summarize_turn` | L69-94 | 26 | 5 | 1 | 7 | ✓ |
| `assemble_context` | L143-167 | 25 | 5 | 1 | 4 | ✗ |
| `_do_summarize` | L96-120 | 25 | 4 | 2 | 6 | ✗ |
| `__init__` | L26-34 | 9 | 2 | 0 | 3 | ✗ |
| `_decrypt` | L60-63 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L314-324 | 11 | 2 | 1 | 4 | ✗ |
| `delete_memo` | L342-349 | 8 | 2 | 1 | 2 | ✗ |
| `_init_table` | L36-53 | 18 | 1 | 0 | 1 | ✗ |
| `_encrypt` | L57-58 | 2 | 1 | 0 | 3 | ✗ |
| `_get_exp_memories` | L122-137 | 16 | 1 | 0 | 3 | ✗ |
| `get_detail` | L249-252 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L326-340 | 15 | 1 | 0 | 3 | ✗ |

**全部问题 (37)**

- 🔄 `search()` L173: 复杂度: 18
- 🔄 `_format_search_results()` L381: 复杂度: 11
- 🔄 `_format_detail_results()` L414: 复杂度: 13
- 🔄 `search()` L173: 认知复杂度: 26
- 🔄 `handle_tags()` L258: 认知复杂度: 13
- 🔄 `_handle_recall()` L287: 认知复杂度: 13
- 🔄 `_format_timedelta()` L356: 认知复杂度: 13
- 🔄 `_format_search_results()` L381: 认知复杂度: 15
- 🔄 `_format_detail_results()` L414: 认知复杂度: 21
- 🔄 `search()` L173: 嵌套深度: 4
- 🔄 `_format_detail_results()` L414: 嵌套深度: 4
- 📏 `search()` L173: 75 代码量
- 📏 `summarize_turn()` L69: 7 参数数量
- 📏 `_do_summarize()` L96: 6 参数数量
- 📏 `search()` L173: 6 参数数量
- 📋 `_get_exp_memories()` L122: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L314: 重复模式: add_memo, delete_memo
- 🏗️ `search()` L173: 中等嵌套: 4
- 🏗️ `_handle_recall()` L287: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L414: 中等嵌套: 4
- ❌ L38: 未处理的易出错调用
- ❌ L49: 未处理的易出错调用
- ❌ L53: 未处理的易出错调用
- ❌ L116: 未处理的易出错调用
- ❌ L323: 未处理的易出错调用
- ❌ L348: 未处理的易出错调用
- ❌ L428: 未处理的易出错调用
- 🏷️ `__init__()` L26: "__init__" - snake_case
- 🏷️ `_init_table()` L36: "_init_table" - snake_case
- 🏷️ `_encrypt()` L57: "_encrypt" - snake_case
- 🏷️ `_decrypt()` L60: "_decrypt" - snake_case
- 🏷️ `_do_summarize()` L96: "_do_summarize" - snake_case
- 🏷️ `_get_exp_memories()` L122: "_get_exp_memories" - snake_case
- 🏷️ `_handle_recall()` L287: "_handle_recall" - snake_case
- 🏷️ `_get_memos()` L326: "_get_memos" - snake_case
- 🏷️ `_format_timedelta()` L356: "_format_timedelta" - snake_case
- 🏷️ `_format_search_results()` L381: "_format_search_results" - snake_case

**详情**:
- 循环复杂度: 平均: 5.2, 最大: 18
- 认知复杂度: 平均: 7.9, 最大: 26
- 嵌套深度: 平均: 1.3, 最大: 4
- 函数长度: 平均: 21.1 行, 最大: 75 行
- 文件长度: 368 代码量 (452 总计)
- 参数数量: 平均: 3.5, 最大: 7
- 代码重复: 11.1% 重复 (2/18)
- 结构分析: 3 个结构问题
- 错误处理: 7/26 个错误被忽略 (26.9%)
- 注释比例: 6.0% (22/368)
- 命名规范: 发现 11 个违规

### 10. stationed.py

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

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `create_engine_with_defaults` | engine.py | 43 | 2 | 237 |
| `process_stream` | plugins/pipeline.py | 40 | 5 | 203 |
| `msgFlow` | psychoscope/static/js/app.js | 38 | 4 | 131 |
| `sendRecording` | psychoscope/static/js/app.js | 36 | 4 | 105 |
| `main` | psychoscope/minimal.py | 26 | 6 | 120 |
| `_run_agent_loop` | plugins/builtin/agent_plugin.py | 21 | 3 | 88 |
| `_collect_state` | stationed.py | 19 | 5 | 77 |
| `main` | main.py | 19 | 3 | 113 |
| `generate_personality_prompt` | prompt/_personality_v1_legacy.py | 19 | 2 | 65 |
| `main` | tests/test_ncm_music.py | 18 | 3 | 97 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*