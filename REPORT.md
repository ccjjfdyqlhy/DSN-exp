# 🌸 屎山代码分析报告 🌸

> 分析时间: 2026-06-17 22:01:56
> 分析范围: app.py, engine.py, maintenance/api.py, maintenance/tracker.py, plugins/builtin/memory_plugin.py...

## 糟糕指数

![Score](https://img.shields.io/badge/Score-46.1%25-green)

| 指标 | 评分 |
|:----|:----:|
| **糟糕指数** | **46.1/100** |
| 屎山等级 | 🌿 微臭青年 |

### 📊 统计信息

| 指标 | 数值 |
|:----|:----:|
| 文件数 | 11 |
| 函数数 | 188 |
| 代码行数 | 2763 |

### 复杂度指标

| 指标 | 均值 | 最值 |
|:----|:---:|:---:|
| 循环复杂度 | 3.57 | 43 |
| 函数长度 | 17.6 行 | 233 行 |
| 参数数量 | - | 17 个 |

### 🏆 最危险函数 Top 5

  1. `"engine.py" → "create_engine_with_defaults"` — CCN=43, 长度=233行
  2. `"engine.py" → "_init_prompt"` — CCN=16, 长度=41行
  3. `"app.py" → "_synthesize_tts_lines"` — CCN=15, 长度=50行
  4. `"app.py" → "asr_passthrough"` — CCN=12, 长度=67行
  5. `"engine.py" → "_register_execution_plugins"` — CCN=11, 长度=41行


### 诊断结论

整体代码质量评级 **46.1/100**（🌿 微臭青年）。

- ✅ 循环复杂度控制良好，函数逻辑清晰
- 🔴 存在超长函数（233行），建议拆分
