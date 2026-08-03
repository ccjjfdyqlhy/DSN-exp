# 🌸 Code Quality Analysis Report 🌸

## 📑 Table of Contents

- [Issue Score](#overall-score)
- [Metrics Details](#metrics-details)
- [Problem Files Ranking](#problem-files)
- [Diagnosis](#conclusion)

![Score](https://img.shields.io/badge/Score-78%25-green)

## Issue Score {#overall-score}

| Metrics Summary | Score |
|------|-------|
| **Issue Score** | **77.56/100** |
| Quality Level | 😐 Slightly stinky youth |

> A hint of fragrance, sometimes a whiff of funk—still safe to touch

### 📊 Statistics

| Metric | Value |
|--------|-------|
| Total Files | 276 |
| Skipped | 1239 |
| Time | 1298ms |

### 📋 Project Overview

| Metric | Value |
|--------|-------|
| Total Code Lines | 50021 |
| Total Comment Lines | 2579 |
| Overall Comment Ratio | 5.2% |
| Avg File Size | 226 lines |
| Largest File | `main.py` (3200) |

#### Language Distribution

| Language | Files |
|:-----|------:|
| Python | 273 |
| JavaScript | 3 |

## Metrics Details {#metrics-details}

| Metrics Summary | Score | Min | Max | Median | Status |
|:-----|------:|------:|------:|------:|:------:|
| Cyclomatic Complexity | 10.18% | 0.0% | 80.0% | 3.0% | ✓✓ |
| Cognitive Complexity | 13.60% | 0.0% | 70.0% | 8.0% | ✓✓ |
| Nesting Depth | 4.79% | 0.0% | 75.0% | 0.0% | ✓✓ |
| Function Length | 6.29% | 0.0% | 59.5% | 0.0% | ✓✓ |
| File Length | 3.23% | 0.0% | 98.4% | 0.0% | ✓✓ |
| Parameter Count | 13.68% | 0.0% | 98.5% | 0.0% | ✓✓ |
| Code Duplication | 5.49% | 0.0% | 81.7% | 0.0% | ✓✓ |
| Structure Analysis | 5.53% | 0.0% | 87.5% | 0.0% | ✓✓ |
| Error Handling | 31.20% | 0.0% | 98.8% | 4.8% | ✓ |
| Comment Ratio | 41.66% | 0.0% | 100.0% | 35.7% | ○ |
| Naming Convention | 31.25% | 0.0% | 100.0% | 25.0% | ✓ |

## Problem Files Ranking {#problem-files}

### 1. plugins/pipeline.py

**Issue Score: 56.25**

> Stats: 1513 lines | 1233 code | 88 comments | 38 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 23, ⚠️ Other Issues: 9, 🏗️ Structure Issues: 12, ❌ Error Handling Issues: 37, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (90)**

- 🔄 `process()` L215: Complexity: 16
- 🔄 `_run_async_background()` L314: Complexity: 11
- 🔄 `_run_agent_loop()` L429: Complexity: 41
- 🔄 `_synthesize_lines_sync()` L824: Complexity: 24
- 🔄 `_poll_pending_tasks()` L967: Complexity: 38
- 🔄 `process_stream()` L1101: Complexity: 77
- 🔄 `process_tts()` L180: Cognitive Complexity: 14
- 🔄 `process()` L215: Cognitive Complexity: 22
- 🔄 `_run_async_background()` L314: Cognitive Complexity: 15
- 🔄 `_run_tool()` L359: Cognitive Complexity: 17
- 🔄 `_run_agent_loop()` L429: Cognitive Complexity: 49
- 🔄 `_print_timing()` L637: Cognitive Complexity: 17
- 🔄 `_format_tag_results()` L675: Cognitive Complexity: 14
- 🔄 `_synthesize_lines_sync()` L824: Cognitive Complexity: 28
- 🔄 `_run_all_plugins()` L937: Cognitive Complexity: 13
- 🔄 `_poll_pending_tasks()` L967: Cognitive Complexity: 50
- 🔄 `process_stream()` L1101: Cognitive Complexity: 95
- 🔄 `process_tts()` L180: Nesting Depth: 4
- 🔄 `_run_tool()` L359: Nesting Depth: 4
- 🔄 `_run_agent_loop()` L429: Nesting Depth: 4
- 🔄 `_print_timing()` L637: Nesting Depth: 4
- 🔄 `_poll_pending_tasks()` L967: Nesting Depth: 6
- 🔄 `process_stream()` L1101: Nesting Depth: 9
- 📏 `process()` L215: 94 Size
- 📏 `_run_async_background()` L314: 51 Size
- 📏 `_run_agent_loop()` L429: 207 Size
- 📏 `_synthesize_lines_sync()` L824: 102 Size
- 📏 `_poll_pending_tasks()` L967: 123 Size
- 📏 `process_stream()` L1101: 379 Size
- 📏 `__init__()` L133: 8 Parameter Count
- 📏 `_report_agent_progress()` L408: 6 Parameter Count
- 🏗️ `_extract_narrations()` L77: Medium nesting: 3
- 🏗️ `process_tts()` L180: Medium nesting: 4
- 🏗️ `process()` L215: Medium nesting: 3
- 🏗️ `_run_tool()` L359: Medium nesting: 4
- 🏗️ `_run_agent_loop()` L429: Medium nesting: 4
- 🏗️ `_print_timing()` L637: Medium nesting: 4
- 🏗️ `_format_tag_results()` L675: Medium nesting: 3
- 🏗️ `_poll_pending_tasks()` L967: High nesting: 6
- 🏗️ `process_stream()` L1101: High nesting: 9
- 🏗️ `_drain_q()` L1302: Medium nesting: 3
- 🏗️ L1: File too large: 1513 lines
- 🏗️ L1: Too many imports: 30
- ❌ L187: Unhandled error-prone call
- ❌ L209: Unhandled error-prone call
- ❌ L256: Unhandled error-prone call
- ❌ L273: Unhandled error-prone call
- ❌ L290: Unhandled error-prone call
- ❌ L321: Unhandled error-prone call
- ❌ L376: Unhandled error-prone call
- ❌ L377: Unhandled error-prone call
- ❌ L378: Unhandled error-prone call
- ❌ L399: Unhandled error-prone call
- ❌ L416: Unhandled error-prone call
- ❌ L427: Unhandled error-prone call
- ❌ L465: Unhandled error-prone call
- ❌ L487: Unhandled error-prone call
- ❌ L512: Unhandled error-prone call
- ❌ L604: Unhandled error-prone call
- ❌ L690: Unhandled error-prone call
- ❌ L850: Unhandled error-prone call
- ❌ L917: Unhandled error-prone call
- ❌ L921: Unhandled error-prone call
- ❌ L924: Unhandled error-prone call
- ❌ L935: Unhandled error-prone call
- ❌ L942: Unhandled error-prone call
- ❌ L964: Unhandled error-prone call
- ❌ L965: Unhandled error-prone call
- ❌ L999: Unhandled error-prone call
- ❌ L1024: Unhandled error-prone call
- ❌ L1061: Unhandled error-prone call
- ❌ L1155: Unhandled error-prone call
- ❌ L1172: Unhandled error-prone call
- ❌ L1293: Unhandled error-prone call
- ❌ L1413: Unhandled error-prone call
- ❌ L1427: Unhandled error-prone call
- ❌ L1444: Unhandled error-prone call
- ❌ L1464: Unhandled error-prone call
- ❌ L1504: Unhandled error-prone call
- ❌ L1506: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 8.6, Max: 77
- Cognitive Complexity: Avg: 12.5, Max: 95
- Nesting Depth: Avg: 1.9, Max: 9
- Function Length: Avg: 37.1 lines, Max: 379 lines
- File Length: 1233 code lines (1513 total)
- Parameter Count: Avg: 2.0, Max: 8
- Code Duplication: 2.6% duplication (1/38)
- Structure Analysis: 12 structure issues
- Error Handling: 37/88 errors ignored (42.0%)
- Comment Ratio: 7.1% (88/1233)
- Naming Convention: 29 violations found

### 2. psychoscope/minimal.py

**Issue Score: 52.14**

> Stats: 2344 lines | 1951 code | 88 comments | 100 functions | 7 classes

**Issues**: 🔄 Complexity Issues: 42, ⚠️ Other Issues: 9, 🏗️ Structure Issues: 24, ❌ Error Handling Issues: 37, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (120)**

- 🔄 `_enumerate_cameras()` L88: Complexity: 14
- 🔄 `raw_input()` L379: Complexity: 13
- 🔄 `_poll_loop()` L557: Complexity: 18
- 🔄 `_tts_worker()` L856: Complexity: 13
- 🔄 `authenticate()` L915: Complexity: 14
- 🔄 `_handle_sse_stream()` L1155: Complexity: 38
- 🔄 `_loop()` L1300: Complexity: 24
- 🔄 `_beat()` L1505: Complexity: 28
- 🔄 `print_cameras()` L1841: Complexity: 14
- 🔄 `main()` L1936: Complexity: 112
- 🔄 `_enumerate_cameras()` L88: Cognitive Complexity: 22
- 🔄 `_scan_devices()` L159: Cognitive Complexity: 17
- 🔄 `read_key()` L351: Cognitive Complexity: 14
- 🔄 `raw_input()` L379: Cognitive Complexity: 19
- 🔄 `play_index()` L436: Cognitive Complexity: 13
- 🔄 `_poll_loop()` L557: Cognitive Complexity: 28
- 🔄 `_play_beep()` L596: Cognitive Complexity: 14
- 🔄 `iter_sse_lines()` L766: Cognitive Complexity: 17
- 🔄 `prompt_backend_host()` L803: Cognitive Complexity: 14
- 🔄 `_tts_worker()` L856: Cognitive Complexity: 23
- 🔄 `authenticate()` L915: Cognitive Complexity: 18
- 🔄 `_handle_sse_stream()` L1155: Cognitive Complexity: 46
- 🔄 `_loop()` L1300: Cognitive Complexity: 36
- 🔄 `_loop()` L1416: Cognitive Complexity: 16
- 🔄 `_beat()` L1505: Cognitive Complexity: 36
- 🔄 `stop_and_send()` L1716: Cognitive Complexity: 14
- 🔄 `_capture_loop()` L1750: Cognitive Complexity: 15
- 🔄 `print_cameras()` L1841: Cognitive Complexity: 24
- 🔄 `print_system_info()` L1894: Cognitive Complexity: 18
- 🔄 `main()` L1936: Cognitive Complexity: 130
- 🔄 `_enumerate_cameras()` L88: Nesting Depth: 4
- 🔄 `_scan_devices()` L159: Nesting Depth: 4
- 🔄 `_poll_loop()` L557: Nesting Depth: 5
- 🔄 `iter_sse_lines()` L766: Nesting Depth: 4
- 🔄 `prompt_backend_host()` L803: Nesting Depth: 4
- 🔄 `_tts_worker()` L856: Nesting Depth: 5
- 🔄 `_handle_sse_stream()` L1155: Nesting Depth: 4
- 🔄 `_loop()` L1300: Nesting Depth: 6
- 🔄 `_beat()` L1505: Nesting Depth: 4
- 🔄 `print_cameras()` L1841: Nesting Depth: 5
- 🔄 `print_system_info()` L1894: Nesting Depth: 4
- 🔄 `main()` L1936: Nesting Depth: 9
- 📏 `_enumerate_cameras()` L88: 62 Size
- 📏 `_tts_worker()` L856: 58 Size
- 📏 `authenticate()` L915: 82 Size
- 📏 `_handle_sse_stream()` L1155: 104 Size
- 📏 `_loop()` L1300: 65 Size
- 📏 `_beat()` L1505: 98 Size
- 📏 `main()` L1936: 391 Size
- 🏗️ `_enumerate_cameras()` L88: Medium nesting: 4
- 🏗️ `_scan_devices()` L159: Medium nesting: 4
- 🏗️ `read_key()` L351: Medium nesting: 3
- 🏗️ `raw_input()` L379: Medium nesting: 3
- 🏗️ `play_index()` L436: Medium nesting: 3
- 🏗️ `_poll_loop()` L557: High nesting: 5
- 🏗️ `_play_beep()` L596: Medium nesting: 3
- 🏗️ `iter_sse_lines()` L766: Medium nesting: 4
- 🏗️ `prompt_backend_host()` L803: Medium nesting: 4
- 🏗️ `_tts_worker()` L856: High nesting: 5
- 🏗️ `_verify_api_key()` L998: Medium nesting: 3
- 🏗️ `_send_worker()` L1136: Medium nesting: 3
- 🏗️ `_handle_sse_stream()` L1155: Medium nesting: 4
- 🏗️ `_loop()` L1300: High nesting: 6
- 🏗️ `_loop()` L1416: Medium nesting: 3
- 🏗️ `_loop()` L1493: Medium nesting: 3
- 🏗️ `_beat()` L1505: Medium nesting: 4
- 🏗️ `_capture_loop()` L1750: Medium nesting: 3
- 🏗️ `print_cameras()` L1841: High nesting: 5
- 🏗️ `print_system_info()` L1894: Medium nesting: 4
- 🏗️ `main()` L1936: High nesting: 9
- 🏗️ L1: File too large: 2344 lines
- 🏗️ L1: Too many functions: 100
- 🏗️ L1: Too many imports: 35
- ❌ L144: Unhandled error-prone call
- ❌ L394: Unhandled error-prone call
- ❌ L402: Unhandled error-prone call
- ❌ L453: Unhandled error-prone call
- ❌ L454: Unhandled error-prone call
- ❌ L608: Unhandled error-prone call
- ❌ L615: Unhandled error-prone call
- ❌ L616: Unhandled error-prone call
- ❌ L638: Unhandled error-prone call
- ❌ L876: Unhandled error-prone call
- ❌ L877: Unhandled error-prone call
- ❌ L886: Unhandled error-prone call
- ❌ L1131: Unhandled error-prone call
- ❌ L1134: Unhandled error-prone call
- ❌ L1187: Unhandled error-prone call
- ❌ L1203: Unhandled error-prone call
- ❌ L1215: Unhandled error-prone call
- ❌ L1252: Unhandled error-prone call
- ❌ L1325: Unhandled error-prone call
- ❌ L1338: Unhandled error-prone call
- ❌ L1356: Unhandled error-prone call
- ❌ L1487: Unhandled error-prone call
- ❌ L1529: Unhandled error-prone call
- ❌ L1530: Unhandled error-prone call
- ❌ L1532: Unhandled error-prone call
- ❌ L1566: Unhandled error-prone call
- ❌ L1588: Unhandled error-prone call
- ❌ L1734: Unhandled error-prone call
- ❌ L1834: Unhandled error-prone call
- ❌ L1859: Unhandled error-prone call
- ❌ L1860: Unhandled error-prone call
- ❌ L1900: Unhandled error-prone call
- ❌ L1925: Unhandled error-prone call
- ❌ L1984: Unhandled error-prone call
- ❌ L2193: Unhandled error-prone call
- ❌ L2241: Unhandled error-prone call
- ❌ L2276: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 6.0, Max: 112
- Cognitive Complexity: Avg: 9.4, Max: 130
- Nesting Depth: Avg: 1.7, Max: 9
- Function Length: Avg: 20.4 lines, Max: 391 lines
- File Length: 1951 code lines (2344 total)
- Parameter Count: Avg: 1.3, Max: 5
- Code Duplication: 4.0% duplication (4/100)
- Structure Analysis: 24 structure issues
- Error Handling: 37/166 errors ignored (22.3%)
- Comment Ratio: 4.5% (88/1951)
- Naming Convention: 48 violations found

### 3. main.py

**Issue Score: 51.72**

> Stats: 3200 lines | 2630 code | 66 comments | 86 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 56, ⚠️ Other Issues: 41, 🏗️ Structure Issues: 17, ❌ Error Handling Issues: 32, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (155)**

- 🔄 `_cmd_cleanup_users()` L343: Complexity: 17
- 🔄 `_cmd_export()` L648: Complexity: 13
- 🔄 `_cmd_import()` L739: Complexity: 11
- 🔄 `_cmd_reminder()` L813: Complexity: 31
- 🔄 `_cmd_plan()` L942: Complexity: 21
- 🔄 `_cmd_login()` L1007: Complexity: 42
- 🔄 `_cmd_login_timeslot()` L1215: Complexity: 14
- 🔄 `_cmd_login_schedule()` L1266: Complexity: 16
- 🔄 `_cmd_login_dynamic()` L1312: Complexity: 12
- 🔄 `_dynamic_show()` L1365: Complexity: 16
- 🔄 `_cmd_plugin()` L1492: Complexity: 11
- 🔄 `_cmd_memory()` L1548: Complexity: 12
- 🔄 `_cmd_memory_query()` L1629: Complexity: 31
- 🔄 `_cmd_memory_rebuild()` L1762: Complexity: 21
- 🔄 `_cmd_memory_list()` L1984: Complexity: 17
- 🔄 `_cmd_persona()` L2275: Complexity: 11
- 🔄 `_persona_status()` L2317: Complexity: 13
- 🔄 `_cmd_agent()` L2408: Complexity: 34
- 🔄 `_cmd_hibernate_check()` L2741: Complexity: 19
- 🔄 `_cmd_hibernate_task()` L2915: Complexity: 20
- 🔄 `main()` L3000: Complexity: 31
- 🔄 `_is_env_configured()` L31: Cognitive Complexity: 17
- 🔄 `_check_port_available()` L153: Cognitive Complexity: 20
- 🔄 `_env_write()` L210: Cognitive Complexity: 20
- 🔄 `_cmd_cleanup_users()` L343: Cognitive Complexity: 23
- 🔄 `_cmd_users()` L414: Cognitive Complexity: 13
- 🔄 `_cmd_status()` L455: Cognitive Complexity: 13
- 🔄 `_cmd_export()` L648: Cognitive Complexity: 17
- 🔄 `_cmd_import()` L739: Cognitive Complexity: 15
- 🔄 `_cmd_reminder()` L813: Cognitive Complexity: 39
- 🔄 `_cmd_plan()` L942: Cognitive Complexity: 25
- 🔄 `_cmd_login()` L1007: Cognitive Complexity: 46
- 🔄 `_login_list()` L1161: Cognitive Complexity: 16
- 🔄 `_cmd_login_timeslot()` L1215: Cognitive Complexity: 18
- 🔄 `_cmd_login_schedule()` L1266: Cognitive Complexity: 20
- 🔄 `_cmd_login_dynamic()` L1312: Cognitive Complexity: 16
- 🔄 `_dynamic_show()` L1365: Cognitive Complexity: 20
- 🔄 `_cmd_plugin()` L1492: Cognitive Complexity: 15
- 🔄 `_cmd_memory()` L1548: Cognitive Complexity: 16
- 🔄 `_cmd_memory_query()` L1629: Cognitive Complexity: 37
- 🔄 `_cmd_memory_rebuild()` L1762: Cognitive Complexity: 27
- 🔄 `_cmd_memory_list()` L1984: Cognitive Complexity: 21
- 🔄 `_cmd_detail()` L2117: Cognitive Complexity: 13
- 🔄 `_cmd_persona()` L2275: Cognitive Complexity: 15
- 🔄 `_persona_status()` L2317: Cognitive Complexity: 21
- 🔄 `_cmd_agent()` L2408: Cognitive Complexity: 40
- 🔄 `_persona_materials()` L2596: Cognitive Complexity: 14
- 🔄 `_cmd_hibernate_check()` L2741: Cognitive Complexity: 25
- 🔄 `_cmd_hibernate_task()` L2915: Cognitive Complexity: 28
- 🔄 `main()` L3000: Cognitive Complexity: 37
- 🔄 `_is_env_configured()` L31: Nesting Depth: 4
- 🔄 `_check_port_available()` L153: Nesting Depth: 5
- 🔄 `_env_write()` L210: Nesting Depth: 5
- 🔄 `_cmd_reminder()` L813: Nesting Depth: 4
- 🔄 `_persona_status()` L2317: Nesting Depth: 4
- 🔄 `_cmd_hibernate_task()` L2915: Nesting Depth: 4
- 📏 `_check_port_available()` L153: 55 Size
- 📏 `_cmd_cleanup_users()` L343: 69 Size
- 📏 `_cmd_export()` L648: 89 Size
- 📏 `_cmd_import()` L739: 72 Size
- 📏 `_cmd_reminder()` L813: 127 Size
- 📏 `_cmd_plan()` L942: 63 Size
- 📏 `_cmd_login()` L1007: 152 Size
- 📏 `_cmd_login_dynamic()` L1312: 51 Size
- 📏 `_dynamic_show()` L1365: 70 Size
- 📏 `_cmd_help()` L1437: 53 Size
- 📏 `_cmd_plugin()` L1492: 54 Size
- 📏 `_cmd_memory_query()` L1629: 131 Size
- 📏 `_cmd_memory_rebuild()` L1762: 116 Size
- 📏 `_cmd_memory_list()` L1984: 84 Size
- 📏 `_persona_status()` L2317: 62 Size
- 📏 `_cmd_agent()` L2408: 145 Size
- 📏 `_cmd_hibernate()` L2685: 54 Size
- 📏 `_cmd_hibernate_check()` L2741: 90 Size
- 📏 `_cmd_hibernate_task()` L2915: 71 Size
- 📏 `main()` L3000: 182 Size
- 📏 `_execute_command()` L2149: 9 Parameter Count
- 📏 `_h_newbind()` L2184: 7 Parameter Count
- 📏 `_h_cleanup_users()` L2187: 7 Parameter Count
- 📏 `_h_users()` L2190: 7 Parameter Count
- 📏 `_h_status()` L2193: 7 Parameter Count
- 📏 `_h_plugin()` L2196: 7 Parameter Count
- 📏 `_h_memory()` L2199: 7 Parameter Count
- 📏 `_h_prompt()` L2202: 7 Parameter Count
- 📏 `_h_config()` L2205: 7 Parameter Count
- 📏 `_h_listconfig()` L2208: 7 Parameter Count
- 📏 `_h_persona()` L2211: 7 Parameter Count
- 📏 `_h_help()` L2214: 7 Parameter Count
- 📏 `_h_login()` L2217: 7 Parameter Count
- 📏 `_h_agent()` L2220: 7 Parameter Count
- 📏 `_h_export()` L2224: 7 Parameter Count
- 📏 `_h_import()` L2228: 7 Parameter Count
- 📏 `_h_reminder()` L2232: 7 Parameter Count
- 📏 `_h_plan()` L2236: 7 Parameter Count
- 📏 `_h_detail()` L2240: 7 Parameter Count
- 📏 `_h_timer()` L2244: 7 Parameter Count
- 🏗️ `_is_env_configured()` L31: Medium nesting: 4
- 🏗️ `_env_backup_rotate()` L100: Medium nesting: 3
- 🏗️ `_check_port_available()` L153: High nesting: 5
- 🏗️ `_env_write()` L210: High nesting: 5
- 🏗️ `_cmd_cleanup_users()` L343: Medium nesting: 3
- 🏗️ `_cmd_reminder()` L813: Medium nesting: 4
- 🏗️ `_login_list()` L1161: Medium nesting: 3
- 🏗️ `_cmd_memory_query()` L1629: Medium nesting: 3
- 🏗️ `_cmd_memory_rebuild()` L1762: Medium nesting: 3
- 🏗️ `_persona_status()` L2317: Medium nesting: 4
- 🏗️ `_cmd_agent()` L2408: Medium nesting: 3
- 🏗️ `_cmd_hibernate_check()` L2741: Medium nesting: 3
- 🏗️ `_cmd_hibernate_task()` L2915: Medium nesting: 4
- 🏗️ `main()` L3000: Medium nesting: 3
- 🏗️ L1: File too large: 3200 lines
- 🏗️ L1: Too many functions: 86
- 🏗️ L1: Too many imports: 47
- ❌ L166: Unhandled error-prone call
- ❌ L410: Unhandled error-prone call
- ❌ L440: Unhandled error-prone call
- ❌ L448: Unhandled error-prone call
- ❌ L781: Unhandled error-prone call
- ❌ L787: Unhandled error-prone call
- ❌ L801: Unhandled error-prone call
- ❌ L807: Unhandled error-prone call
- ❌ L1181: Unhandled error-prone call
- ❌ L1182: Unhandled error-prone call
- ❌ L1193: Unhandled error-prone call
- ❌ L1196: Unhandled error-prone call
- ❌ L1197: Unhandled error-prone call
- ❌ L1237: Unhandled error-prone call
- ❌ L1238: Unhandled error-prone call
- ❌ L1285: Unhandled error-prone call
- ❌ L1286: Unhandled error-prone call
- ❌ L1323: Unhandled error-prone call
- ❌ L1340: Unhandled error-prone call
- ❌ L1373: Unhandled error-prone call
- ❌ L1389: Unhandled error-prone call
- ❌ L1390: Unhandled error-prone call
- ❌ L1412: Unhandled error-prone call
- ❌ L1540: Unhandled error-prone call
- ❌ L1933: Unhandled error-prone call
- ❌ L1934: Unhandled error-prone call
- ❌ L2064: Unhandled error-prone call
- ❌ L2364: Unhandled error-prone call
- ❌ L2551: Unhandled error-prone call
- ❌ L2584: Unhandled error-prone call
- ❌ L2585: Unhandled error-prone call
- ❌ L2586: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 7.8, Max: 42
- Cognitive Complexity: Avg: 10.8, Max: 46
- Nesting Depth: Avg: 1.5, Max: 5
- Function Length: Avg: 33.9 lines, Max: 182 lines
- File Length: 2630 code lines (3200 total)
- Parameter Count: Avg: 2.7, Max: 9
- Code Duplication: 1.2% duplication (1/86)
- Structure Analysis: 17 structure issues
- Error Handling: 32/106 errors ignored (30.2%)
- Comment Ratio: 2.5% (66/2630)
- Naming Convention: 83 violations found

### 4. plugins/builtin/models_plugin.py

**Issue Score: 45.73**

> Stats: 451 lines | 391 code | 14 comments | 11 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 7, ⚠️ Other Issues: 4, 🏗️ Structure Issues: 4, ❌ Error Handling Issues: 3, 📝 Comment Issues: 1, 🏷️ Naming Issues: 6

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (23)**

- 🔄 `on_hook()` L61: Complexity: 40
- 🔄 `invoke()` L361: Complexity: 23
- 🔄 `on_hook()` L61: Cognitive Complexity: 54
- 🔄 `_build_tools_schema()` L218: Cognitive Complexity: 16
- 🔄 `invoke()` L361: Cognitive Complexity: 35
- 🔄 `on_hook()` L61: Nesting Depth: 7
- 🔄 `invoke()` L361: Nesting Depth: 6
- 📏 `on_hook()` L61: 156 Size
- 📏 `invoke()` L361: 78 Size
- 📏 `__init__()` L23: 12 Parameter Count
- 🏗️ `on_hook()` L61: High nesting: 7
- 🏗️ `_build_tools_schema()` L218: Medium nesting: 3
- 🏗️ `_build_full_schema()` L289: Medium nesting: 3
- 🏗️ `invoke()` L361: High nesting: 6
- ❌ L182: Unhandled error-prone call
- ❌ L203: Unhandled error-prone call
- ❌ L243: Unhandled error-prone call
- 🏷️ `__init__()` L23: "__init__" - snake_case
- 🏷️ `_build_tools_schema()` L218: "_build_tools_schema" - snake_case
- 🏷️ `_build_toolbox_schema()` L248: "_build_toolbox_schema" - snake_case
- 🏷️ `_build_full_schema()` L289: "_build_full_schema" - snake_case
- 🏷️ `_create_chat()` L306: "_create_chat" - snake_case
- 🏷️ `_clean_reply()` L338: "_clean_reply" - snake_case

**Metric Details**:
- Cyclomatic Complexity: Avg: 8.9, Max: 40
- Cognitive Complexity: Avg: 13.1, Max: 54
- Nesting Depth: Avg: 2.1, Max: 7
- Function Length: Avg: 37.9 lines, Max: 156 lines
- File Length: 391 code lines (451 total)
- Parameter Count: Avg: 3.0, Max: 12
- Code Duplication: 0.0% duplication (0/11)
- Structure Analysis: 4 structure issues
- Error Handling: 3/22 errors ignored (13.6%)
- Comment Ratio: 3.6% (14/391)
- Naming Convention: 6 violations found

### 5. engine.py

**Issue Score: 45.21**

> Stats: 1337 lines | 1076 code | 53 comments | 42 functions | 2 classes

**Issues**: 🔄 Complexity Issues: 16, ⚠️ Other Issues: 11, 🏗️ Structure Issues: 11, ❌ Error Handling Issues: 11, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (58)**

- 🔄 `_init_prompt()` L572: Complexity: 17
- 🔄 `_init_plugins_via_loader()` L628: Complexity: 38
- 🔄 `build_context()` L739: Complexity: 13
- 🔄 `chat_debug_respond()` L906: Complexity: 11
- 🔄 `create_engine_with_defaults()` L1134: Complexity: 36
- 🔄 `_generate_result_message()` L315: Cognitive Complexity: 13
- 🔄 `_inject_system_skill_deps()` L520: Cognitive Complexity: 14
- 🔄 `_init_prompt()` L572: Cognitive Complexity: 25
- 🔄 `_init_plugins_via_loader()` L628: Cognitive Complexity: 48
- 🔄 `build_context()` L739: Cognitive Complexity: 15
- 🔄 `chat()` L817: Cognitive Complexity: 13
- 🔄 `chat_debug_respond()` L906: Cognitive Complexity: 15
- 🔄 `create_engine_with_defaults()` L1134: Cognitive Complexity: 46
- 🔄 `_init_prompt()` L572: Nesting Depth: 4
- 🔄 `_init_plugins_via_loader()` L628: Nesting Depth: 5
- 🔄 `create_engine_with_defaults()` L1134: Nesting Depth: 5
- 📏 `_generate_result_message()` L315: 57 Size
- 📏 `_init_prompt()` L572: 52 Size
- 📏 `_init_plugins_via_loader()` L628: 97 Size
- 📏 `chat_debug_respond()` L906: 74 Size
- 📏 `create_engine_with_defaults()` L1134: 203 Size
- 📏 `build_context()` L739: 8 Parameter Count
- 📏 `chat()` L817: 8 Parameter Count
- 📏 `chat_stream()` L856: 8 Parameter Count
- 📏 `chat_debug()` L880: 6 Parameter Count
- 📏 `create_engine_with_defaults()` L1134: 12 Parameter Count
- 🏗️ `_get_event_loop()` L44: Medium nesting: 3
- 🏗️ `_process_task_completion()` L217: Medium nesting: 3
- 🏗️ `_init_memory()` L400: Medium nesting: 3
- 🏗️ `_inject_system_skill_deps()` L520: Medium nesting: 3
- 🏗️ `_inject_v3_to_exa_evolution()` L554: Medium nesting: 3
- 🏗️ `_init_prompt()` L572: Medium nesting: 4
- 🏗️ `_init_plugins_via_loader()` L628: High nesting: 5
- 🏗️ `_dump_context_for_session()` L985: Medium nesting: 3
- 🏗️ `create_engine_with_defaults()` L1134: High nesting: 5
- 🏗️ L1: File too large: 1337 lines
- 🏗️ L1: Too many imports: 63
- ❌ L241: Unhandled error-prone call
- ❌ L254: Unhandled error-prone call
- ❌ L268: Unhandled error-prone call
- ❌ L331: Unhandled error-prone call
- ❌ L790: Unhandled error-prone call
- ❌ L791: Unhandled error-prone call
- ❌ L792: Unhandled error-prone call
- ❌ L793: Unhandled error-prone call
- ❌ L794: Unhandled error-prone call
- ❌ L811: Unhandled error-prone call
- ❌ L1067: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 6.5, Max: 38
- Cognitive Complexity: Avg: 9.7, Max: 48
- Nesting Depth: Avg: 1.6, Max: 5
- Function Length: Avg: 28.5 lines, Max: 203 lines
- File Length: 1076 code lines (1337 total)
- Parameter Count: Avg: 2.5, Max: 12
- Code Duplication: 4.8% duplication (2/42)
- Structure Analysis: 11 structure issues
- Error Handling: 11/48 errors ignored (22.9%)
- Comment Ratio: 4.9% (53/1076)
- Naming Convention: 26 violations found

### 6. memory/core.py

**Issue Score: 43.65**

> Stats: 924 lines | 702 code | 66 comments | 28 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 18, ⚠️ Other Issues: 10, 📋 Duplication Issues: 2, 🏗️ Structure Issues: 6, ❌ Error Handling Issues: 16, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (61)**

- 🔄 `assemble_context()` L243: Complexity: 14
- 🔄 `search()` L299: Complexity: 39
- 🔄 `reindex_embeddings()` L438: Complexity: 17
- 🔄 `_format_search_results()` L833: Complexity: 11
- 🔄 `_format_detail_results()` L869: Complexity: 16
- 🔄 `assemble_context()` L243: Cognitive Complexity: 20
- 🔄 `search()` L299: Cognitive Complexity: 53
- 🔄 `reindex_embeddings()` L438: Cognitive Complexity: 25
- 🔄 `rebuild_summaries()` L536: Cognitive Complexity: 14
- 🔄 `handle_tags()` L651: Cognitive Complexity: 13
- 🔄 `_handle_recall()` L680: Cognitive Complexity: 15
- 🔄 `_inject_unsynced_agent_chat()` L762: Cognitive Complexity: 14
- 🔄 `_format_timedelta()` L805: Cognitive Complexity: 13
- 🔄 `_format_search_results()` L833: Cognitive Complexity: 15
- 🔄 `_format_detail_results()` L869: Cognitive Complexity: 24
- 🔄 `search()` L299: Nesting Depth: 7
- 🔄 `reindex_embeddings()` L438: Nesting Depth: 4
- 🔄 `_format_detail_results()` L869: Nesting Depth: 4
- 📏 `assemble_context()` L243: 51 Size
- 📏 `search()` L299: 129 Size
- 📏 `reindex_embeddings()` L438: 93 Size
- 📏 `rebuild_summaries()` L536: 66 Size
- 📏 `_format_detail_results()` L869: 55 Size
- 📏 `summarize_turn()` L101: 7 Parameter Count
- 📏 `_do_summarize()` L128: 6 Parameter Count
- 📏 `_embed_raw_round()` L192: 6 Parameter Count
- 📏 `search()` L299: 7 Parameter Count
- 📋 `_get_exp_memories()` L167: Duplicate pattern: _get_exp_memories, _get_memos
- 📋 `add_memo()` L720: Duplicate pattern: add_memo, delete_memo
- 🏗️ `assemble_context()` L243: Medium nesting: 3
- 🏗️ `search()` L299: High nesting: 7
- 🏗️ `reindex_embeddings()` L438: Medium nesting: 4
- 🏗️ `rebuild_summaries()` L536: Medium nesting: 3
- 🏗️ `_handle_recall()` L680: Medium nesting: 3
- 🏗️ `_format_detail_results()` L869: Medium nesting: 4
- ❌ L47: Unhandled error-prone call
- ❌ L58: Unhandled error-prone call
- ❌ L62: Unhandled error-prone call
- ❌ L73: Unhandled error-prone call
- ❌ L77: Unhandled error-prone call
- ❌ L153: Unhandled error-prone call
- ❌ L203: Unhandled error-prone call
- ❌ L208: Unhandled error-prone call
- ❌ L517: Unhandled error-prone call
- ❌ L522: Unhandled error-prone call
- ❌ L583: Unhandled error-prone call
- ❌ L587: Unhandled error-prone call
- ❌ L729: Unhandled error-prone call
- ❌ L780: Unhandled error-prone call
- ❌ L797: Unhandled error-prone call
- ❌ L886: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 6.8, Max: 39
- Cognitive Complexity: Avg: 10.1, Max: 53
- Nesting Depth: Avg: 1.6, Max: 7
- Function Length: Avg: 29.1 lines, Max: 129 lines
- File Length: 702 code lines (924 total)
- Parameter Count: Avg: 3.3, Max: 7
- Code Duplication: 7.1% duplication (2/28)
- Structure Analysis: 6 structure issues
- Error Handling: 16/38 errors ignored (42.1%)
- Comment Ratio: 9.4% (66/702)
- Naming Convention: 19 violations found

### 7. models/clients.py

**Issue Score: 39.96**

> Stats: 1365 lines | 1080 code | 41 comments | 60 functions | 6 classes

**Issues**: 🔄 Complexity Issues: 18, ⚠️ Other Issues: 13, 🏗️ Structure Issues: 8, ❌ Error Handling Issues: 4, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (52)**

- 🔄 `_call_and_append()` L204: Complexity: 24
- 🔄 `_call_embed_api()` L719: Complexity: 11
- 🔄 `_call_llm()` L847: Complexity: 17
- 🔄 `_do_request()` L869: Complexity: 15
- 🔄 `_ocr_single()` L1104: Complexity: 13
- 🔄 `ask()` L1217: Complexity: 13
- 🔄 `_call_and_append()` L204: Cognitive Complexity: 30
- 🔄 `_do_call_chat_api()` L432: Cognitive Complexity: 14
- 🔄 `describe_images()` L573: Cognitive Complexity: 13
- 🔄 `_call_embed_api()` L719: Cognitive Complexity: 21
- 🔄 `_call_llm()` L847: Cognitive Complexity: 27
- 🔄 `_do_request()` L869: Cognitive Complexity: 21
- 🔄 `_ocr_single()` L1104: Cognitive Complexity: 23
- 🔄 `ask()` L1217: Cognitive Complexity: 15
- 🔄 `_do_call_chat_api()` L432: Nesting Depth: 4
- 🔄 `_call_embed_api()` L719: Nesting Depth: 5
- 🔄 `_call_llm()` L847: Nesting Depth: 5
- 🔄 `_ocr_single()` L1104: Nesting Depth: 5
- 📏 `_call_and_append()` L204: 106 Size
- 📏 `__init__()` L364: 51 Size
- 📏 `_call_llm()` L847: 60 Size
- 📏 `_do_request()` L869: 55 Size
- 📏 `_ocr_single()` L1104: 57 Size
- 📏 `ask()` L1217: 65 Size
- 📏 `__init__()` L123: 11 Parameter Count
- 📏 `__init__()` L364: 8 Parameter Count
- 📏 `__init__()` L682: 6 Parameter Count
- 📏 `__init__()` L806: 8 Parameter Count
- 📏 `_call_llm()` L847: 7 Parameter Count
- 📏 `ask()` L1217: 6 Parameter Count
- 🏗️ `_call_and_append()` L204: Medium nesting: 3
- 🏗️ `_do_call_chat_api()` L432: Medium nesting: 4
- 🏗️ `_call_embed_api()` L719: High nesting: 5
- 🏗️ `_call_llm()` L847: High nesting: 5
- 🏗️ `_do_request()` L869: Medium nesting: 3
- 🏗️ `_ocr_single()` L1104: High nesting: 5
- 🏗️ L1: File too large: 1365 lines
- 🏗️ L1: Too many functions: 60
- ❌ L73: Unhandled error-prone call
- ❌ L193: Unhandled error-prone call
- ❌ L267: Unhandled error-prone call
- ❌ L270: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 4.4, Max: 24
- Cognitive Complexity: Avg: 6.4, Max: 30
- Nesting Depth: Avg: 1.0, Max: 5
- Function Length: Avg: 20.0 lines, Max: 106 lines
- File Length: 1080 code lines (1365 total)
- Parameter Count: Avg: 2.7, Max: 11
- Code Duplication: 5.0% duplication (3/60)
- Structure Analysis: 8 structure issues
- Error Handling: 4/31 errors ignored (12.9%)
- Comment Ratio: 3.8% (41/1080)
- Naming Convention: 29 violations found

### 8. boot.py

**Issue Score: 39.84**

> Stats: 882 lines | 740 code | 47 comments | 14 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 10, ⚠️ Other Issues: 3, 📋 Duplication Issues: 2, 🏗️ Structure Issues: 4, ❌ Error Handling Issues: 8, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (36)**

- 🔄 `_synthesize_tts_lines()` L141: Complexity: 11
- 🔄 `process_task_completion()` L206: Complexity: 15
- 🔄 `_preload_models()` L292: Complexity: 13
- 🔄 `create_application()` L389: Complexity: 63
- 🔄 `_synthesize_tts_lines()` L141: Cognitive Complexity: 15
- 🔄 `process_task_completion()` L206: Cognitive Complexity: 23
- 🔄 `_preload_models()` L292: Cognitive Complexity: 17
- 🔄 `create_application()` L389: Cognitive Complexity: 73
- 🔄 `process_task_completion()` L206: Nesting Depth: 4
- 🔄 `create_application()` L389: Nesting Depth: 5
- 📏 `_preload_models()` L292: 72 Size
- 📏 `create_application()` L389: 493 Size
- 📋 `_save_debug_audio()` L112: Duplicate pattern: _save_debug_audio, _handle_reasoner_completion
- 📋 `process_task_completion()` L206: Duplicate pattern: process_task_completion, _handle_reminder_completion
- 🏗️ `create_chat_client()` L66: Medium nesting: 3
- 🏗️ `process_task_completion()` L206: Medium nesting: 4
- 🏗️ `create_application()` L389: High nesting: 5
- 🏗️ L1: Too many imports: 65
- ❌ L117: Unhandled error-prone call
- ❌ L118: Unhandled error-prone call
- ❌ L160: Unhandled error-prone call
- ❌ L218: Unhandled error-prone call
- ❌ L219: Unhandled error-prone call
- ❌ L519: Unhandled error-prone call
- ❌ L526: Unhandled error-prone call
- ❌ L802: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 9.9, Max: 63
- Cognitive Complexity: Avg: 13.6, Max: 73
- Nesting Depth: Avg: 1.9, Max: 5
- Function Length: Avg: 55.8 lines, Max: 493 lines
- File Length: 740 code lines (882 total)
- Parameter Count: Avg: 1.4, Max: 3
- Code Duplication: 14.3% duplication (2/14)
- Structure Analysis: 4 structure issues
- Error Handling: 8/38 errors ignored (21.1%)
- Comment Ratio: 6.4% (47/740)
- Naming Convention: 10 violations found

### 9. dual/coordinator.py

**Issue Score: 38.58**

> Stats: 247 lines | 196 code | 21 comments | 5 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 3, ⚠️ Other Issues: 3, 🏗️ Structure Issues: 1, ❌ Error Handling Issues: 5, 🏷️ Naming Issues: 3

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
|:-----|------:|------:|------:|------:|------:|:------:|
| `process_stream` | L47-236 | 190 | 32 | 7 | 6 | ✓ |
| `_find_task` | L239-246 | 8 | 5 | 2 | 2 | ✓ |
| `_sse` | L17-18 | 2 | 1 | 0 | 1 | ✗ |
| `__init__` | L28-42 | 15 | 1 | 0 | 6 | ✗ |
| `get_active_session` | L44-45 | 2 | 1 | 0 | 3 | ✗ |

**All Issues (15)**

- 🔄 `process_stream()` L47: Complexity: 32
- 🔄 `process_stream()` L47: Cognitive Complexity: 46
- 🔄 `process_stream()` L47: Nesting Depth: 7
- 📏 `process_stream()` L47: 190 Size
- 📏 `__init__()` L28: 6 Parameter Count
- 📏 `process_stream()` L47: 6 Parameter Count
- 🏗️ `process_stream()` L47: High nesting: 7
- ❌ L143: Unhandled error-prone call
- ❌ L164: Unhandled error-prone call
- ❌ L174: Unhandled error-prone call
- ❌ L216: Unhandled error-prone call
- ❌ L236: Unhandled error-prone call
- 🏷️ `_sse()` L17: "_sse" - snake_case
- 🏷️ `__init__()` L28: "__init__" - snake_case
- 🏷️ `_find_task()` L239: "_find_task" - snake_case

**Metric Details**:
- Cyclomatic Complexity: Avg: 8.0, Max: 32
- Cognitive Complexity: Avg: 11.6, Max: 46
- Nesting Depth: Avg: 1.8, Max: 7
- Function Length: Avg: 43.4 lines, Max: 190 lines
- File Length: 196 code lines (247 total)
- Parameter Count: Avg: 3.6, Max: 6
- Code Duplication: 0.0% duplication (0/5)
- Structure Analysis: 1 structure issues
- Error Handling: 5/15 errors ignored (33.3%)
- Comment Ratio: 10.7% (21/196)
- Naming Convention: 3 violations found

### 10. skills/builtin/ncm_music/tools/ncm_api.py

**Issue Score: 38.03**

> Stats: 1234 lines | 1010 code | 50 comments | 51 functions | 1 classes

**Issues**: 🔄 Complexity Issues: 15, ⚠️ Other Issues: 8, 📋 Duplication Issues: 4, 🏗️ Structure Issues: 9, ❌ Error Handling Issues: 93, 📝 Comment Issues: 1, 🏷️ Naming Issues: 10

#### Function Details

| Function | Lines | Count | Complexity | Nesting | Params | Doc |
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

**All Issues (138)**

- 🔄 `_try_restore_session()` L77: Complexity: 12
- 🔄 `search_song()` L193: Complexity: 11
- 🔄 `get_song_url()` L251: Complexity: 14
- 🔄 `search()` L433: Complexity: 23
- 🔄 `_fetch_song_url()` L1052: Complexity: 12
- 🔄 `_try_restore_session()` L77: Cognitive Complexity: 20
- 🔄 `search_song()` L193: Cognitive Complexity: 19
- 🔄 `get_song_url()` L251: Cognitive Complexity: 18
- 🔄 `music_control()` L365: Cognitive Complexity: 16
- 🔄 `list_downloaded()` L394: Cognitive Complexity: 15
- 🔄 `search()` L433: Cognitive Complexity: 27
- 🔄 `_fetch_song_url()` L1052: Cognitive Complexity: 16
- 🔄 `_try_restore_session()` L77: Nesting Depth: 4
- 🔄 `search_song()` L193: Nesting Depth: 4
- 🔄 `music_control()` L365: Nesting Depth: 4
- 📏 `search_song()` L193: 57 Size
- 📏 `get_song_url()` L251: 62 Size
- 📏 `search()` L433: 69 Size
- 📏 `_fetch_song_url()` L1052: 56 Size
- 📏 `search_song()` L193: 7 Parameter Count
- 📏 `get_song_url()` L251: 7 Parameter Count
- 📏 `_download_song_file()` L1135: 6 Parameter Count
- 📋 `get_artist()` L525: Duplicate pattern: get_artist, get_playlist, get_daily_recommend
- 📋 `get_artist_albums()` L544: Duplicate pattern: get_artist_albums, get_artist_tracks, get_playlist_tracks, create_playlist, get_personal_fm
- 📋 `add_to_playlist()` L655: Duplicate pattern: add_to_playlist, remove_from_playlist
- 📋 `get_user_playlists()` L696: Duplicate pattern: get_user_playlists, get_user_detail
- 🏗️ `_try_restore_session()` L77: Medium nesting: 4
- 🏗️ `_login_by_cookie()` L112: Medium nesting: 3
- 🏗️ `search_song()` L193: Medium nesting: 4
- 🏗️ `music_control()` L365: Medium nesting: 4
- 🏗️ `list_downloaded()` L394: Medium nesting: 3
- 🏗️ `login_logout()` L905: Medium nesting: 3
- 🏗️ L1: File too large: 1234 lines
- 🏗️ L1: Too many functions: 51
- 🏗️ L1: Too many imports: 43
- ❌ L234: Unhandled error-prone call
- ❌ L238: Unhandled error-prone call
- ❌ L239: Unhandled error-prone call
- ❌ L240: Unhandled error-prone call
- ❌ L246: Unhandled error-prone call
- ❌ L286: Unhandled error-prone call
- ❌ L304: Unhandled error-prone call
- ❌ L306: Unhandled error-prone call
- ❌ L311: Unhandled error-prone call
- ❌ L387: Unhandled error-prone call
- ❌ L406: Unhandled error-prone call
- ❌ L407: Unhandled error-prone call
- ❌ L467: Unhandled error-prone call
- ❌ L470: Unhandled error-prone call
- ❌ L473: Unhandled error-prone call
- ❌ L476: Unhandled error-prone call
- ❌ L479: Unhandled error-prone call
- ❌ L482: Unhandled error-prone call
- ❌ L485: Unhandled error-prone call
- ❌ L488: Unhandled error-prone call
- ❌ L491: Unhandled error-prone call
- ❌ L492: Unhandled error-prone call
- ❌ L500: Unhandled error-prone call
- ❌ L652: Unhandled error-prone call
- ❌ L794: Unhandled error-prone call
- ❌ L796: Unhandled error-prone call
- ❌ L797: Unhandled error-prone call
- ❌ L798: Unhandled error-prone call
- ❌ L799: Unhandled error-prone call
- ❌ L800: Unhandled error-prone call
- ❌ L801: Unhandled error-prone call
- ❌ L806: Unhandled error-prone call
- ❌ L808: Unhandled error-prone call
- ❌ L809: Unhandled error-prone call
- ❌ L810: Unhandled error-prone call
- ❌ L811: Unhandled error-prone call
- ❌ L812: Unhandled error-prone call
- ❌ L882: Unhandled error-prone call
- ❌ L933: Unhandled error-prone call
- ❌ L934: Unhandled error-prone call
- ❌ L935: Unhandled error-prone call
- ❌ L936: Unhandled error-prone call
- ❌ L937: Unhandled error-prone call
- ❌ L938: Unhandled error-prone call
- ❌ L947: Unhandled error-prone call
- ❌ L948: Unhandled error-prone call
- ❌ L949: Unhandled error-prone call
- ❌ L950: Unhandled error-prone call
- ❌ L951: Unhandled error-prone call
- ❌ L952: Unhandled error-prone call
- ❌ L953: Unhandled error-prone call
- ❌ L954: Unhandled error-prone call
- ❌ L963: Unhandled error-prone call
- ❌ L964: Unhandled error-prone call
- ❌ L965: Unhandled error-prone call
- ❌ L966: Unhandled error-prone call
- ❌ L967: Unhandled error-prone call
- ❌ L968: Unhandled error-prone call
- ❌ L969: Unhandled error-prone call
- ❌ L970: Unhandled error-prone call
- ❌ L979: Unhandled error-prone call
- ❌ L980: Unhandled error-prone call
- ❌ L981: Unhandled error-prone call
- ❌ L982: Unhandled error-prone call
- ❌ L983: Unhandled error-prone call
- ❌ L984: Unhandled error-prone call
- ❌ L993: Unhandled error-prone call
- ❌ L994: Unhandled error-prone call
- ❌ L995: Unhandled error-prone call
- ❌ L996: Unhandled error-prone call
- ❌ L997: Unhandled error-prone call
- ❌ L998: Unhandled error-prone call
- ❌ L999: Unhandled error-prone call
- ❌ L1008: Unhandled error-prone call
- ❌ L1009: Unhandled error-prone call
- ❌ L1010: Unhandled error-prone call
- ❌ L1011: Unhandled error-prone call
- ❌ L1012: Unhandled error-prone call
- ❌ L1021: Unhandled error-prone call
- ❌ L1022: Unhandled error-prone call
- ❌ L1023: Unhandled error-prone call
- ❌ L1024: Unhandled error-prone call
- ❌ L1025: Unhandled error-prone call
- ❌ L1026: Unhandled error-prone call
- ❌ L1088: Unhandled error-prone call
- ❌ L1090: Unhandled error-prone call
- ❌ L1091: Unhandled error-prone call
- ❌ L1092: Unhandled error-prone call
- ❌ L1122: Unhandled error-prone call
- ❌ L1123: Unhandled error-prone call
- ❌ L1125: Unhandled error-prone call
- ❌ L1128: Unhandled error-prone call
- ❌ L1148: Unhandled error-prone call
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

**Metric Details**:
- Cyclomatic Complexity: Avg: 4.8, Max: 23
- Cognitive Complexity: Avg: 7.3, Max: 27
- Nesting Depth: Avg: 1.2, Max: 4
- Function Length: Avg: 21.5 lines, Max: 69 lines
- File Length: 1010 code lines (1234 total)
- Parameter Count: Avg: 2.7, Max: 7
- Code Duplication: 15.7% duplication (8/51)
- Structure Analysis: 9 structure issues
- Error Handling: 93/193 errors ignored (48.2%)
- Comment Ratio: 5.0% (50/1010)
- Naming Convention: 24 violations found

## Top 10 Worst Functions

| Function | File | Complexity | Nesting | Count |
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

## Diagnosis {#conclusion}

🌸 **Slightly stinky youth** - A faint whiff, open a window and hope for the best

👍 Keep going, you're the clean freak of the coding world, a true code hygiene champion

---

*Generated by [fuck-u-code](https://github.com/Done-0/fuck-u-code)*