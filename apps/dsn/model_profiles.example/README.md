# 模型描述模板（示例目录）

这个目录里的 YAML **默认不生效**，只是模板与参考。
生效目录是同级的 `../model_profiles/`。

`apps/dsn_ui` 启动时会扫描生效目录下的 `*.yaml`，把每个文件注册成一个模型。

## 怎么用

1. 复制一份到生效目录：

   ```bash
   cp apps/dsn/model_profiles.example/<模板>.yaml apps/dsn/model_profiles/
   ```

2. 把里面的 `/path/to/...` 换成你机器上的真实路径。
3. 重启 `dsn_ui`，模型就会出现在「模型」页签里。

不想动文件的话，直接用 Web 控制台的「接入新实例」向导 ——
它会扫描本机 GGUF 并自动写出一份 profile。

## 模板

| 文件 | 用途 |
|---|---|
| `llama_cpp_local.yaml` | 最简的本地 llama.cpp 模型（从零写起看这个） |
| `jev_27b_vl.yaml` | 带视觉塔 + System-1 决策头的重型模型，附**显存与层数调优结论** |
| `gemma_3_4b_it_gguf.yaml` | 另一个 4B 基础模型示例 |

## 字段速查

```yaml
model: my-model                 # 模型 ID，接口里用它
engine: llama_cpp                # llama_cpp / lmstudio / strata
priority: 80                    # 数值越大越优先被调度
orchestrated: true              # 是否交给 ModelScheduler 管理显存
resident: false                 # true = 常驻显存；false = 用完即回收
immediate: false                # true = 启动后立刻加载
load_timeout: 180               # 加载超时（秒）
request_timeout: 300            # 请求超时（秒）

llama_config:                    # engine=llama_cpp 时才需要
  binary_path: ~/llama.cpp/build/bin/llama-server
  model_path: /path/to/model.gguf
  mmproj_path: /path/to/mmproj.gguf    # 有则自动具备视觉能力
  n_gpu_layers: 99               # 全部层上卡
  ctx_size: 32768
  tensor_split: "11,11"          # 多卡时按显存分配
  flash_attn: "on"
```

> `~` 与 `$VAR` 会被自动展开（见 `infra/orchestrator/llamacpp.py`）。
> 路径写错不会在启动时报错，而是等到「加载模型」时才失败 ——
> `python3 installer.py --doctor` 会提前帮你把失效路径揪出来。
