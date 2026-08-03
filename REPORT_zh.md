# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-78%25-green)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **77.56/100** |
| 屎山等级 | 😐 微臭青年 |

> 略带清香，偶尔飘过一丝酸爽

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 276 |
| 已跳过 | 1239 |
| 耗时 | 1299ms |

### 📋 项目概览

| 指标 | 数值 |
|--------|-------|
| 总代码行数 | 50021 |
| 总注释行数 | 2579 |
| 整体注释比例 | 5.2% |
| 平均文件大小 | 226 行 |
| 最大文件 | `main.py` (3200) |

#### 语言分布

| 语言 | 文件数 |
|:-----|------:|
| Python | 273 |
| JavaScript | 3 |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | Min | Max | Median | 状态 |
|:-----|------:|------:|------:|------:|:------:|
| 循环复杂度 | 10.18% | 0.0% | 80.0% | 3.0% | ✓✓ |
| 认知复杂度 | 13.60% | 0.0% | 70.0% | 8.0% | ✓✓ |
| 嵌套深度 | 4.79% | 0.0% | 75.0% | 0.0% | ✓✓ |
| 函数长度 | 6.29% | 0.0% | 59.5% | 0.0% | ✓✓ |
| 文件长度 | 3.23% | 0.0% | 98.4% | 0.0% | ✓✓ |
| 参数数量 | 13.68% | 0.0% | 98.5% | 0.0% | ✓✓ |
| 代码重复 | 5.49% | 0.0% | 81.7% | 0.0% | ✓✓ |
| 结构分析 | 5.53% | 0.0% | 87.5% | 0.0% | ✓✓ |
| 错误处理 | 31.20% | 0.0% | 98.8% | 4.8% | ✓ |
| 注释比例 | 41.66% | 0.0% | 100.0% | 35.7% | ○ |
| 命名规范 | 31.25% | 0.0% | 100.0% | 25.0% | ✓ |

## 最屎代码排行榜 {#problem-files}

### 1. plugins/pipeline.py

**糟糕指数: 56.25**

> 行数: 1513 总计, 1233 代码, 88 注释 | 函数: 38 | 类: 1

**问题**: 🔄 复杂度问题: 23, ⚠️ 其他问题: 9, 🏗️ 结构问题: 12, ❌ 错误处理问题: 37, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L1101-1512 | 379 | 77 | 9 | 3 | ✓ |
| `_run_agent_loop` | L429-635 | 207 | 41 | 4 | 2 | ✗ |
| `_poll_pending_tasks` | L967-1089 | 123 | 38 | 6 | 4 | ✓ |
| `_synthesize_lines_sync` | L824-925 | 102 | 24 | 2 | 4 | ✓ |
| `process` | L215-308 | 94 | 16 | 3 | 2 | ✗ |
| `_run_async_background` | L314-405 | 51 | 11 | 2 | 2 | ✗ |
| `_run_tool` | L359-399 | 41 | 9 | 4 | 0 | ✓ |
| `_print_timing` | L637-663 | 27 | 9 | 4 | 3 | ✗ |
| `_run_all_plugins` | L937-965 | 29 | 9 | 2 | 5 | ✗ |
| `_format_tag_results` | L675-693 | 19 | 8 | 3 | 1 | ✗ |
| `_assemble_prompt` | L695-728 | 34 | 7 | 2 | 2 | ✓ |
| `_concat_wav` | L155-178 | 24 | 6 | 2 | 1 | ✓ |
| `process_tts` | L180-194 | 15 | 6 | 4 | 2 | ✓ |
| `_dispatch_pre_process` | L732-762 | 31 | 6 | 1 | 2 | ✓ |
| `_call_llm_with_msgs` | L47-74 | 18 | 5 | 2 | 2 | ✓ |
| `_report_agent_progress` | L408-427 | 20 | 5 | 1 | 6 | ✓ |
| `_clone_pre_process_context` | L783-802 | 20 | 5 | 2 | 1 | ✓ |
| `_drain_q` | L1302-1323 | 22 | 5 | 3 | 0 | ✓ |
| `_invoke` | L63-72 | 10 | 4 | 2 | 0 | ✗ |
| `_extract_narrations` | L77-92 | 16 | 4 | 3 | 1 | ✓ |
| `process_post_process` | L205-211 | 7 | 4 | 1 | 3 | ✓ |
| `_print_plugin_timing` | L665-672 | 8 | 4 | 2 | 2 | ✗ |
| `_bridge_progress` | L928-935 | 8 | 3 | 2 | 2 | ✗ |
| `_consume_agent_progress` | L1285-1293 | 9 | 3 | 2 | 2 | ✗ |
| `_desc_tool` | L95-100 | 6 | 2 | 1 | 1 | ✗ |
| `_desc_task` | L103-110 | 8 | 2 | 1 | 1 | ✗ |
| `_log_stage_timing` | L113-116 | 4 | 2 | 1 | 2 | ✗ |
| `process_pre_process` | L196-203 | 8 | 2 | 1 | 2 | ✓ |
| `_merge_pre_process_results` | L765-780 | 16 | 2 | 1 | 3 | ✓ |
| `timer_enabled` | L25-27 | 3 | 1 | 0 | 0 | ✗ |
| `enable_timer` | L30-32 | 3 | 1 | 0 | 0 | ✗ |
| `disable_timer` | L35-37 | 3 | 1 | 0 | 0 | ✗ |
| `toggle_timer` | L40-44 | 5 | 1 | 0 | 0 | ✗ |
| `__init__` | L133-150 | 18 | 1 | 0 | 8 | ✗ |
| `_dispatch_post_process` | L310-312 | 3 | 1 | 0 | 2 | ✗ |
| `_synthesize_lines` | L806-812 | 7 | 1 | 0 | 2 | ✓ |
| `_synthesize_lines_stream` | L814-822 | 9 | 1 | 0 | 3 | ✓ |
| `_sse` | L1121-1122 | 2 | 1 | 0 | 1 | ✓ |

**全部问题 (90)**

- 🔄 `process()` L215: 复杂度: 16
- 🔄 `_run_async_background()` L314: 复杂度: 11
- 🔄 `_run_agent_loop()` L429: 复杂度: 41
- 🔄 `_synthesize_lines_sync()` L824: 复杂度: 24
- 🔄 `_poll_pending_tasks()` L967: 复杂度: 38
- 🔄 `process_stream()` L1101: 复杂度: 77
- 🔄 `process_tts()` L180: 认知复杂度: 14
- 🔄 `process()` L215: 认知复杂度: 22
- 🔄 `_run_async_background()` L314: 认知复杂度: 15
- 🔄 `_run_tool()` L359: 认知复杂度: 17
- 🔄 `_run_agent_loop()` L429: 认知复杂度: 49
- 🔄 `_print_timing()` L637: 认知复杂度: 17
- 🔄 `_format_tag_results()` L675: 认知复杂度: 14
- 🔄 `_synthesize_lines_sync()` L824: 认知复杂度: 28
- 🔄 `_run_all_plugins()` L937: 认知复杂度: 13
- 🔄 `_poll_pending_tasks()` L967: 认知复杂度: 50
- 🔄 `process_stream()` L1101: 认知复杂度: 95
- 🔄 `process_tts()` L180: 嵌套深度: 4
- 🔄 `_run_tool()` L359: 嵌套深度: 4
- 🔄 `_run_agent_loop()` L429: 嵌套深度: 4
- 🔄 `_print_timing()` L637: 嵌套深度: 4
- 🔄 `_poll_pending_tasks()` L967: 嵌套深度: 6
- 🔄 `process_stream()` L1101: 嵌套深度: 9
- 📏 `process()` L215: 94 代码量
- 📏 `_run_async_background()` L314: 51 代码量
- 📏 `_run_agent_loop()` L429: 207 代码量
- 📏 `_synthesize_lines_sync()` L824: 102 代码量
- 📏 `_poll_pending_tasks()` L967: 123 代码量
- 📏 `process_stream()` L1101: 379 代码量
- 📏 `__init__()` L133: 8 参数数量
- 📏 `_report_agent_progress()` L408: 6 参数数量
- 🏗️ `_extract_narrations()` L77: 中等嵌套: 3
- 🏗️ `process_tts()` L180: 中等嵌套: 4
- 🏗️ `process()` L215: 中等嵌套: 3
- 🏗️ `_run_tool()` L359: 中等嵌套: 4
- 🏗️ `_run_agent_loop()` L429: 中等嵌套: 4
- 🏗️ `_print_timing()` L637: 中等嵌套: 4
- 🏗️ `_format_tag_results()` L675: 中等嵌套: 3
- 🏗️ `_poll_pending_tasks()` L967: 嵌套过深: 6
- 🏗️ `process_stream()` L1101: 嵌套过深: 9
- 🏗️ `_drain_q()` L1302: 中等嵌套: 3
- 🏗️ L1: 文件过大: 1513 行
- 🏗️ L1: 导入过多: 30
- ❌ L187: 未处理的易出错调用
- ❌ L209: 未处理的易出错调用
- ❌ L256: 未处理的易出错调用
- ❌ L273: 未处理的易出错调用
- ❌ L290: 未处理的易出错调用
- ❌ L321: 未处理的易出错调用
- ❌ L376: 未处理的易出错调用
- ❌ L377: 未处理的易出错调用
- ❌ L378: 未处理的易出错调用
- ❌ L399: 未处理的易出错调用
- ❌ L416: 未处理的易出错调用
- ❌ L427: 未处理的易出错调用
- ❌ L465: 未处理的易出错调用
- ❌ L487: 未处理的易出错调用
- ❌ L512: 未处理的易出错调用
- ❌ L604: 未处理的易出错调用
- ❌ L690: 未处理的易出错调用
- ❌ L850: 未处理的易出错调用
- ❌ L917: 未处理的易出错调用
- ❌ L921: 未处理的易出错调用
- ❌ L924: 未处理的易出错调用
- ❌ L935: 未处理的易出错调用
- ❌ L942: 未处理的易出错调用
- ❌ L964: 未处理的易出错调用
- ❌ L965: 未处理的易出错调用
- ❌ L999: 未处理的易出错调用
- ❌ L1024: 未处理的易出错调用
- ❌ L1061: 未处理的易出错调用
- ❌ L1155: 未处理的易出错调用
- ❌ L1172: 未处理的易出错调用
- ❌ L1293: 未处理的易出错调用
- ❌ L1413: 未处理的易出错调用
- ❌ L1427: 未处理的易出错调用
- ❌ L1444: 未处理的易出错调用
- ❌ L1464: 未处理的易出错调用
- ❌ L1504: 未处理的易出错调用
- ❌ L1506: 未处理的易出错调用
- 🏷️ `_call_llm_with_msgs()` L47: "_call_llm_with_msgs" - snake_case
- 🏷️ `_invoke()` L63: "_invoke" - snake_case
- 🏷️ `_extract_narrations()` L77: "_extract_narrations" - snake_case
- 🏷️ `_desc_tool()` L95: "_desc_tool" - snake_case
- 🏷️ `_desc_task()` L103: "_desc_task" - snake_case
- 🏷️ `_log_stage_timing()` L113: "_log_stage_timing" - snake_case
- 🏷️ `__init__()` L133: "__init__" - snake_case
- 🏷️ `_concat_wav()` L155: "_concat_wav" - snake_case
- 🏷️ `_dispatch_post_process()` L310: "_dispatch_post_process" - snake_case
- 🏷️ `_run_async_background()` L314: "_run_async_background" - snake_case

**详情**:
- 循环复杂度: 平均: 8.6, 最大: 77
- 认知复杂度: 平均: 12.5, 最大: 95
- 嵌套深度: 平均: 1.9, 最大: 9
- 函数长度: 平均: 37.1 行, 最大: 379 行
- 文件长度: 1233 代码量 (1513 总计)
- 参数数量: 平均: 2.0, 最大: 8
- 代码重复: 2.6% 重复 (1/38)
- 结构分析: 12 个结构问题
- 错误处理: 37/88 个错误被忽略 (42.0%)
- 注释比例: 7.1% (88/1233)
- 命名规范: 发现 29 个违规

### 2. psychoscope/minimal.py

**糟糕指数: 52.14**

> 行数: 2344 总计, 1951 代码, 88 注释 | 函数: 100 | 类: 7

**问题**: 🔄 复杂度问题: 42, ⚠️ 其他问题: 9, 🏗️ 结构问题: 24, ❌ 错误处理问题: 37, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `main` | L1936-2339 | 391 | 112 | 9 | 0 | ✗ |
| `_handle_sse_stream` | L1155-1258 | 104 | 38 | 4 | 5 | ✗ |
| `_beat` | L1505-1602 | 98 | 28 | 4 | 1 | ✗ |
| `_loop` | L1300-1364 | 65 | 24 | 6 | 1 | ✗ |
| `_poll_loop` | L557-593 | 37 | 18 | 5 | 1 | ✗ |
| `_enumerate_cameras` | L88-156 | 62 | 14 | 4 | 1 | ✓ |
| `authenticate` | L915-996 | 82 | 14 | 2 | 3 | ✗ |
| `print_cameras` | L1841-1882 | 42 | 14 | 5 | 2 | ✓ |
| `raw_input` | L379-403 | 25 | 13 | 3 | 1 | ✓ |
| `_tts_worker` | L856-913 | 58 | 13 | 5 | 1 | ✗ |
| `_loop` | L1416-1437 | 22 | 10 | 3 | 1 | ✗ |
| `stop_and_send` | L1716-1748 | 33 | 10 | 2 | 1 | ✗ |
| `print_system_info` | L1894-1929 | 36 | 10 | 4 | 1 | ✗ |
| `_scan_devices` | L159-189 | 31 | 9 | 4 | 2 | ✓ |
| `iter_sse_lines` | L766-787 | 22 | 9 | 4 | 1 | ✗ |
| `_capture_loop` | L1750-1780 | 31 | 9 | 3 | 1 | ✗ |
| `read_key` | L351-376 | 26 | 8 | 3 | 1 | ✓ |
| `_play_beep` | L596-632 | 37 | 8 | 3 | 2 | ✗ |
| `prompt_mic_selection` | L1630-1657 | 28 | 8 | 2 | 1 | ✓ |
| `play_index` | L436-463 | 28 | 7 | 3 | 2 | ✗ |
| `toggle` | L465-477 | 13 | 7 | 2 | 1 | ✗ |
| `_resolve_camera` | L204-215 | 12 | 6 | 1 | 1 | ✓ |
| `_capture_camera_frame` | L646-675 | 30 | 6 | 2 | 1 | ✓ |
| `_capture_and_save_frame` | L738-763 | 26 | 6 | 2 | 2 | ✓ |
| `prompt_backend_host` | L803-820 | 18 | 6 | 4 | 1 | ✓ |
| `send_audio` | L1051-1088 | 38 | 6 | 2 | 2 | ✗ |
| `send_text` | L1090-1124 | 35 | 6 | 2 | 2 | ✗ |
| `_send_worker` | L1136-1153 | 18 | 6 | 3 | 1 | ✗ |
| `_parse_camera_map` | L74-85 | 12 | 5 | 2 | 1 | ✗ |
| `_cached_camera_frame` | L691-704 | 14 | 5 | 2 | 1 | ✓ |
| `_capture_all_cameras` | L707-735 | 17 | 5 | 2 | 0 | ✓ |
| `_verify_api_key` | L998-1015 | 18 | 5 | 3 | 1 | ✗ |
| `send_async` | L1034-1049 | 16 | 5 | 2 | 2 | ✗ |
| `configure` | L1385-1395 | 11 | 5 | 0 | 4 | ✓ |
| `skip_latest` | L1474-1491 | 18 | 5 | 2 | 1 | ✗ |
| `_loop` | L1493-1503 | 11 | 5 | 3 | 1 | ✗ |
| `_default_backends` | L192-201 | 10 | 4 | 1 | 0 | ✓ |
| `_ensure_raw_mode` | L341-348 | 8 | 4 | 2 | 0 | ✓ |
| `duck` | L509-515 | 7 | 4 | 2 | 1 | ✗ |
| `unduck` | L517-522 | 6 | 4 | 2 | 1 | ✗ |
| `cleanup` | L534-545 | 12 | 4 | 2 | 1 | ✗ |
| `start` | L1397-1409 | 13 | 4 | 1 | 1 | ✗ |
| `start` | L1694-1714 | 21 | 4 | 1 | 1 | ✗ |
| `_camera_backend_for` | L218-224 | 7 | 3 | 1 | 1 | ✓ |
| `_exit_unix` | L305-312 | 8 | 3 | 2 | 1 | ✗ |
| `__init__` | L411-424 | 14 | 3 | 1 | 3 | ✗ |
| `load_playlist` | L426-434 | 9 | 3 | 2 | 1 | ✗ |
| `stop` | L479-486 | 8 | 3 | 2 | 1 | ✗ |
| `next` | L488-492 | 5 | 3 | 1 | 1 | ✗ |
| `prev` | L494-498 | 5 | 3 | 1 | 1 | ✗ |
| `audio_set_volume` | L500-507 | 8 | 3 | 2 | 2 | ✗ |
| `_report_state` | L547-555 | 9 | 3 | 1 | 1 | ✗ |
| `_grab` | L716-727 | 12 | 3 | 1 | 1 | ✗ |
| `load_config` | L790-796 | 7 | 3 | 2 | 0 | ✗ |
| `stop_tts` | L847-854 | 8 | 3 | 2 | 1 | ✗ |
| `add_task` | L1292-1298 | 7 | 3 | 2 | 2 | ✗ |
| `_list_microphones` | L1619-1627 | 9 | 3 | 1 | 0 | ✓ |
| `_device_index` | L1677-1684 | 8 | 3 | 1 | 0 | ✓ |
| `print_personality` | L1813-1838 | 26 | 3 | 2 | 1 | ✗ |
| `_report_cameras_background` | L2018-2026 | 9 | 3 | 2 | 0 | ✓ |
| `_scan` | L108-114 | 7 | 2 | 1 | 0 | ✗ |
| `_open_camera` | L227-232 | 6 | 2 | 1 | 1 | ✓ |
| `setup_logging` | L252-267 | 16 | 2 | 1 | 0 | ✗ |
| `enter_raw` | L286-290 | 5 | 2 | 1 | 1 | ✗ |
| `exit_raw` | L292-296 | 5 | 2 | 1 | 1 | ✗ |
| `stop_poll` | L529-532 | 4 | 2 | 1 | 1 | ✗ |
| `raw_pcm_to_wav_b64` | L635-643 | 9 | 2 | 1 | 2 | ✗ |
| `_store_frame_cache` | L686-688 | 3 | 2 | 1 | 2 | ✗ |
| `__init__` | L828-845 | 18 | 2 | 1 | 3 | ✗ |
| `_headers` | L1017-1020 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L1278-1284 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L1286-1290 | 5 | 2 | 1 | 1 | ✗ |
| `stop` | L1411-1414 | 4 | 2 | 1 | 1 | ✗ |
| `start` | L1458-1464 | 7 | 2 | 1 | 1 | ✗ |
| `stop` | L1466-1469 | 4 | 2 | 1 | 1 | ✗ |
| `has_frames` | L1691-1692 | 2 | 2 | 0 | 1 | ✗ |
| `print_header` | L1787-1810 | 24 | 2 | 1 | 3 | ✗ |
| `toggle_standby` | L1885-1891 | 7 | 2 | 1 | 1 | ✗ |
| `__init__` | L281-284 | 4 | 1 | 0 | 1 | ✗ |
| `_enter_unix` | L298-303 | 6 | 1 | 0 | 1 | ✗ |
| `_enter_windows` | L314-316 | 3 | 1 | 0 | 1 | ✗ |
| `_exit_windows` | L318-319 | 2 | 1 | 0 | 1 | ✗ |
| `raw_mode` | L326-338 | 13 | 1 | 1 | 0 | ✓ |
| `start_poll` | L524-527 | 4 | 1 | 0 | 1 | ✗ |
| `save_config` | L799-800 | 2 | 1 | 0 | 1 | ✗ |
| `_http_get` | L1022-1024 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post` | L1026-1028 | 3 | 1 | 0 | 2 | ✗ |
| `_http_post_stream` | L1030-1032 | 3 | 1 | 0 | 2 | ✗ |
| `is_sending` | L1127-1128 | 2 | 1 | 0 | 1 | ✗ |
| `send_audio_async` | L1130-1131 | 2 | 1 | 0 | 2 | ✗ |
| `send_text_async` | L1133-1134 | 2 | 1 | 0 | 2 | ✗ |
| `__init__` | L1269-1276 | 8 | 1 | 0 | 3 | ✗ |
| `__init__` | L1377-1383 | 7 | 1 | 0 | 2 | ✗ |
| `__init__` | L1448-1456 | 9 | 1 | 0 | 4 | ✗ |
| `sync_now` | L1471-1472 | 2 | 1 | 0 | 1 | ✗ |
| `_type_label` | L1605-1610 | 6 | 1 | 0 | 1 | ✗ |
| `__init__` | L1665-1674 | 10 | 1 | 0 | 2 | ✗ |
| `is_recording` | L1687-1688 | 2 | 1 | 0 | 1 | ✗ |
| `_early_sigint` | L1944-1945 | 2 | 1 | 0 | 2 | ✓ |
| `_sigint` | L2048-2049 | 2 | 1 | 0 | 2 | ✗ |

**全部问题 (120)**

- 🔄 `_enumerate_cameras()` L88: 复杂度: 14
- 🔄 `raw_input()` L379: 复杂度: 13
- 🔄 `_poll_loop()` L557: 复杂度: 18
- 🔄 `_tts_worker()` L856: 复杂度: 13
- 🔄 `authenticate()` L915: 复杂度: 14
- 🔄 `_handle_sse_stream()` L1155: 复杂度: 38
- 🔄 `_loop()` L1300: 复杂度: 24
- 🔄 `_beat()` L1505: 复杂度: 28
- 🔄 `print_cameras()` L1841: 复杂度: 14
- 🔄 `main()` L1936: 复杂度: 112
- 🔄 `_enumerate_cameras()` L88: 认知复杂度: 22
- 🔄 `_scan_devices()` L159: 认知复杂度: 17
- 🔄 `read_key()` L351: 认知复杂度: 14
- 🔄 `raw_input()` L379: 认知复杂度: 19
- 🔄 `play_index()` L436: 认知复杂度: 13
- 🔄 `_poll_loop()` L557: 认知复杂度: 28
- 🔄 `_play_beep()` L596: 认知复杂度: 14
- 🔄 `iter_sse_lines()` L766: 认知复杂度: 17
- 🔄 `prompt_backend_host()` L803: 认知复杂度: 14
- 🔄 `_tts_worker()` L856: 认知复杂度: 23
- 🔄 `authenticate()` L915: 认知复杂度: 18
- 🔄 `_handle_sse_stream()` L1155: 认知复杂度: 46
- 🔄 `_loop()` L1300: 认知复杂度: 36
- 🔄 `_loop()` L1416: 认知复杂度: 16
- 🔄 `_beat()` L1505: 认知复杂度: 36
- 🔄 `stop_and_send()` L1716: 认知复杂度: 14
- 🔄 `_capture_loop()` L1750: 认知复杂度: 15
- 🔄 `print_cameras()` L1841: 认知复杂度: 24
- 🔄 `print_system_info()` L1894: 认知复杂度: 18
- 🔄 `main()` L1936: 认知复杂度: 130
- 🔄 `_enumerate_cameras()` L88: 嵌套深度: 4
- 🔄 `_scan_devices()` L159: 嵌套深度: 4
- 🔄 `_poll_loop()` L557: 嵌套深度: 5
- 🔄 `iter_sse_lines()` L766: 嵌套深度: 4
- 🔄 `prompt_backend_host()` L803: 嵌套深度: 4
- 🔄 `_tts_worker()` L856: 嵌套深度: 5
- 🔄 `_handle_sse_stream()` L1155: 嵌套深度: 4
- 🔄 `_loop()` L1300: 嵌套深度: 6
- 🔄 `_beat()` L1505: 嵌套深度: 4
- 🔄 `print_cameras()` L1841: 嵌套深度: 5
- 🔄 `print_system_info()` L1894: 嵌套深度: 4
- 🔄 `main()` L1936: 嵌套深度: 9
- 📏 `_enumerate_cameras()` L88: 62 代码量
- 📏 `_tts_worker()` L856: 58 代码量
- 📏 `authenticate()` L915: 82 代码量
- 📏 `_handle_sse_stream()` L1155: 104 代码量
- 📏 `_loop()` L1300: 65 代码量
- 📏 `_beat()` L1505: 98 代码量
- 📏 `main()` L1936: 391 代码量
- 🏗️ `_enumerate_cameras()` L88: 中等嵌套: 4
- 🏗️ `_scan_devices()` L159: 中等嵌套: 4
- 🏗️ `read_key()` L351: 中等嵌套: 3
- 🏗️ `raw_input()` L379: 中等嵌套: 3
- 🏗️ `play_index()` L436: 中等嵌套: 3
- 🏗️ `_poll_loop()` L557: 嵌套过深: 5
- 🏗️ `_play_beep()` L596: 中等嵌套: 3
- 🏗️ `iter_sse_lines()` L766: 中等嵌套: 4
- 🏗️ `prompt_backend_host()` L803: 中等嵌套: 4
- 🏗️ `_tts_worker()` L856: 嵌套过深: 5
- 🏗️ `_verify_api_key()` L998: 中等嵌套: 3
- 🏗️ `_send_worker()` L1136: 中等嵌套: 3
- 🏗️ `_handle_sse_stream()` L1155: 中等嵌套: 4
- 🏗️ `_loop()` L1300: 嵌套过深: 6
- 🏗️ `_loop()` L1416: 中等嵌套: 3
- 🏗️ `_loop()` L1493: 中等嵌套: 3
- 🏗️ `_beat()` L1505: 中等嵌套: 4
- 🏗️ `_capture_loop()` L1750: 中等嵌套: 3
- 🏗️ `print_cameras()` L1841: 嵌套过深: 5
- 🏗️ `print_system_info()` L1894: 中等嵌套: 4
- 🏗️ `main()` L1936: 嵌套过深: 9
- 🏗️ L1: 文件过大: 2344 行
- 🏗️ L1: 函数过多: 100
- 🏗️ L1: 导入过多: 35
- ❌ L144: 未处理的易出错调用
- ❌ L394: 未处理的易出错调用
- ❌ L402: 未处理的易出错调用
- ❌ L453: 未处理的易出错调用
- ❌ L454: 未处理的易出错调用
- ❌ L608: 未处理的易出错调用
- ❌ L615: 未处理的易出错调用
- ❌ L616: 未处理的易出错调用
- ❌ L638: 未处理的易出错调用
- ❌ L876: 未处理的易出错调用
- ❌ L877: 未处理的易出错调用
- ❌ L886: 未处理的易出错调用
- ❌ L1131: 未处理的易出错调用
- ❌ L1134: 未处理的易出错调用
- ❌ L1187: 未处理的易出错调用
- ❌ L1203: 未处理的易出错调用
- ❌ L1215: 未处理的易出错调用
- ❌ L1252: 未处理的易出错调用
- ❌ L1325: 未处理的易出错调用
- ❌ L1338: 未处理的易出错调用
- ❌ L1356: 未处理的易出错调用
- ❌ L1487: 未处理的易出错调用
- ❌ L1529: 未处理的易出错调用
- ❌ L1530: 未处理的易出错调用
- ❌ L1532: 未处理的易出错调用
- ❌ L1566: 未处理的易出错调用
- ❌ L1588: 未处理的易出错调用
- ❌ L1734: 未处理的易出错调用
- ❌ L1834: 未处理的易出错调用
- ❌ L1859: 未处理的易出错调用
- ❌ L1860: 未处理的易出错调用
- ❌ L1900: 未处理的易出错调用
- ❌ L1925: 未处理的易出错调用
- ❌ L1984: 未处理的易出错调用
- ❌ L2193: 未处理的易出错调用
- ❌ L2241: 未处理的易出错调用
- ❌ L2276: 未处理的易出错调用
- 🏷️ `_parse_camera_map()` L74: "_parse_camera_map" - snake_case
- 🏷️ `_enumerate_cameras()` L88: "_enumerate_cameras" - snake_case
- 🏷️ `_scan()` L108: "_scan" - snake_case
- 🏷️ `_scan_devices()` L159: "_scan_devices" - snake_case
- 🏷️ `_default_backends()` L192: "_default_backends" - snake_case
- 🏷️ `_resolve_camera()` L204: "_resolve_camera" - snake_case
- 🏷️ `_camera_backend_for()` L218: "_camera_backend_for" - snake_case
- 🏷️ `_open_camera()` L227: "_open_camera" - snake_case
- 🏷️ `__init__()` L281: "__init__" - snake_case
- 🏷️ `_enter_unix()` L298: "_enter_unix" - snake_case

**详情**:
- 循环复杂度: 平均: 6.0, 最大: 112
- 认知复杂度: 平均: 9.4, 最大: 130
- 嵌套深度: 平均: 1.7, 最大: 9
- 函数长度: 平均: 20.4 行, 最大: 391 行
- 文件长度: 1951 代码量 (2344 总计)
- 参数数量: 平均: 1.3, 最大: 5
- 代码重复: 4.0% 重复 (4/100)
- 结构分析: 24 个结构问题
- 错误处理: 37/166 个错误被忽略 (22.3%)
- 注释比例: 4.5% (88/1951)
- 命名规范: 发现 48 个违规

### 3. main.py

**糟糕指数: 51.72**

> 行数: 3200 总计, 2630 代码, 66 注释 | 函数: 86 | 类: 1

**问题**: 🔄 复杂度问题: 56, ⚠️ 其他问题: 41, 🏗️ 结构问题: 17, ❌ 错误处理问题: 32, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_cmd_login` | L1007-1158 | 152 | 42 | 2 | 1 | ✓ |
| `_cmd_agent` | L2408-2552 | 145 | 34 | 3 | 3 | ✓ |
| `_cmd_reminder` | L813-939 | 127 | 31 | 4 | 2 | ✓ |
| `_cmd_memory_query` | L1629-1759 | 131 | 31 | 3 | 2 | ✓ |
| `main` | L3000-3195 | 182 | 31 | 3 | 0 | ✗ |
| `_cmd_plan` | L942-1004 | 63 | 21 | 2 | 2 | ✓ |
| `_cmd_memory_rebuild` | L1762-1885 | 116 | 21 | 3 | 2 | ✓ |
| `_cmd_hibernate_task` | L2915-2985 | 71 | 20 | 4 | 2 | ✗ |
| `_cmd_hibernate_check` | L2741-2830 | 90 | 19 | 3 | 1 | ✗ |
| `_cmd_cleanup_users` | L343-411 | 69 | 17 | 3 | 2 | ✓ |
| `_cmd_memory_list` | L1984-2067 | 84 | 17 | 2 | 4 | ✓ |
| `_cmd_login_schedule` | L1266-1309 | 44 | 16 | 2 | 2 | ✓ |
| `_dynamic_show` | L1365-1434 | 70 | 16 | 2 | 1 | ✗ |
| `_cmd_login_timeslot` | L1215-1263 | 49 | 14 | 2 | 2 | ✓ |
| `_cmd_export` | L648-736 | 89 | 13 | 2 | 2 | ✓ |
| `_persona_status` | L2317-2378 | 62 | 13 | 4 | 2 | ✗ |
| `_cmd_login_dynamic` | L1312-1362 | 51 | 12 | 2 | 2 | ✓ |
| `_cmd_memory` | L1548-1579 | 32 | 12 | 2 | 3 | ✓ |
| `_cmd_import` | L739-810 | 72 | 11 | 2 | 2 | ✓ |
| `_cmd_plugin` | L1492-1545 | 54 | 11 | 2 | 2 | ✓ |
| `_cmd_persona` | L2275-2314 | 40 | 11 | 2 | 2 | ✓ |
| `_check_port_available` | L153-207 | 55 | 10 | 5 | 2 | ✗ |
| `_env_write` | L210-242 | 33 | 10 | 5 | 2 | ✓ |
| `_login_list` | L1161-1200 | 40 | 10 | 3 | 1 | ✗ |
| `_persona_materials` | L2596-2626 | 31 | 10 | 2 | 2 | ✗ |
| `_cmd_hibernate` | L2685-2738 | 54 | 10 | 1 | 2 | ✗ |
| `_is_env_configured` | L31-51 | 21 | 9 | 4 | 0 | ✗ |
| `_cmd_users` | L414-452 | 39 | 9 | 2 | 2 | ✓ |
| `_cmd_status` | L455-491 | 37 | 9 | 2 | 2 | ✓ |
| `_cmd_detail` | L2117-2146 | 30 | 9 | 2 | 1 | ✓ |
| `_cmd_memory_reindex` | L1582-1626 | 31 | 8 | 1 | 1 | ✓ |
| `_execute_command` | L2149-2181 | 33 | 8 | 2 | 9 | ✗ |
| `_cmd_hibernate_interval` | L2875-2912 | 38 | 8 | 2 | 2 | ✗ |
| `_cmd_config` | L537-569 | 33 | 7 | 2 | 2 | ✓ |
| `_cmd_hibernate_archive` | L2833-2872 | 40 | 7 | 2 | 2 | ✗ |
| `_cmd_memory_users` | L1888-1936 | 49 | 6 | 1 | 2 | ✓ |
| `_cmd_memory_chats` | L1939-1981 | 43 | 6 | 1 | 2 | ✓ |
| `_cmd_prompt` | L2070-2096 | 27 | 6 | 1 | 2 | ✓ |
| `_env_backup_rotate` | L100-115 | 16 | 5 | 3 | 0 | ✓ |
| `_enable_console_logging` | L281-299 | 19 | 5 | 2 | 0 | ✗ |
| `_try_convert` | L517-534 | 18 | 5 | 2 | 2 | ✓ |
| `_cmd_config_listall` | L572-591 | 20 | 5 | 2 | 1 | ✓ |
| `_cmd_config_set` | L594-621 | 28 | 5 | 1 | 3 | ✓ |
| `_run_index` | L1609-1622 | 14 | 5 | 2 | 0 | ✗ |
| `_persona_list` | L2556-2593 | 38 | 5 | 1 | 1 | ✗ |
| `_persona_rollback` | L2629-2660 | 32 | 5 | 1 | 2 | ✗ |
| `_env_backup_restore` | L118-137 | 20 | 4 | 2 | 0 | ✓ |
| `_mask_value` | L506-514 | 9 | 4 | 2 | 2 | ✗ |
| `_login_add` | L1203-1212 | 10 | 4 | 1 | 2 | ✗ |
| `_run` | L1873-1880 | 8 | 4 | 2 | 0 | ✗ |
| `_handle_steward_chat` | L3129-3142 | 14 | 4 | 1 | 1 | ✗ |
| `_env_backup_count` | L140-150 | 11 | 3 | 2 | 0 | ✗ |
| `_disable_console_logging` | L302-312 | 11 | 3 | 2 | 0 | ✗ |
| `_cmd_newbind` | L326-340 | 15 | 3 | 1 | 1 | ✓ |
| `_cmd_config_undo` | L624-640 | 17 | 3 | 1 | 0 | ✓ |
| `_run` | L2391-2402 | 12 | 3 | 2 | 0 | ✗ |
| `_persona_do_rollback` | L2670-2682 | 13 | 3 | 1 | 2 | ✓ |
| `append_log` | L245-248 | 4 | 2 | 1 | 3 | ✗ |
| `get_logs_snapshot` | L251-253 | 3 | 2 | 1 | 0 | ✗ |
| `_install_log_handler` | L256-274 | 17 | 2 | 1 | 0 | ✗ |
| `_h_plugin` | L2196-2197 | 2 | 2 | 0 | 7 | ✗ |
| `_h_timer` | L2244-2249 | 6 | 2 | 0 | 7 | ✗ |
| `_persona_distill` | L2381-2405 | 13 | 2 | 1 | 2 | ✗ |
| `_cmd_hibernate_sleep` | L2988-2997 | 10 | 2 | 1 | 1 | ✗ |
| `_restart_process` | L26-28 | 3 | 1 | 0 | 0 | ✓ |
| `emit` | L268-269 | 2 | 1 | 0 | 2 | ✗ |
| `_cmd_listconfig` | L643-645 | 3 | 1 | 0 | 1 | ✓ |
| `_cmd_help` | L1437-1489 | 53 | 1 | 0 | 0 | ✓ |
| `_cmd_memory_help` | L2099-2114 | 16 | 1 | 0 | 0 | ✓ |
| `_h_newbind` | L2184-2185 | 2 | 1 | 0 | 7 | ✗ |
| `_h_cleanup_users` | L2187-2188 | 2 | 1 | 0 | 7 | ✗ |
| `_h_users` | L2190-2191 | 2 | 1 | 0 | 7 | ✗ |
| `_h_status` | L2193-2194 | 2 | 1 | 0 | 7 | ✗ |
| `_h_memory` | L2199-2200 | 2 | 1 | 0 | 7 | ✗ |
| `_h_prompt` | L2202-2203 | 2 | 1 | 0 | 7 | ✗ |
| `_h_config` | L2205-2206 | 2 | 1 | 0 | 7 | ✗ |
| `_h_listconfig` | L2208-2209 | 2 | 1 | 0 | 7 | ✗ |
| `_h_persona` | L2211-2212 | 2 | 1 | 0 | 7 | ✗ |
| `_h_help` | L2214-2215 | 2 | 1 | 0 | 7 | ✗ |
| `_h_login` | L2217-2218 | 2 | 1 | 0 | 7 | ✗ |
| `_h_agent` | L2220-2221 | 2 | 1 | 0 | 7 | ✗ |
| `_h_export` | L2224-2225 | 2 | 1 | 0 | 7 | ✗ |
| `_h_import` | L2228-2229 | 2 | 1 | 0 | 7 | ✗ |
| `_h_reminder` | L2232-2233 | 2 | 1 | 0 | 7 | ✗ |
| `_h_plan` | L2236-2237 | 2 | 1 | 0 | 7 | ✗ |
| `_h_detail` | L2240-2241 | 2 | 1 | 0 | 7 | ✗ |

**全部问题 (155)**

- 🔄 `_cmd_cleanup_users()` L343: 复杂度: 17
- 🔄 `_cmd_export()` L648: 复杂度: 13
- 🔄 `_cmd_import()` L739: 复杂度: 11
- 🔄 `_cmd_reminder()` L813: 复杂度: 31
- 🔄 `_cmd_plan()` L942: 复杂度: 21
- 🔄 `_cmd_login()` L1007: 复杂度: 42
- 🔄 `_cmd_login_timeslot()` L1215: 复杂度: 14
- 🔄 `_cmd_login_schedule()` L1266: 复杂度: 16
- 🔄 `_cmd_login_dynamic()` L1312: 复杂度: 12
- 🔄 `_dynamic_show()` L1365: 复杂度: 16
- 🔄 `_cmd_plugin()` L1492: 复杂度: 11
- 🔄 `_cmd_memory()` L1548: 复杂度: 12
- 🔄 `_cmd_memory_query()` L1629: 复杂度: 31
- 🔄 `_cmd_memory_rebuild()` L1762: 复杂度: 21
- 🔄 `_cmd_memory_list()` L1984: 复杂度: 17
- 🔄 `_cmd_persona()` L2275: 复杂度: 11
- 🔄 `_persona_status()` L2317: 复杂度: 13
- 🔄 `_cmd_agent()` L2408: 复杂度: 34
- 🔄 `_cmd_hibernate_check()` L2741: 复杂度: 19
- 🔄 `_cmd_hibernate_task()` L2915: 复杂度: 20
- 🔄 `main()` L3000: 复杂度: 31
- 🔄 `_is_env_configured()` L31: 认知复杂度: 17
- 🔄 `_check_port_available()` L153: 认知复杂度: 20
- 🔄 `_env_write()` L210: 认知复杂度: 20
- 🔄 `_cmd_cleanup_users()` L343: 认知复杂度: 23
- 🔄 `_cmd_users()` L414: 认知复杂度: 13
- 🔄 `_cmd_status()` L455: 认知复杂度: 13
- 🔄 `_cmd_export()` L648: 认知复杂度: 17
- 🔄 `_cmd_import()` L739: 认知复杂度: 15
- 🔄 `_cmd_reminder()` L813: 认知复杂度: 39
- 🔄 `_cmd_plan()` L942: 认知复杂度: 25
- 🔄 `_cmd_login()` L1007: 认知复杂度: 46
- 🔄 `_login_list()` L1161: 认知复杂度: 16
- 🔄 `_cmd_login_timeslot()` L1215: 认知复杂度: 18
- 🔄 `_cmd_login_schedule()` L1266: 认知复杂度: 20
- 🔄 `_cmd_login_dynamic()` L1312: 认知复杂度: 16
- 🔄 `_dynamic_show()` L1365: 认知复杂度: 20
- 🔄 `_cmd_plugin()` L1492: 认知复杂度: 15
- 🔄 `_cmd_memory()` L1548: 认知复杂度: 16
- 🔄 `_cmd_memory_query()` L1629: 认知复杂度: 37
- 🔄 `_cmd_memory_rebuild()` L1762: 认知复杂度: 27
- 🔄 `_cmd_memory_list()` L1984: 认知复杂度: 21
- 🔄 `_cmd_detail()` L2117: 认知复杂度: 13
- 🔄 `_cmd_persona()` L2275: 认知复杂度: 15
- 🔄 `_persona_status()` L2317: 认知复杂度: 21
- 🔄 `_cmd_agent()` L2408: 认知复杂度: 40
- 🔄 `_persona_materials()` L2596: 认知复杂度: 14
- 🔄 `_cmd_hibernate_check()` L2741: 认知复杂度: 25
- 🔄 `_cmd_hibernate_task()` L2915: 认知复杂度: 28
- 🔄 `main()` L3000: 认知复杂度: 37
- 🔄 `_is_env_configured()` L31: 嵌套深度: 4
- 🔄 `_check_port_available()` L153: 嵌套深度: 5
- 🔄 `_env_write()` L210: 嵌套深度: 5
- 🔄 `_cmd_reminder()` L813: 嵌套深度: 4
- 🔄 `_persona_status()` L2317: 嵌套深度: 4
- 🔄 `_cmd_hibernate_task()` L2915: 嵌套深度: 4
- 📏 `_check_port_available()` L153: 55 代码量
- 📏 `_cmd_cleanup_users()` L343: 69 代码量
- 📏 `_cmd_export()` L648: 89 代码量
- 📏 `_cmd_import()` L739: 72 代码量
- 📏 `_cmd_reminder()` L813: 127 代码量
- 📏 `_cmd_plan()` L942: 63 代码量
- 📏 `_cmd_login()` L1007: 152 代码量
- 📏 `_cmd_login_dynamic()` L1312: 51 代码量
- 📏 `_dynamic_show()` L1365: 70 代码量
- 📏 `_cmd_help()` L1437: 53 代码量
- 📏 `_cmd_plugin()` L1492: 54 代码量
- 📏 `_cmd_memory_query()` L1629: 131 代码量
- 📏 `_cmd_memory_rebuild()` L1762: 116 代码量
- 📏 `_cmd_memory_list()` L1984: 84 代码量
- 📏 `_persona_status()` L2317: 62 代码量
- 📏 `_cmd_agent()` L2408: 145 代码量
- 📏 `_cmd_hibernate()` L2685: 54 代码量
- 📏 `_cmd_hibernate_check()` L2741: 90 代码量
- 📏 `_cmd_hibernate_task()` L2915: 71 代码量
- 📏 `main()` L3000: 182 代码量
- 📏 `_execute_command()` L2149: 9 参数数量
- 📏 `_h_newbind()` L2184: 7 参数数量
- 📏 `_h_cleanup_users()` L2187: 7 参数数量
- 📏 `_h_users()` L2190: 7 参数数量
- 📏 `_h_status()` L2193: 7 参数数量
- 📏 `_h_plugin()` L2196: 7 参数数量
- 📏 `_h_memory()` L2199: 7 参数数量
- 📏 `_h_prompt()` L2202: 7 参数数量
- 📏 `_h_config()` L2205: 7 参数数量
- 📏 `_h_listconfig()` L2208: 7 参数数量
- 📏 `_h_persona()` L2211: 7 参数数量
- 📏 `_h_help()` L2214: 7 参数数量
- 📏 `_h_login()` L2217: 7 参数数量
- 📏 `_h_agent()` L2220: 7 参数数量
- 📏 `_h_export()` L2224: 7 参数数量
- 📏 `_h_import()` L2228: 7 参数数量
- 📏 `_h_reminder()` L2232: 7 参数数量
- 📏 `_h_plan()` L2236: 7 参数数量
- 📏 `_h_detail()` L2240: 7 参数数量
- 📏 `_h_timer()` L2244: 7 参数数量
- 🏗️ `_is_env_configured()` L31: 中等嵌套: 4
- 🏗️ `_env_backup_rotate()` L100: 中等嵌套: 3
- 🏗️ `_check_port_available()` L153: 嵌套过深: 5
- 🏗️ `_env_write()` L210: 嵌套过深: 5
- 🏗️ `_cmd_cleanup_users()` L343: 中等嵌套: 3
- 🏗️ `_cmd_reminder()` L813: 中等嵌套: 4
- 🏗️ `_login_list()` L1161: 中等嵌套: 3
- 🏗️ `_cmd_memory_query()` L1629: 中等嵌套: 3
- 🏗️ `_cmd_memory_rebuild()` L1762: 中等嵌套: 3
- 🏗️ `_persona_status()` L2317: 中等嵌套: 4
- 🏗️ `_cmd_agent()` L2408: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_check()` L2741: 中等嵌套: 3
- 🏗️ `_cmd_hibernate_task()` L2915: 中等嵌套: 4
- 🏗️ `main()` L3000: 中等嵌套: 3
- 🏗️ L1: 文件过大: 3200 行
- 🏗️ L1: 函数过多: 86
- 🏗️ L1: 导入过多: 47
- ❌ L166: 未处理的易出错调用
- ❌ L410: 未处理的易出错调用
- ❌ L440: 未处理的易出错调用
- ❌ L448: 未处理的易出错调用
- ❌ L781: 未处理的易出错调用
- ❌ L787: 未处理的易出错调用
- ❌ L801: 未处理的易出错调用
- ❌ L807: 未处理的易出错调用
- ❌ L1181: 未处理的易出错调用
- ❌ L1182: 未处理的易出错调用
- ❌ L1193: 未处理的易出错调用
- ❌ L1196: 未处理的易出错调用
- ❌ L1197: 未处理的易出错调用
- ❌ L1237: 未处理的易出错调用
- ❌ L1238: 未处理的易出错调用
- ❌ L1285: 未处理的易出错调用
- ❌ L1286: 未处理的易出错调用
- ❌ L1323: 未处理的易出错调用
- ❌ L1340: 未处理的易出错调用
- ❌ L1373: 未处理的易出错调用
- ❌ L1389: 未处理的易出错调用
- ❌ L1390: 未处理的易出错调用
- ❌ L1412: 未处理的易出错调用
- ❌ L1540: 未处理的易出错调用
- ❌ L1933: 未处理的易出错调用
- ❌ L1934: 未处理的易出错调用
- ❌ L2064: 未处理的易出错调用
- ❌ L2364: 未处理的易出错调用
- ❌ L2551: 未处理的易出错调用
- ❌ L2584: 未处理的易出错调用
- ❌ L2585: 未处理的易出错调用
- ❌ L2586: 未处理的易出错调用
- 🏷️ `_restart_process()` L26: "_restart_process" - snake_case
- 🏷️ `_is_env_configured()` L31: "_is_env_configured" - snake_case
- 🏷️ `_env_backup_rotate()` L100: "_env_backup_rotate" - snake_case
- 🏷️ `_env_backup_restore()` L118: "_env_backup_restore" - snake_case
- 🏷️ `_env_backup_count()` L140: "_env_backup_count" - snake_case
- 🏷️ `_check_port_available()` L153: "_check_port_available" - snake_case
- 🏷️ `_env_write()` L210: "_env_write" - snake_case
- 🏷️ `_install_log_handler()` L256: "_install_log_handler" - snake_case
- 🏷️ `_enable_console_logging()` L281: "_enable_console_logging" - snake_case
- 🏷️ `_disable_console_logging()` L302: "_disable_console_logging" - snake_case

**详情**:
- 循环复杂度: 平均: 7.8, 最大: 42
- 认知复杂度: 平均: 10.8, 最大: 46
- 嵌套深度: 平均: 1.5, 最大: 5
- 函数长度: 平均: 33.9 行, 最大: 182 行
- 文件长度: 2630 代码量 (3200 总计)
- 参数数量: 平均: 2.7, 最大: 9
- 代码重复: 1.2% 重复 (1/86)
- 结构分析: 17 个结构问题
- 错误处理: 32/106 个错误被忽略 (30.2%)
- 注释比例: 2.5% (66/2630)
- 命名规范: 发现 83 个违规

### 4. plugins/builtin/models_plugin.py

**糟糕指数: 45.73**

> 行数: 451 总计, 391 代码, 14 注释 | 函数: 11 | 类: 1

**问题**: 🔄 复杂度问题: 7, ⚠️ 其他问题: 4, 🏗️ 结构问题: 4, ❌ 错误处理问题: 3, 📝 注释问题: 1, 🏷️ 命名问题: 6

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `on_hook` | L61-216 | 156 | 40 | 7 | 3 | ✗ |
| `invoke` | L361-438 | 78 | 23 | 6 | 4 | ✗ |
| `_build_tools_schema` | L218-246 | 29 | 10 | 3 | 2 | ✗ |
| `_build_toolbox_schema` | L248-287 | 40 | 7 | 1 | 2 | ✗ |
| `_build_full_schema` | L289-304 | 16 | 5 | 3 | 1 | ✗ |
| `_create_chat` | L306-335 | 30 | 5 | 2 | 2 | ✗ |
| `set_skill_registry` | L51-55 | 5 | 3 | 0 | 2 | ✗ |
| `_clean_reply` | L338-359 | 22 | 2 | 1 | 1 | ✗ |
| `__init__` | L23-49 | 27 | 1 | 0 | 12 | ✗ |
| `on_load` | L57-59 | 3 | 1 | 0 | 1 | ✗ |
| `describe_image` | L440-450 | 11 | 1 | 0 | 3 | ✗ |

**全部问题 (23)**

- 🔄 `on_hook()` L61: 复杂度: 40
- 🔄 `invoke()` L361: 复杂度: 23
- 🔄 `on_hook()` L61: 认知复杂度: 54
- 🔄 `_build_tools_schema()` L218: 认知复杂度: 16
- 🔄 `invoke()` L361: 认知复杂度: 35
- 🔄 `on_hook()` L61: 嵌套深度: 7
- 🔄 `invoke()` L361: 嵌套深度: 6
- 📏 `on_hook()` L61: 156 代码量
- 📏 `invoke()` L361: 78 代码量
- 📏 `__init__()` L23: 12 参数数量
- 🏗️ `on_hook()` L61: 嵌套过深: 7
- 🏗️ `_build_tools_schema()` L218: 中等嵌套: 3
- 🏗️ `_build_full_schema()` L289: 中等嵌套: 3
- 🏗️ `invoke()` L361: 嵌套过深: 6
- ❌ L182: 未处理的易出错调用
- ❌ L203: 未处理的易出错调用
- ❌ L243: 未处理的易出错调用
- 🏷️ `__init__()` L23: "__init__" - snake_case
- 🏷️ `_build_tools_schema()` L218: "_build_tools_schema" - snake_case
- 🏷️ `_build_toolbox_schema()` L248: "_build_toolbox_schema" - snake_case
- 🏷️ `_build_full_schema()` L289: "_build_full_schema" - snake_case
- 🏷️ `_create_chat()` L306: "_create_chat" - snake_case
- 🏷️ `_clean_reply()` L338: "_clean_reply" - snake_case

**详情**:
- 循环复杂度: 平均: 8.9, 最大: 40
- 认知复杂度: 平均: 13.1, 最大: 54
- 嵌套深度: 平均: 2.1, 最大: 7
- 函数长度: 平均: 37.9 行, 最大: 156 行
- 文件长度: 391 代码量 (451 总计)
- 参数数量: 平均: 3.0, 最大: 12
- 代码重复: 0.0% 重复 (0/11)
- 结构分析: 4 个结构问题
- 错误处理: 3/22 个错误被忽略 (13.6%)
- 注释比例: 3.6% (14/391)
- 命名规范: 发现 6 个违规

### 5. engine.py

**糟糕指数: 45.21**

> 行数: 1337 总计, 1076 代码, 53 注释 | 函数: 42 | 类: 2

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 11, 🏗️ 结构问题: 11, ❌ 错误处理问题: 11, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_init_plugins_via_loader` | L628-724 | 97 | 38 | 5 | 1 | ✓ |
| `create_engine_with_defaults` | L1134-1336 | 203 | 36 | 5 | 12 | ✓ |
| `_init_prompt` | L572-623 | 52 | 17 | 4 | 1 | ✗ |
| `build_context` | L739-776 | 38 | 13 | 1 | 8 | ✓ |
| `chat_debug_respond` | L906-979 | 74 | 11 | 2 | 4 | ✓ |
| `_generate_result_message` | L315-371 | 57 | 9 | 2 | 3 | ✗ |
| `chat` | L817-854 | 38 | 9 | 2 | 8 | ✓ |
| `_dispatch_task_completion` | L237-251 | 15 | 8 | 2 | 3 | ✗ |
| `_inject_system_skill_deps` | L520-552 | 33 | 8 | 3 | 1 | ✓ |
| `chat_stream` | L856-876 | 21 | 8 | 1 | 8 | ✓ |
| `_handle_engine_action_completion` | L253-271 | 19 | 7 | 2 | 4 | ✗ |
| `_get_event_loop` | L44-55 | 12 | 6 | 3 | 0 | ✗ |
| `_retry_engine_action` | L373-398 | 26 | 6 | 2 | 4 | ✗ |
| `_init_memory` | L400-432 | 33 | 6 | 3 | 1 | ✗ |
| `_init_world` | L434-463 | 30 | 6 | 2 | 1 | ✗ |
| `_init_skills` | L494-518 | 25 | 6 | 2 | 1 | ✗ |
| `_inject_v3_to_exa_evolution` | L554-570 | 17 | 6 | 3 | 1 | ✓ |
| `chat_debug` | L880-904 | 25 | 6 | 0 | 6 | ✓ |
| `index_prompts_for_chat` | L1027-1047 | 21 | 6 | 2 | 3 | ✓ |
| `run_scheduled` | L1051-1099 | 32 | 6 | 2 | 1 | ✓ |
| `get_info` | L1107-1115 | 9 | 6 | 0 | 1 | ✓ |
| `_process_task_completion` | L217-235 | 19 | 5 | 3 | 1 | ✗ |
| `_dump_context_for_session` | L985-1019 | 35 | 5 | 3 | 2 | ✓ |
| `_init_tts` | L465-492 | 28 | 4 | 2 | 1 | ✗ |
| `from_subapp` | L87-104 | 18 | 3 | 0 | 1 | ✓ |
| `__init__` | L118-152 | 35 | 3 | 1 | 2 | ✗ |
| `_init_tasks` | L190-213 | 24 | 3 | 1 | 1 | ✗ |
| `_handle_reasoner_completion` | L293-314 | 22 | 3 | 1 | 3 | ✗ |
| `_get_skills_info` | L781-802 | 22 | 3 | 2 | 1 | ✗ |
| `_get_tool_parameters` | L803-815 | 13 | 3 | 2 | 2 | ✗ |
| `_init_database` | L177-188 | 12 | 2 | 0 | 1 | ✗ |
| `_handle_reminder_completion` | L273-291 | 19 | 2 | 1 | 3 | ✓ |
| `create_chat` | L1021-1022 | 2 | 2 | 0 | 3 | ✗ |
| `get_history` | L1024-1025 | 2 | 2 | 0 | 3 | ✗ |
| `job` | L1063-1069 | 7 | 2 | 1 | 0 | ✗ |
| `cron_loop` | L1073-1082 | 10 | 2 | 1 | 0 | ✗ |
| `_init_from_subapp` | L156-175 | 20 | 1 | 0 | 1 | ✗ |
| `_init_plugins` | L624-626 | 3 | 1 | 0 | 1 | ✓ |
| `_init_pipeline` | L725-735 | 11 | 1 | 0 | 1 | ✗ |
| `_is_debug_mode` | L778-779 | 2 | 1 | 0 | 1 | ✗ |
| `process_tts` | L981-983 | 3 | 1 | 0 | 2 | ✓ |
| `create_engine` | L1120-1133 | 14 | 1 | 0 | 1 | ✓ |

**全部问题 (58)**

- 🔄 `_init_prompt()` L572: 复杂度: 17
- 🔄 `_init_plugins_via_loader()` L628: 复杂度: 38
- 🔄 `build_context()` L739: 复杂度: 13
- 🔄 `chat_debug_respond()` L906: 复杂度: 11
- 🔄 `create_engine_with_defaults()` L1134: 复杂度: 36
- 🔄 `_generate_result_message()` L315: 认知复杂度: 13
- 🔄 `_inject_system_skill_deps()` L520: 认知复杂度: 14
- 🔄 `_init_prompt()` L572: 认知复杂度: 25
- 🔄 `_init_plugins_via_loader()` L628: 认知复杂度: 48
- 🔄 `build_context()` L739: 认知复杂度: 15
- 🔄 `chat()` L817: 认知复杂度: 13
- 🔄 `chat_debug_respond()` L906: 认知复杂度: 15
- 🔄 `create_engine_with_defaults()` L1134: 认知复杂度: 46
- 🔄 `_init_prompt()` L572: 嵌套深度: 4
- 🔄 `_init_plugins_via_loader()` L628: 嵌套深度: 5
- 🔄 `create_engine_with_defaults()` L1134: 嵌套深度: 5
- 📏 `_generate_result_message()` L315: 57 代码量
- 📏 `_init_prompt()` L572: 52 代码量
- 📏 `_init_plugins_via_loader()` L628: 97 代码量
- 📏 `chat_debug_respond()` L906: 74 代码量
- 📏 `create_engine_with_defaults()` L1134: 203 代码量
- 📏 `build_context()` L739: 8 参数数量
- 📏 `chat()` L817: 8 参数数量
- 📏 `chat_stream()` L856: 8 参数数量
- 📏 `chat_debug()` L880: 6 参数数量
- 📏 `create_engine_with_defaults()` L1134: 12 参数数量
- 🏗️ `_get_event_loop()` L44: 中等嵌套: 3
- 🏗️ `_process_task_completion()` L217: 中等嵌套: 3
- 🏗️ `_init_memory()` L400: 中等嵌套: 3
- 🏗️ `_inject_system_skill_deps()` L520: 中等嵌套: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L554: 中等嵌套: 3
- 🏗️ `_init_prompt()` L572: 中等嵌套: 4
- 🏗️ `_init_plugins_via_loader()` L628: 嵌套过深: 5
- 🏗️ `_dump_context_for_session()` L985: 中等嵌套: 3
- 🏗️ `create_engine_with_defaults()` L1134: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1337 行
- 🏗️ L1: 导入过多: 63
- ❌ L241: 未处理的易出错调用
- ❌ L254: 未处理的易出错调用
- ❌ L268: 未处理的易出错调用
- ❌ L331: 未处理的易出错调用
- ❌ L790: 未处理的易出错调用
- ❌ L791: 未处理的易出错调用
- ❌ L792: 未处理的易出错调用
- ❌ L793: 未处理的易出错调用
- ❌ L794: 未处理的易出错调用
- ❌ L811: 未处理的易出错调用
- ❌ L1067: 未处理的易出错调用
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
- 循环复杂度: 平均: 6.5, 最大: 38
- 认知复杂度: 平均: 9.7, 最大: 48
- 嵌套深度: 平均: 1.6, 最大: 5
- 函数长度: 平均: 28.5 行, 最大: 203 行
- 文件长度: 1076 代码量 (1337 总计)
- 参数数量: 平均: 2.5, 最大: 12
- 代码重复: 4.8% 重复 (2/42)
- 结构分析: 11 个结构问题
- 错误处理: 11/48 个错误被忽略 (22.9%)
- 注释比例: 4.9% (53/1076)
- 命名规范: 发现 26 个违规

### 6. memory/core.py

**糟糕指数: 43.65**

> 行数: 924 总计, 702 代码, 66 注释 | 函数: 28 | 类: 1

**问题**: 🔄 复杂度问题: 18, ⚠️ 其他问题: 10, 📋 重复问题: 2, 🏗️ 结构问题: 6, ❌ 错误处理问题: 16, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `search` | L299-427 | 129 | 39 | 7 | 7 | ✓ |
| `reindex_embeddings` | L438-530 | 93 | 17 | 4 | 2 | ✓ |
| `_format_detail_results` | L869-923 | 55 | 16 | 4 | 2 | ✗ |
| `assemble_context` | L243-293 | 51 | 14 | 3 | 4 | ✓ |
| `_format_search_results` | L833-866 | 34 | 11 | 2 | 3 | ✗ |
| `_inject_unsynced_agent_chat` | L762-790 | 29 | 10 | 2 | 4 | ✓ |
| `handle_tags` | L651-678 | 28 | 9 | 2 | 4 | ✓ |
| `_handle_recall` | L680-710 | 31 | 9 | 3 | 4 | ✗ |
| `_format_timedelta` | L805-830 | 26 | 9 | 2 | 1 | ✗ |
| `rebuild_summaries` | L536-601 | 66 | 8 | 3 | 2 | ✓ |
| `_cosine_similarity` | L222-233 | 12 | 6 | 1 | 2 | ✗ |
| `summarize_turn` | L101-126 | 26 | 5 | 1 | 7 | ✓ |
| `_do_summarize` | L128-166 | 39 | 5 | 2 | 6 | ✗ |
| `_build_round_text` | L602-621 | 20 | 5 | 2 | 4 | ✓ |
| `_build_round_messages` | L622-641 | 20 | 5 | 2 | 4 | ✓ |
| `_embed_raw_round` | L192-211 | 20 | 4 | 2 | 6 | ✓ |
| `__init__` | L25-39 | 15 | 3 | 0 | 4 | ✗ |
| `_get_bound_agent` | L752-760 | 9 | 3 | 1 | 2 | ✓ |
| `_decrypt` | L92-95 | 4 | 2 | 1 | 3 | ✗ |
| `add_memo` | L720-735 | 16 | 2 | 1 | 4 | ✓ |
| `delete_memo` | L791-798 | 8 | 2 | 1 | 2 | ✗ |
| `_init_table` | L41-77 | 37 | 1 | 0 | 1 | ✗ |
| `_encrypt` | L85-91 | 7 | 1 | 0 | 3 | ✓ |
| `_get_exp_memories` | L167-182 | 16 | 1 | 0 | 2 | ✗ |
| `_pack_embedding` | L214-215 | 2 | 1 | 0 | 1 | ✗ |
| `_unpack_embedding` | L218-219 | 2 | 1 | 0 | 1 | ✗ |
| `get_detail` | L429-432 | 4 | 1 | 0 | 4 | ✗ |
| `_get_memos` | L736-750 | 15 | 1 | 0 | 2 | ✗ |

**全部问题 (61)**

- 🔄 `assemble_context()` L243: 复杂度: 14
- 🔄 `search()` L299: 复杂度: 39
- 🔄 `reindex_embeddings()` L438: 复杂度: 17
- 🔄 `_format_search_results()` L833: 复杂度: 11
- 🔄 `_format_detail_results()` L869: 复杂度: 16
- 🔄 `assemble_context()` L243: 认知复杂度: 20
- 🔄 `search()` L299: 认知复杂度: 53
- 🔄 `reindex_embeddings()` L438: 认知复杂度: 25
- 🔄 `rebuild_summaries()` L536: 认知复杂度: 14
- 🔄 `handle_tags()` L651: 认知复杂度: 13
- 🔄 `_handle_recall()` L680: 认知复杂度: 15
- 🔄 `_inject_unsynced_agent_chat()` L762: 认知复杂度: 14
- 🔄 `_format_timedelta()` L805: 认知复杂度: 13
- 🔄 `_format_search_results()` L833: 认知复杂度: 15
- 🔄 `_format_detail_results()` L869: 认知复杂度: 24
- 🔄 `search()` L299: 嵌套深度: 7
- 🔄 `reindex_embeddings()` L438: 嵌套深度: 4
- 🔄 `_format_detail_results()` L869: 嵌套深度: 4
- 📏 `assemble_context()` L243: 51 代码量
- 📏 `search()` L299: 129 代码量
- 📏 `reindex_embeddings()` L438: 93 代码量
- 📏 `rebuild_summaries()` L536: 66 代码量
- 📏 `_format_detail_results()` L869: 55 代码量
- 📏 `summarize_turn()` L101: 7 参数数量
- 📏 `_do_summarize()` L128: 6 参数数量
- 📏 `_embed_raw_round()` L192: 6 参数数量
- 📏 `search()` L299: 7 参数数量
- 📋 `_get_exp_memories()` L167: 重复模式: _get_exp_memories, _get_memos
- 📋 `add_memo()` L720: 重复模式: add_memo, delete_memo
- 🏗️ `assemble_context()` L243: 中等嵌套: 3
- 🏗️ `search()` L299: 嵌套过深: 7
- 🏗️ `reindex_embeddings()` L438: 中等嵌套: 4
- 🏗️ `rebuild_summaries()` L536: 中等嵌套: 3
- 🏗️ `_handle_recall()` L680: 中等嵌套: 3
- 🏗️ `_format_detail_results()` L869: 中等嵌套: 4
- ❌ L47: 未处理的易出错调用
- ❌ L58: 未处理的易出错调用
- ❌ L62: 未处理的易出错调用
- ❌ L73: 未处理的易出错调用
- ❌ L77: 未处理的易出错调用
- ❌ L153: 未处理的易出错调用
- ❌ L203: 未处理的易出错调用
- ❌ L208: 未处理的易出错调用
- ❌ L517: 未处理的易出错调用
- ❌ L522: 未处理的易出错调用
- ❌ L583: 未处理的易出错调用
- ❌ L587: 未处理的易出错调用
- ❌ L729: 未处理的易出错调用
- ❌ L780: 未处理的易出错调用
- ❌ L797: 未处理的易出错调用
- ❌ L886: 未处理的易出错调用
- 🏷️ `__init__()` L25: "__init__" - snake_case
- 🏷️ `_init_table()` L41: "_init_table" - snake_case
- 🏷️ `_encrypt()` L85: "_encrypt" - snake_case
- 🏷️ `_decrypt()` L92: "_decrypt" - snake_case
- 🏷️ `_do_summarize()` L128: "_do_summarize" - snake_case
- 🏷️ `_get_exp_memories()` L167: "_get_exp_memories" - snake_case
- 🏷️ `_embed_raw_round()` L192: "_embed_raw_round" - snake_case
- 🏷️ `_pack_embedding()` L214: "_pack_embedding" - snake_case
- 🏷️ `_unpack_embedding()` L218: "_unpack_embedding" - snake_case
- 🏷️ `_cosine_similarity()` L222: "_cosine_similarity" - snake_case

**详情**:
- 循环复杂度: 平均: 6.8, 最大: 39
- 认知复杂度: 平均: 10.1, 最大: 53
- 嵌套深度: 平均: 1.6, 最大: 7
- 函数长度: 平均: 29.1 行, 最大: 129 行
- 文件长度: 702 代码量 (924 总计)
- 参数数量: 平均: 3.3, 最大: 7
- 代码重复: 7.1% 重复 (2/28)
- 结构分析: 6 个结构问题
- 错误处理: 16/38 个错误被忽略 (42.1%)
- 注释比例: 9.4% (66/702)
- 命名规范: 发现 19 个违规

### 7. models/clients.py

**糟糕指数: 39.96**

> 行数: 1365 总计, 1080 代码, 41 注释 | 函数: 60 | 类: 6

**问题**: 🔄 复杂度问题: 18, ⚠️ 其他问题: 13, 🏗️ 结构问题: 8, ❌ 错误处理问题: 4, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `_call_and_append` | L204-309 | 106 | 24 | 3 | 4 | ✗ |
| `_call_llm` | L847-961 | 60 | 17 | 5 | 7 | ✓ |
| `_do_request` | L869-923 | 55 | 15 | 3 | 0 | ✗ |
| `_ocr_single` | L1104-1165 | 57 | 13 | 5 | 3 | ✗ |
| `ask` | L1217-1281 | 65 | 13 | 1 | 6 | ✓ |
| `_call_embed_api` | L719-780 | 41 | 11 | 5 | 2 | ✓ |
| `__init__` | L123-169 | 47 | 9 | 1 | 11 | ✗ |
| `describe_images` | L573-618 | 46 | 9 | 2 | 5 | ✓ |
| `classify_image` | L620-667 | 48 | 8 | 2 | 4 | ✓ |
| `__init__` | L806-846 | 41 | 8 | 1 | 8 | ✗ |
| `__init__` | L1045-1071 | 27 | 8 | 1 | 5 | ✗ |
| `summarize_text` | L963-984 | 22 | 7 | 1 | 3 | ✓ |
| `summarize_dialog` | L989-1026 | 38 | 7 | 2 | 3 | ✓ |
| `_is_no_model_error` | L34-42 | 9 | 6 | 1 | 1 | ✓ |
| `__init__` | L364-414 | 51 | 6 | 1 | 8 | ✓ |
| `_do_call_chat_api` | L432-454 | 23 | 6 | 4 | 2 | ✓ |
| `_call_and_append` | L469-506 | 38 | 6 | 2 | 1 | ✗ |
| `describe_image` | L539-571 | 33 | 6 | 1 | 5 | ✓ |
| `classify_image` | L1311-1330 | 20 | 6 | 2 | 3 | ✓ |
| `_unload_lmstudio_model` | L85-106 | 22 | 5 | 2 | 2 | ✓ |
| `__init__` | L1197-1209 | 13 | 5 | 1 | 5 | ✗ |
| `send_message` | L456-463 | 8 | 4 | 1 | 2 | ✓ |
| `__init__` | L682-702 | 21 | 4 | 0 | 6 | ✗ |
| `embed` | L704-711 | 8 | 4 | 1 | 2 | ✓ |
| `ocr_batch` | L1078-1103 | 26 | 4 | 1 | 3 | ✓ |
| `_load_lmstudio_model` | L58-84 | 27 | 3 | 1 | 4 | ✓ |
| `send_message` | L171-182 | 12 | 3 | 1 | 5 | ✗ |
| `last_tool_calls` | L191-202 | 12 | 3 | 1 | 1 | ✗ |
| `_call_chat_api` | L421-430 | 10 | 3 | 2 | 2 | ✓ |
| `_do_request` | L724-744 | 21 | 3 | 1 | 0 | ✗ |
| `_do_request` | L1124-1128 | 5 | 3 | 1 | 0 | ✗ |
| `ask_raw` | L1283-1307 | 25 | 3 | 1 | 5 | ✓ |
| `ocr_md` | L1332-1346 | 15 | 3 | 1 | 3 | ✓ |
| `embed_batch` | L713-717 | 5 | 2 | 1 | 2 | ✓ |
| `ocr` | L1073-1076 | 4 | 2 | 0 | 3 | ✓ |
| `ocr_md_batch` | L1348-1361 | 14 | 2 | 1 | 3 | ✓ |
| `toggle_detail_chats` | L20-24 | 5 | 1 | 0 | 0 | ✓ |
| `toggle_detail_actions` | L27-31 | 5 | 1 | 0 | 0 | ✓ |
| `_post_json` | L45-57 | 13 | 1 | 0 | 5 | ✓ |
| `continue_conversation` | L184-188 | 5 | 1 | 0 | 4 | ✗ |
| `reset_conversation` | L311-318 | 8 | 1 | 0 | 1 | ✓ |
| `get_history` | L320-326 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L328-343 | 16 | 1 | 0 | 2 | ✓ |
| `set_api_key` | L345-352 | 8 | 1 | 0 | 2 | ✓ |
| `__repr__` | L354-355 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L416-417 | 2 | 1 | 0 | 1 | ✗ |
| `continue_conversation` | L465-467 | 3 | 1 | 0 | 1 | ✓ |
| `reset_conversation` | L508-511 | 4 | 1 | 0 | 1 | ✓ |
| `get_history` | L513-519 | 7 | 1 | 0 | 1 | ✓ |
| `set_model` | L521-528 | 8 | 1 | 0 | 2 | ✓ |
| `set_base_url` | L530-537 | 8 | 1 | 0 | 2 | ✓ |
| `__repr__` | L669-670 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_model_loaded` | L782-783 | 2 | 1 | 0 | 1 | ✗ |
| `__repr__` | L785-786 | 2 | 1 | 0 | 1 | ✗ |
| `_auto_load_model` | L986-987 | 2 | 1 | 0 | 1 | ✗ |
| `_ensure_loaded` | L1167-1168 | 2 | 1 | 0 | 1 | ✗ |
| `unload` | L1170-1172 | 3 | 1 | 0 | 1 | ✗ |
| `__repr__` | L1174-1179 | 6 | 1 | 0 | 1 | ✗ |
| `encode_image` | L1212-1215 | 4 | 1 | 0 | 2 | ✓ |
| `__repr__` | L1363-1364 | 2 | 1 | 0 | 1 | ✗ |

**全部问题 (52)**

- 🔄 `_call_and_append()` L204: 复杂度: 24
- 🔄 `_call_embed_api()` L719: 复杂度: 11
- 🔄 `_call_llm()` L847: 复杂度: 17
- 🔄 `_do_request()` L869: 复杂度: 15
- 🔄 `_ocr_single()` L1104: 复杂度: 13
- 🔄 `ask()` L1217: 复杂度: 13
- 🔄 `_call_and_append()` L204: 认知复杂度: 30
- 🔄 `_do_call_chat_api()` L432: 认知复杂度: 14
- 🔄 `describe_images()` L573: 认知复杂度: 13
- 🔄 `_call_embed_api()` L719: 认知复杂度: 21
- 🔄 `_call_llm()` L847: 认知复杂度: 27
- 🔄 `_do_request()` L869: 认知复杂度: 21
- 🔄 `_ocr_single()` L1104: 认知复杂度: 23
- 🔄 `ask()` L1217: 认知复杂度: 15
- 🔄 `_do_call_chat_api()` L432: 嵌套深度: 4
- 🔄 `_call_embed_api()` L719: 嵌套深度: 5
- 🔄 `_call_llm()` L847: 嵌套深度: 5
- 🔄 `_ocr_single()` L1104: 嵌套深度: 5
- 📏 `_call_and_append()` L204: 106 代码量
- 📏 `__init__()` L364: 51 代码量
- 📏 `_call_llm()` L847: 60 代码量
- 📏 `_do_request()` L869: 55 代码量
- 📏 `_ocr_single()` L1104: 57 代码量
- 📏 `ask()` L1217: 65 代码量
- 📏 `__init__()` L123: 11 参数数量
- 📏 `__init__()` L364: 8 参数数量
- 📏 `__init__()` L682: 6 参数数量
- 📏 `__init__()` L806: 8 参数数量
- 📏 `_call_llm()` L847: 7 参数数量
- 📏 `ask()` L1217: 6 参数数量
- 🏗️ `_call_and_append()` L204: 中等嵌套: 3
- 🏗️ `_do_call_chat_api()` L432: 中等嵌套: 4
- 🏗️ `_call_embed_api()` L719: 嵌套过深: 5
- 🏗️ `_call_llm()` L847: 嵌套过深: 5
- 🏗️ `_do_request()` L869: 中等嵌套: 3
- 🏗️ `_ocr_single()` L1104: 嵌套过深: 5
- 🏗️ L1: 文件过大: 1365 行
- 🏗️ L1: 函数过多: 60
- ❌ L73: 未处理的易出错调用
- ❌ L193: 未处理的易出错调用
- ❌ L267: 未处理的易出错调用
- ❌ L270: 未处理的易出错调用
- 🏷️ `_is_no_model_error()` L34: "_is_no_model_error" - snake_case
- 🏷️ `_post_json()` L45: "_post_json" - snake_case
- 🏷️ `_load_lmstudio_model()` L58: "_load_lmstudio_model" - snake_case
- 🏷️ `_unload_lmstudio_model()` L85: "_unload_lmstudio_model" - snake_case
- 🏷️ `__init__()` L123: "__init__" - snake_case
- 🏷️ `_call_and_append()` L204: "_call_and_append" - snake_case
- 🏷️ `__repr__()` L354: "__repr__" - snake_case
- 🏷️ `__init__()` L364: "__init__" - snake_case
- 🏷️ `_ensure_model_loaded()` L416: "_ensure_model_loaded" - snake_case
- 🏷️ `_call_chat_api()` L421: "_call_chat_api" - snake_case

**详情**:
- 循环复杂度: 平均: 4.4, 最大: 24
- 认知复杂度: 平均: 6.4, 最大: 30
- 嵌套深度: 平均: 1.0, 最大: 5
- 函数长度: 平均: 20.0 行, 最大: 106 行
- 文件长度: 1080 代码量 (1365 总计)
- 参数数量: 平均: 2.7, 最大: 11
- 代码重复: 5.0% 重复 (3/60)
- 结构分析: 8 个结构问题
- 错误处理: 4/31 个错误被忽略 (12.9%)
- 注释比例: 3.8% (41/1080)
- 命名规范: 发现 29 个违规

### 8. boot.py

**糟糕指数: 39.84**

> 行数: 882 总计, 740 代码, 47 注释 | 函数: 14 | 类: 1

**问题**: 🔄 复杂度问题: 10, ⚠️ 其他问题: 3, 📋 重复问题: 2, 🏗️ 结构问题: 4, ❌ 错误处理问题: 8, 📝 注释问题: 1, 🏷️ 命名问题: 10

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `create_application` | L389-881 | 493 | 63 | 5 | 0 | ✓ |
| `process_task_completion` | L206-233 | 28 | 15 | 4 | 0 | ✗ |
| `_preload_models` | L292-363 | 72 | 13 | 2 | 1 | ✓ |
| `_synthesize_tts_lines` | L141-164 | 24 | 11 | 2 | 1 | ✗ |
| `_handle_action_completion` | L262-287 | 26 | 8 | 2 | 3 | ✗ |
| `create_chat_client` | L66-91 | 26 | 6 | 3 | 1 | ✗ |
| `_convert_audio_to_wav` | L122-138 | 17 | 5 | 2 | 1 | ✗ |
| `_process_image_input` | L94-109 | 16 | 4 | 1 | 2 | ✗ |
| `_t` | L373-384 | 12 | 4 | 1 | 2 | ✗ |
| `_handle_reasoner_completion` | L252-259 | 8 | 3 | 1 | 2 | ✗ |
| `_save_debug_audio` | L112-119 | 8 | 2 | 1 | 1 | ✗ |
| `setup_logging` | L167-203 | 34 | 2 | 1 | 1 | ✗ |
| `_handle_reminder_completion` | L236-249 | 14 | 2 | 1 | 2 | ✓ |
| `filter` | L198-200 | 3 | 1 | 0 | 2 | ✗ |

**全部问题 (36)**

- 🔄 `_synthesize_tts_lines()` L141: 复杂度: 11
- 🔄 `process_task_completion()` L206: 复杂度: 15
- 🔄 `_preload_models()` L292: 复杂度: 13
- 🔄 `create_application()` L389: 复杂度: 63
- 🔄 `_synthesize_tts_lines()` L141: 认知复杂度: 15
- 🔄 `process_task_completion()` L206: 认知复杂度: 23
- 🔄 `_preload_models()` L292: 认知复杂度: 17
- 🔄 `create_application()` L389: 认知复杂度: 73
- 🔄 `process_task_completion()` L206: 嵌套深度: 4
- 🔄 `create_application()` L389: 嵌套深度: 5
- 📏 `_preload_models()` L292: 72 代码量
- 📏 `create_application()` L389: 493 代码量
- 📋 `_save_debug_audio()` L112: 重复模式: _save_debug_audio, _handle_reasoner_completion
- 📋 `process_task_completion()` L206: 重复模式: process_task_completion, _handle_reminder_completion
- 🏗️ `create_chat_client()` L66: 中等嵌套: 3
- 🏗️ `process_task_completion()` L206: 中等嵌套: 4
- 🏗️ `create_application()` L389: 嵌套过深: 5
- 🏗️ L1: 导入过多: 65
- ❌ L117: 未处理的易出错调用
- ❌ L118: 未处理的易出错调用
- ❌ L160: 未处理的易出错调用
- ❌ L218: 未处理的易出错调用
- ❌ L219: 未处理的易出错调用
- ❌ L519: 未处理的易出错调用
- ❌ L526: 未处理的易出错调用
- ❌ L802: 未处理的易出错调用
- 🏷️ `_process_image_input()` L94: "_process_image_input" - snake_case
- 🏷️ `_save_debug_audio()` L112: "_save_debug_audio" - snake_case
- 🏷️ `_convert_audio_to_wav()` L122: "_convert_audio_to_wav" - snake_case
- 🏷️ `_synthesize_tts_lines()` L141: "_synthesize_tts_lines" - snake_case
- 🏷️ `_handle_reminder_completion()` L236: "_handle_reminder_completion" - snake_case
- 🏷️ `_handle_reasoner_completion()` L252: "_handle_reasoner_completion" - snake_case
- 🏷️ `_handle_action_completion()` L262: "_handle_action_completion" - snake_case
- 🏷️ `_preload_models()` L292: "_preload_models" - snake_case
- 🏷️ `_t()` L373: "_t" - snake_case
- 🏷️ L196: "_NoiseFilter" - PascalCase

**详情**:
- 循环复杂度: 平均: 9.9, 最大: 63
- 认知复杂度: 平均: 13.6, 最大: 73
- 嵌套深度: 平均: 1.9, 最大: 5
- 函数长度: 平均: 55.8 行, 最大: 493 行
- 文件长度: 740 代码量 (882 总计)
- 参数数量: 平均: 1.4, 最大: 3
- 代码重复: 14.3% 重复 (2/14)
- 结构分析: 4 个结构问题
- 错误处理: 8/38 个错误被忽略 (21.1%)
- 注释比例: 6.4% (47/740)
- 命名规范: 发现 10 个违规

### 9. dual/coordinator.py

**糟糕指数: 38.58**

> 行数: 247 总计, 196 代码, 21 注释 | 函数: 5 | 类: 1

**问题**: 🔄 复杂度问题: 3, ⚠️ 其他问题: 3, 🏗️ 结构问题: 1, ❌ 错误处理问题: 5, 🏷️ 命名问题: 3

#### 函数详情

| 函数 | 行范围 | 行数 | 复杂度 | 嵌套 | 参数 | 注释 |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L47-236 | 190 | 32 | 7 | 6 | ✓ |
| `_find_task` | L239-246 | 8 | 5 | 2 | 2 | ✓ |
| `_sse` | L17-18 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L28-42 | 15 | 1 | 0 | 6 | ✗ |
| `get_active_session` | L44-45 | 2 | 1 | 0 | 3 | ✗ |

**全部问题 (15)**

- 🔄 `process_stream()` L47: 复杂度: 32
- 🔄 `process_stream()` L47: 认知复杂度: 46
- 🔄 `process_stream()` L47: 嵌套深度: 7
- 📏 `process_stream()` L47: 190 代码量
- 📏 `__init__()` L28: 6 参数数量
- 📏 `process_stream()` L47: 6 参数数量
- 🏗️ `process_stream()` L47: 嵌套过深: 7
- ❌ L143: 未处理的易出错调用
- ❌ L164: 未处理的易出错调用
- ❌ L174: 未处理的易出错调用
- ❌ L216: 未处理的易出错调用
- ❌ L236: 未处理的易出错调用
- 🏷️ `_sse()` L17: "_sse" - snake_case
- 🏷️ `__init__()` L28: "__init__" - snake_case
- 🏷️ `_find_task()` L239: "_find_task" - snake_case

**详情**:
- 循环复杂度: 平均: 8.0, 最大: 32
- 认知复杂度: 平均: 11.6, 最大: 46
- 嵌套深度: 平均: 1.8, 最大: 7
- 函数长度: 平均: 43.4 行, 最大: 190 行
- 文件长度: 196 代码量 (247 总计)
- 参数数量: 平均: 3.6, 最大: 6
- 代码重复: 0.0% 重复 (0/5)
- 结构分析: 1 个结构问题
- 错误处理: 5/15 个错误被忽略 (33.3%)
- 注释比例: 10.7% (21/196)
- 命名规范: 发现 3 个违规

### 10. skills/builtin/ncm_music/tools/ncm_api.py

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

## 最差函数 Top 10

| 函数 | 文件 | 复杂度 | 嵌套 | 行数 |
|:-----|:-----|------:|------:|------:|
| `main` | psychoscope/minimal.py | 112 | 9 | 391 |
| `process_stream` | plugins/pipeline.py | 77 | 9 | 379 |
| `create_application` | boot.py | 63 | 5 | 493 |
| `_cmd_login` | main.py | 42 | 2 | 152 |
| `_run_agent_loop` | plugins/pipeline.py | 41 | 4 | 207 |
| `on_hook` | plugins/builtin/models_plugin.py | 40 | 7 | 156 |
| `msgFlow` | psychoscope/static/js/app.js | 40 | 4 | 146 |
| `search` | memory/core.py | 39 | 7 | 129 |
| `_init_plugins_via_loader` | engine.py | 38 | 5 | 97 |
| `_handle_sse_stream` | psychoscope/minimal.py | 38 | 4 | 104 |

## 诊断结论 {#conclusion}

🌸 **微臭青年** - 略有异味，建议适量通风

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*