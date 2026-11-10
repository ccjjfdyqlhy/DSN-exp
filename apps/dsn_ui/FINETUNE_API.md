# 微调工坊 API

dsn_ui 启动后暴露 `/api/finetune/*`——**本地实验用的训练门面**。
它把框架层 `infra/finetune/` 的公开 API 翻译成 HTTP，让「模型工坊」页签能提交训练、
看进度、查日志、晋级/回滚适配器。

> **本文件与 `finetune_api.py` 都属于 apps/ 层，按本地专用策略不上 GitHub**
> （见 `.git/local-only-policy.txt` 与 `docs/expansion/00-local-only-policy.md`）。
> 框架层（`infra/finetune/`、`harness/learning/`）才是进仓库的部分。

## 0. 边界（先读这一段）

| 事项 | 归谁 | 说明 |
|---|---|---|
| 训练怎么跑 | `infra/finetune/train_sft.py` | 独立解释器里的独立脚本，**主进程不 import torch** |
| 作业状态机 / 参数契约 | `infra/finetune/base.py` | `JobState` / `TrainSpec` / `TrainJob` |
| 显存仲裁 | `infra/orchestrator/scheduler.py` 的 `DeviceGate` | 训练与推理抢同一批卡，由同一个闸门裁决 |
| 作业执行与排队 | `infra/finetune/runner.py` | 单 worker，训练天然串行 |
| **本模块** | `apps/dsn_ui/finetune_api.py` | 只做 HTTP 翻译 + 线程池 + 错误文案 |

三层纪律（`docs/architecture.md`）：`apps/ → harness/ → infra/` 单向依赖。
本模块只 import `infra.finetune`，**不反向依赖 harness/，也不自己实现训练逻辑**。

## 1. 端点一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/finetune/env` | 训练栈体检（解释器 / torch / CUDA / 设备 / 依赖 / SDPA 后端） |
| GET | `/api/finetune/environment` | `/env` 的别名 |
| GET | `/api/finetune/devices` | DeviceGate 占用：空闲卡、被谁占了 |
| GET | `/api/finetune/jobs?limit=50` | 作业列表（新 → 旧） |
| GET | `/api/finetune/jobs/{id}` | 单个作业状态 + 指标 |
| GET | `/api/finetune/jobs/{id}/logs?tail=200` | 训练日志尾部 |
| POST | `/api/finetune/jobs` | 提交训练作业 |
| POST | `/api/finetune/jobs/{id}/promote` | 适配器晋级到槽位 |
| POST | `/api/finetune/rollback` | 槽位回滚到上一个适配器 |
| GET | `/api/finetune/adapters` | 适配器清单 + 槽位归属 |
| POST | `/api/finetune/adapters/{id}/activate` | `promote` 的别名 |
| POST | `/api/finetune/adapters/{id}/rollback` | `rollback` 的别名 |
| GET | `/api/finetune/slots` | 槽位登记表 |

## 2. 错误契约

所有错误都是 `{"error": "<中文说明>"}`：

| 状态码 | 含义 | 例子 |
|---|---|---|
| 400 | 调用方写错了 | `缺少必填参数: dataset_path, output_dir` |
| 400 | 参数被框架层拒绝 | `base_model 不能是 GGUF 文件（...）：训练需要 HF 格式权重` |
| 400 | 未知参数 | `未知参数: nope` |
| 404 | 作业不存在 | `作业不存在: job-123` |
| 503 | 环境不可用 | `训练环境不可用: 缺少训练依赖: peft` |

**400 与 503 的区别很重要**：400 是"改一下参数再提交"，503 是"机器上缺东西"，
前端要分开提示，别让用户以为是自己的错。

## 3. 训练栈体检

```bash
curl http://127.0.0.1:8888/api/finetune/env
```

```json
{
  "available": true,
  "reason": "",
  "python": "/home/darkstar/anaconda3/envs/dsn-train/bin/python",
  "warnings": ["FlashAttention-2 不可用（sm_75 正常现象），请使用 sdpa / mem_efficient"],
  "torch": {
    "version": "2.8.0+cu128",
    "cuda_version": "12.8",
    "cuda_available": true,
    "device_count": 2,
    "devices": [
      {"index": 0, "name": "NVIDIA GeForce RTX 2080 Ti",
       "compute_capability": "7.5", "total_memory_mib": 10818}
    ],
    "bf16_supported": false,
    "arch_list": ["sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]
  },
  "packages": {"transformers": "5.20.2", "peft": "0.21.2", "accelerate": "1.15.0"},
  "sdpa": {"flash": "unavailable: RuntimeError: ...", "mem_efficient": "...", "math": "..."}
}
```

体检由**子进程探针**完成（`infra/finetune/probe.py`），所以主进程不需要 torch。
`available: false` 时 `reason` 一定非空——前端要把它显示成红条。

本机常态：`bf16_supported=false`（sm_75 没有原生 bf16）、FA2 不可用（正常现象）。
这两条不是故障，但会直接影响训练参数选择。

## 4. 提交训练

```bash
curl -X POST http://127.0.0.1:8888/api/finetune/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "base_model": "/home/darkstar/qwen_weights/HF/Qwen3-4B",
    "dataset_path": "/home/darkstar/dsn-finetune/smoke-data/train.jsonl",
    "output_dir": "/home/darkstar/dsn-finetune/smoke-out",
    "method": "qlora",
    "max_steps": 2
  }'
```

body 是 `TrainSpec` 的子集；**只接受框架层认识的字段**，多传会报
`未知参数: xxx`（避免前端字段名写错时静默忽略）。

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `base_model` | ✅ | — | **HF 权重路径或仓库名**，不能是 GGUF |
| `dataset_path` | ✅ | — | 数据集文件 |
| `output_dir` | ✅ | — | 产物目录（`spec.json` / `train.log` / `result.json` / `adapter/`） |
| `train_path` | | `dataset_path` | 实际训练用的文件（数据集构建器产出 train/val 时用） |
| `method` | | `qlora` | `qlora` / `lora` / `full` |
| `lora_rank` / `lora_alpha` / `lora_dropout` | | 16 / 32 / 0.05 | LoRA 超参 |
| `target_modules` | | q/k/v/o_proj | LoRA 作用层 |
| `seq_len` | | 1024 | 11GB 单卡的现实上限 |
| `batch_size` / `grad_accum` | | 1 / 16 | |
| `lr` / `epochs` | | 2e-4 / 2.0 | |
| `dtype` / `attn_implementation` | | float16 / sdpa | sm_75 只能这两个 |
| `gradient_checkpointing` | | true | |
| `max_steps` | | -1 | >0 覆盖 epochs（冒烟测试用） |
| `gpus` | | 全部 | 指定卡号，如 `[0]` |
| `seed` | | 42 | |

响应：`{"job": { ...TrainJob }}`，`state` 初始为 `queued`（训练在后台线程跑）。

### 提交前的三道闸

1. **参数自检**（`TrainSpec.validate()`）：缺参、方法不认识、`enable_thinking=True` 一律拒；
2. **GGUF 拦截**：Bonsai-2 / JEV-27B-VL 只有 GGUF，训练用不了——这挡住的是"想训那两个"的误操作；
3. **架构可训练性检查**：用训练解释器里的 transformers 真加载一次模型配置。

三道闸都在**提交时**跑完，不会浪费一次 GPU 作业。

## 5. 作业与日志

```bash
curl http://127.0.0.1:8888/api/finetune/jobs
curl "http://127.0.0.1:8888/api/finetune/jobs/{id}?log_tail=200"
curl "http://127.0.0.1:8888/api/finetune/jobs/{id}/logs?tail=200"
```

`state` 取值：`queued`（排队）→ `running`（训练中）→ `succeeded` / `failed` / `cancelled`。
作业**提交即落库**（`~/dsn-finetune/jobs.db`），进程重启后历史仍在。

> **当前缺口**：还没有「取消」端点。框架层的 `runner.py` 用的是 `subprocess.run`，
> 没有保留子进程句柄，因此无法安全地中途杀掉一次训练。要做取消，需要在
> `infra/finetune/runner.py` 里改成 `Popen` + 进程表（属于框架层改动，会进 GitHub）。

## 6. 晋级与回滚

「训出来了」不等于「上线了」。适配器先是**候选**，晋级到某个**槽位**才生效。

```bash
# 晋级：把某个成功作业的适配器设为槽位当前生效版本
curl -X POST http://127.0.0.1:8888/api/finetune/jobs/{id}/promote \
  -H 'Content-Type: application/json' -d '{"slot": "student"}'
# → {"slot": "student", "job_id": "job-...", "previous_job_id": "job-..."}

# 回滚：把槽位指回上一个版本
curl -X POST http://127.0.0.1:8888/api/finetune/rollback \
  -H 'Content-Type: application/json' -d '{"slot": "student"}'
# → {"slot": "student", "job_id": "...", "previous_job_id": "...", "rolled_back": true}
```

`slot` 省略时默认 `"student"`。没有上一个版本时 `rolled_back: false`，
并带 `reason: "没有上一个版本可回滚"`。

> **注意**：这里只改**登记表**（哪个适配器对哪个槽位生效）。
> 真正把它挂到 llama-server 上跑，靠的是 `infra/orchestrator/llamacpp.py` 的
> `--lora` / `--lora-scaled` / `--lora-init-without-apply`，
> 编排器侧由 `DeviceGate` 决定能不能拿到卡。
> 「晋级 → 挂载 → 评测 → 确认」这条完整链路属于里程碑 M5。

## 7. 显存占用

```bash
curl http://127.0.0.1:8888/api/finetune/devices
# → {"device_count": 2, "free": [0, 1], "occupancy": {}}
```

`occupancy` 的 key 是卡号，value 是租约（`holder` / `reason` / `acquired_at`）。
`holder` 形如 `finetune:job-...`（训练占的）或模型名（推理占的）。

本机的硬约束：**JEV-27B-VL 必须独占双卡**，它在的时候训练只能排队
（`FINETUNE_DEVICE_TIMEOUT`，默认 3600s，超时失败，**不硬抢**）。

## 8. 纪律（写代码时别踩）

- **主进程永远不 import torch**：训练在独立解释器（默认 `~/anaconda3/envs/dsn-train/bin/python`）里跑。
- **训练期不开 thinking**：`TrainSpec.validate()` 直接拒 `enable_thinking=True`。
- **教师只碰 agent 自己的轨迹**：见 `harness/learning/`（框架层，已进 GitHub）。
- **适配器谱系要留痕**：晋级/回滚都写登记表，不要在 UI 里偷偷换版本。
- **别在日志里打密钥**：训练日志会回显到前端。
