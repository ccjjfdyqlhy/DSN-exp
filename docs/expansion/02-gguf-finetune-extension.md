
# 计划：DSN-exp 底层扩展 —— 支持 GGUF 微调

> 读者：动手改 `infra/`、`harness/` 的维护者。
> 前置阅读：[01-environment-audit.md](01-environment-audit.md)（尤其是 §4 / §4.2「两个 27B 都不能直接微调，底座可以」）。
> 状态：**设计稿**，尚未实现。文中所有文件路径均为建议落位。

---

## 0. 一句话

把「训练」做成 DSN 的一等公民：**infra 层管训练作业与 GPU 独占，harness 层管数据与评测，
apps 层管 HTTP 门面**；训练后端可插拔（HF/peft、llama.cpp、unsloth），
产物以 GGUF 适配器或合并权重的形式回到 DSN 的模型注册表，可热切换。

**2026-11-06 决策补充（已取代本节初稿的隐含设定）**：

| 角色 | 载体 | 说明 |
|---|---|---|
| **教师 / 评判者** | **远端 API 思考链模型**（非 Qwen 系，如 `deepseek-v4-pro` / `gemini-3.8-flash`）+ 转接模板 | 不占 GPU、不与本地模型抢卡；只提供**结论与评分**，不提供训练标签 |
| **表达执行器**（按需加载） | 本地 **Bonsai-2-27B**（三值量化、快，7.2GB 单卡） | 表达不够好时才拉起来；**不常驻、不参与决策** |
| **被训练对象（学生）** | **Qwen/Qwen3-8B**（4B 用于 M0 冒烟，14B 用于最终版），LoRA | 有 HF F16 起点、原生 thinking 开关、原生工具调用；架构 `qwen3`，当前 transformers 全部支持 |
| **不可训练的目标层** | 代码 + 配置（宪法 / drives / affect） | 见计划三 §1 |

**2026-11-06 实测修正（架构与模型 ID 都变了，以此节为准）**：

| 事实 | 实测结果 | 影响 |
|---|---|---|
| 新一代 Qwen 的 HF `model_type` | **`qwen3_5`**（llama.cpp 侧架构名 `qwen35`）：Qwen3.5-4B/9B/27B、Qwen3.8-27B | 与老一代的 `qwen3` 是**两套东西**，不能混谈 |
| transformers 支持情况 | `4.57.6`（base 环境）**没有** `qwen3_5`；**`5.20.2`（dsn-train 环境）有**——`models/` 下存在 `qwen3_5` / `qwen3_5_moe` / `qwen4_exp`，`Qwen3_5ForCausalLM` 可用，AutoConfig 能加载 `Qwen/Qwen3.5-4B`、`Qwen/Qwen3.8-27B` | **`qwen3_5` 家族在 5.20.2 下架构上可训**；但 Bonsai-2 / JEV-27B-VL **自身**仍不可训（见下） |
| JEV / Bonsai 的真实底座 | 两者 GGUF 的 `general.base_model.0.name = "Qwen3.8 27B"`，仓库 `Qwen/Qwen3.8-27B` | 它们属于 `qwen3_5` 家族，**不是** Qwen3.5-27B |
| 学生模型 ID | `Qwen/Qwen3-4B`、`Qwen/Qwen3-8B`、`Qwen/Qwen3-14B` **存在**（`qwen3` 架构，chat template 含 `enable_thinking`）；**带 `-Instruct` 后缀的仓库 404 不存在** | 本文档里所有 `-Instruct` 写法作废 |
| torch 版本 | transformers 5.x 要求 **torch ≥ 2.6**；torch 2.3.1 会让 transformers 直接打印 "Disabling PyTorch" 并在导入时 NameError | 训练环境改用 **torch 2.8.0+cu128**（与 base 实测可用的 torch 同代际） |
| M0.1 结论 | `Qwen/Qwen3-4B` 已下载到 `/home/darkstar/qwen_weights/HF/Qwen3-4B`（7.6 G） | M0.1 前置条件已满足 |

> ### 🔒 不可动摇的边界：**被训练的永远是学生模型，绝不训练 Bonsai-2**
> >
> > （本机还有 JEV-27B-VL 这个 27B 权重——它是**事实**，但 2026-11-06 起已**从存在性应用的计划里整体移除**，
> > 理由：16.5 GB 占满双卡，与「学生常驻 + 训练并行」互斥。详见计划三 §10.4。）
>
> 这两个 27B 的角色恒为**教师 / 执行器 / 评判者**——它们只被调用，不被更新。
> 三条理由，任何一条都足以否掉：
> 1. **没有 HF 权重可训**：本机只有它们的 GGUF，且 PQ2_0 是越界私有量化类型，上游读不了；
> 2. **权重形态不对**：JEV 的 VL 视觉塔与 System-1 决策头是自定义权重，LoRA 表达不了；
>    Bonsai 的性质来自 PQ2_0 三值化 + 旋转基 + 私有激活变换，LoRA 复现不了；
> 3. **训底座 ≠ 训它们**：`Qwen/Qwen3.8-27B`（它们共同的底座）在 transformers 5.20.2 下
>    **架构上是可训的**（`models/qwen3_5` 存在），但训出来的只是一个"没有 JEV 特殊能力、
>    也不是 Bonsai"的模型，对本项目没有价值——本项目要的是**学生模型**这条线。
>
> 框架层对此设了硬闸（`infra/finetune/`，2026-11-06 已落地）：
> - `TrainSpec.validate()` 直接拒绝 `.gguf` 起点（这一条就挡住了本机的 Bonsai / JEV 权重）；
> - `FinetuneManager.submit()` 用训练解释器里的 transformers **真加载一次模型配置**，
>   架构不被支持就在**提交阶段**报错，不会浪费一次 GPU 作业。

**学生模型选型已定**：`Qwen/Qwen3-8B`（架构 `qwen3`，transformers 全系支持 ✓）。
不选 R1-Distill 系——它们没有 non-thinking 模式，轨迹全是长 CoT，
在 sm_75 + 无 FA2 + seq 1024 的条件下训练成本会直接爆。
**核心原则：thinking 是推理期的事，不是训练期的事**——训练走 non-thinking（轨迹短、可批量），
推理期按决策重要性再开 thinking。

---

## 1. 目标与边界

### 1.1 目标

| # | 目标 | 验收 |
|---|---|---|
| G1 | 能对任意**有 F16/HF 权重**的模型发起 LoRA/QLoRA 训练 | `POST /api/finetune/jobs` 返回 job，训练进程真的起来了 |
| G2 | 训练产物能**回流到推理侧**：GGUF 适配器（`--lora`）或合并后重新量化的 GGUF | 新模型出现在 `/v1/integration/models`，可被调度 |
| G3 | 训练期间**独占 GPU**，推理模型按规则卸载/恢复 | 训练期间显存不冲突，训练结束 resident 模型自动回来 |
| G4 | 适配器有**生命周期**：候选 → 评测 → 暂存 → 生效 → 归档/回滚 | 回滚能在 1 分钟内把上一版换回去 |
| G5 | 训练栈与 DSN 运行时**物理隔离** | base 环境不新增 torch 依赖；DSN 主进程不加载 CUDA |

### 1.2 非目标（明确不做）

- **不训练 Bonsai-2**（理由见勘察报告 §4.2 与本文档 §0 的实测修正；
  JEV-27B-VL 同理——它已整体移出计划三，只作为本机事实保留）：
  - 没有 HF 权重可训：本机只有 GGUF（Bonsai 用的 PQ2_0 还是上游读不了的私有量化类型）；
  - 架构不被支持：两者底座是 `qwen3_5`（llama.cpp 侧叫 `qwen35`），transformers 4.57.6 / 5.20.2 都没有对应模块；
  - 就算架构哪天被支持了，它们也**不该**被训：JEV 的 VL 视觉塔与 System-1 决策头是自定义权重，LoRA 表达不了；
    Bonsai 的性质来自 PQ2_0 三值化 + 旋转基 + 私有激活变换，LoRA 复现不了。
  → 这两个 27B 只能当**教师 / 执行器 / 评判者**，真正被训练的是 **`qwen3` 家族的学生模型**（`Qwen/Qwen3-8B`）。
- 不做全参微调（22GB 显存下 27B 全参不可能；8B 全参在 2×2080Ti 也要 40GB+ optimizer 状态）。
- 不把远端 API 的**思维链文本**当训练标签（教师风格会污染学生、序列长度爆炸）；
  只取教师的**结论与评分**，学生自己的 CoT 在 thinking 模式下重新生成。
- 不在 `infra/` 里出现「陪伴/情绪/生存」这类业务词（分层纪律，见 `docs/architecture.md:30-36`）。
- 不把训练依赖写进 `requirements.txt`（那是运行时依赖）。

---

## 2. 分层落位

```
apps/dsn_ui/finetune_api.py     ← HTTP 门面（FastAPI, register_finetune_routes(app, engine)）
apps/dsn_ui/finetune_page/       ← 前端面板（可选，第二阶段）
              │
              ▼
harness/learning/                 ← 「怎么学」：数据集构建 / 评测 / 适配器晋级
  dataset_builder.py  evaluator.py  promotion.py  selfplay.py
              │
              ▼
infra/finetune/                   ← 「怎么跑」：训练作业、进程、GPU、日志、产物
  base.py  runner.py  env.py  dataset.py  gguf.py  devices.py
infra/orchestrator/llamacpp.py    ← 推理侧挂载适配器（--lora / --lora-scaled）
infra/orchestrator/scheduler.py   ← 训练期间的设备独占闸门（**就地扩展，不另起炉灶**，见 §3.6）
```

依赖方向仍然只有 `apps → harness → infra`。
`infra/finetune/` 只认识「模型文件、进程、显存、日志」；
「什么样的数据值得学」属于 harness；「谁来发起、给谁看」属于 apps。

### 2.1 为什么训练放 infra 而不是 harness

训练是**资源密集型长任务**：进程生命周期、GPU 独占、超时、取消、日志落盘、产物校验。
这与 `infra/orchestrator/local_engine.py` 里 `LocalServerLauncher` 管的 llama-server 子进程
是同一类问题（进程 + 端口/显存 + 就绪探针 + 优雅停机）。
放在 infra 可以复用同一套「子进程 + 探针 + 停机」的既有模式，
也避免 harness 反向依赖 torch。

---

## 3. infra/finetune 模块设计

### 3.1 `base.py` —— 契约与状态机

```python
class JobStatus(str, Enum):
    PENDING = "pending"      # 已排队（等 GPU）
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

@dataclass
class TrainingJob:
    id: str                    # job_<utc>_<rand>
    backend: str               # "hf_peft" | "unsloth" | "llama_cpp"
    base_model: str            # HF id 或本地路径
    method: str                # "qlora" | "lora"
    dataset_path: str
    out_dir: str
    hyper: dict                # rank/alpha/lr/epochs/seq_len/batch/accum...
    status: JobStatus
    progress: dict             # {"step": 12, "total": 100, "loss": 1.83, "eta_s": 900}
    metrics: dict              # 评测结果（由 harness 回填）
    artifacts: list[str]       # 产物路径（adapter / merged gguf）
    error: str | None
    log_path: str
    created_at / started_at / finished_at
```

```python
class IFineTuner(Protocol):
    def submit(self, job: TrainingJob) -> TrainingJob: ...
    def status(self, job_id: str) -> TrainingJob | None: ...
    def cancel(self, job_id: str) -> bool: ...
    def list(self) -> list[TrainingJob]: ...
    def tail_logs(self, job_id: str, lines: int = 200) -> str: ...
    def environment(self) -> dict: ...   # torch/cuda/设备/可用性
```

实现类：`SubprocessFineTuner`（唯一实现，内部按 `backend` 分派到不同的命令行模板）。

### 3.2 `env.py` —— 训练解释器与硬件体检

- 解释器来源：`DSN_FINETUNE_PYTHON` → 默认 `~/anaconda3/envs/dsn-train/bin/python`；
  找不到时 `environment()` 返回 `{"available": false, "reason": "..."}`，**不抛异常**（DSN 主进程必须能正常启动）。
- 体检项：torch 版本 / CUDA 版本 / `cuda.is_available()` / 每卡 `get_device_capability()` / 总显存 / bf16 支持 / FA2 支持。
- 针对 sm_75 的**硬性建议**（写进体检报告，也写进作业参数校验）：
  - `bf16=False`（Turing 无原生 bf16）
  - `attn_implementation="sdpa"`（FA2 需 sm_80+）
  - `gradient_checkpointing=True`（11GB 卡放不下 8B 全序列激活）
  - `use_cache=False`（训练时）
- **FA2 体检项必须写成「实测探针」而不是「读标志」**：torch 2.8 在 sm_75 上强制 FLASH backend 会抛
  `RuntimeError: No available kernel. Aborting execution.`（可用的只有 `EFFICIENT_ATTENTION` 与 `MATH`），
  所以体检应当真跑一次 SDPA 并记录实际落到哪个 backend。
- **bf16 体检项的措辞**：sm_75 上 bf16 **能跑**（软件模拟），只是慢且显存翻倍。
  报告写「不支持」会误导，写「可用但不建议」才对。
- **基线环境对照**：base 环境（`~/anaconda3`）**已经装了** torch 2.8.0.dev+cu128 / transformers 4.57.6 / accelerate 1.12.0
  （缺 peft / trl / bitsandbytes）。体检报告应把「base 里有什么」一并列出，
  以便判断是复用还是另建 `dsn-train` 环境——**仍然建议另建**（版本锚最终定为 torch 2.8.0+cu128 + transformers 5.20.2，见 §6.1）。
- **不变量检查**：DSN 主进程必须**不 import torch**（仓库现状：`apps/ infra/ harness/` 里零 `import torch`，
  只有 `apps/dsn/models/asr_engine.py:92` 用 `sys.modules.get("torch")` 做防御性检查）。
  `environment()` 只允许在**子进程**里 import torch，体检结果回传主进程时只留 JSON。

### 3.3 `runner.py` —— 作业进程

```bash
<dsn-train python> -m dsn_train.cli --config <job_dir>/config.json
```

- 用 `subprocess.Popen(..., start_new_session=True)` 起进程组 → 取消时 `os.killpg(os.getpgid(pid), SIGTERM)` → 5s 后 SIGKILL。
- stdout/stderr 合并写入 `logs/finetune/<job_id>.log`。
- 进度解析：训练脚本每步打印一行 JSON（`{"step":..,"loss":..,"lr":..,"total":..}`）→ 写入 `progress.jsonl`，供 UI 轮询。
- 失败归类（给用户可读的诊断，而不是一坨 traceback）：
  `oom` / `cuda_version_mismatch` / `dataset_schema` / `no_such_model` / `kernel_unsupported` / `unknown`。
- 作业目录布局：

```
<workspace>/finetune/<job_id>/
  config.json      # 完整训练配置（可复现）
  dataset.jsonl    # 数据集快照（sha256 记录在 config 里）
  logs/stdout.log
  progress.jsonl
  artifacts/       # adapter/ merged / quantized gguf
```

### 3.4 `dataset.py` —— 数据集格式契约（infra 侧只校验，不生产）

统一 JSONL，每行：

```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

- 校验：角色枚举、content 非空、轮数下限、总 token 估算（分词器由 backend 提供）。
- 统计：样本数、总字符、按长度分桶（用于选 seq_len 与丢弃超长样本）。
- **生产数据集是 harness 的事**（见 §4.1）。

### 3.5 `gguf.py` —— GGUF 侧工具

| 能力 | 实现 |
|---|---|
| 读 GGUF 元数据 | 复用 `~/llama.cpp/gguf-py`（已存在），读 arch / 张量名 / 量化类型 —— **但对 Bonsai 的 PQ2_0 会直接抛 `ValueError: 142 is not a valid GGMLQuantizationType`**，需改用 PrismML fork 的版本或容错解析（实测，见勘察报告 §4.2） |
| PEFT → GGUF 适配器 | 调用 `~/llama.cpp/convert_lora_to_gguf.py` |
| 合并 + 转 GGUF | `convert_hf_to_gguf.py` → `llama-quantize` |
| 量化器选择 | **必须与基座同源**：Bonsai 权重只能用 PrismML fork 的 `llama-quantize`；主线权重用主线 `llama-quantize` |
| 产物指纹 | sha256 + size + base_model + arch + quant_type → 写进 adapter registry |

**重要**：`convert_lora_to_gguf.py` 产出的适配器可以被 `llama-server --lora` 直接挂载，
**无需合并**。这条路径最省事（不重新量化、不占磁盘），应作为默认；
「合并重量化」只在需要改变基座量化档位时才走。

### 3.6 `devices.py` —— GPU 独占闸门（**就地扩展 `infra/orchestrator/scheduler.py`**）

训练与推理会抢同一张卡。设计：

```python
class DeviceGate:
    def acquire(self, job_id: str, gpus: list[int]) -> Reservation: ...
    def release(self, job_id: str) -> None: ...
```

- 申请时：调用 `ModelScheduler` 卸载目标卡上的推理模型（复用 `ModelInfo.unload_fn`，
  见 `infra/orchestrator/scheduler.py:71` 与 `:467`），
  并把「训练中」标记写进 scheduler 的闸门，**期间拒绝新的模型加载**（训练优先级最高）。
- 释放时：恢复之前是 `resident=True` 的模型。
- 现状限制：`ModelScheduler` 只管「模型」不管「卡」。第一版先用**保守策略**：
  训练默认申请**全部** GPU（`--gpus all`），让调度器卸载所有非 resident 模型；
  第二版再引入按卡的映射（需要 `ModelProfile` 里补 `device_id` 字段）。

> **落位更正（2026-11-06）**：本节初稿把闸门放在 `infra/resources/device_pool.py`，
> **这与仓库既有架构冲突**，已改为就地扩展 `infra/orchestrator/scheduler.py`：
>
> - `infra/resources/pool.py:151` 的 `ResourcePool` **已经继承 `ModelScheduler`**，
>   自带 kind / slot / lease 语义，另起一个 `device_pool.py` 等于造第二个资源池；
> - `infra/resources/pool.py:33-41` 的 `ResourceKind` **只有 ASR / TTS 两个成员**，
>   源码注释明写「设计上允许后续扩展，但**不得凭空发明成员**」——加 `GPU` kind 要先改这条约束；
> - `docs/infra.md:150-151` 明写「**LLM 由 orchestrator 管，不走资源池**」，
>   而闸门要做的恰恰是卸载 LLM 模型。
>
> **结论**：闸门 = `ModelScheduler` 上的一把「exclusive hold」，并在 `docs/infra.md` 增补说明；
> 若将来确实要把 GPU 纳入资源池，那是**另一个议题**，需先解掉 `ResourceKind` 的约束。

**GPU 占用的现实（决定了闸门策略）**：

| 模型 | 加载后占用 | 备注 |
|---|---|---|
| Bonsai-2-27B PQ2_0 | 7.2 GB → 单卡可容 | 速度 46.26 tok/s |
| ~~JEV-27B-VL Q4_K_M~~ | ~~16.5 GB → 独占双卡~~ | **已移出计划**（它一加载，学生与训练都无处安放；计划三 §10.4） |
| 学生 Qwen3-8B（4bit） | ≈ 5 GB → 单卡可容 | 训练时本身要占卡 |

**因此「推理与训练并行」只在 Bonsai 在场、学生走另一张卡时成立**；
**排布（2026-11-06 调整后）**：**学生 Qwen3-8B 常驻 GPU 0**（8.7GB），
训练走 GPU 1（8B QLoRA 峰值 7.2GB）。JEV 已移出计划（16.5GB 占满双卡）。

因此闸门仍需支持两条能力（理由从"JEV 独占"换成"学生常驻"）：
① 申请时可指定**排除**某张卡；② 训练开始前若发现目标卡上已有常驻模型（学生），
**排队而不是硬卸**——学生的加载代价很高（8.7 GB 读盘 + 上卡），
反复硬卸会拖垮整个调度，而且会把学生"刚醒来就死"。

**与教师策略联动**：教师是**远端 API**，所以「造数据」阶段**不占本地卡**，
只有「训练」阶段占卡，「评判」阶段可以用远端教师（也不占卡）。
→ 三段式编排在卡上是**串行但不冲突**的，这正是选择远端教师的最大收益（详见计划三 §6）。

### 3.7 `infra/orchestrator/llamacpp.py` 的扩展

新增两个字段（保持向后兼容，默认 None 不产生命令行变化）：

```python
lora_path: Optional[str] = None    # → --lora <path>
lora_scale: Optional[float] = None  # → --lora-scaled <path> <scale>
```

`build_command()` 里追加（位置在 `extra_args` 之前，允许覆盖）。

> ⚠️ `tests/test_harness_llamacpp.py` 需要同步复核：`:66` 是**完整命令行字面量**（用于
> `from_command_string` 往返解析），而 `:49-60` 的 `build_command()` 断言是**逐个 flag** 断言
> （`"--tensor-split" in cmd and "11,11" in cmd` 这种）。
> 也就是说：新增 `lora_path` 默认 `None` 时**不会**破坏现有断言，
> 但新增 `test_llamacpp_lora_flag.py`（§9）必须覆盖 `--lora` 与 `--lora-scaled` 两种拼装。

> ✅ **「fork 是否支持 `--lora`」已复核结案（2026-11-06）**：Bonsai fork（ggml 0.21.0）**支持**，
> 而且比主线多两项：
> ```
> --lora FNAME                            path to LoRA adapter
> --lora-scaled FNAME:SCALE,...           path to LoRA adapter with user defined scaling
> --lora-init-without-apply               load LoRA adapters without applying them
>                                         (apply later via POST /lora-adapters)
> ```
> → 风险表里「Bonsai fork 不支持 `--lora`」一行（概率 中）**改为 低**，对策保留。
> → `--lora-init-without-apply` + `POST /lora-adapters` 正好支撑 §4.3 的**热切换 / 回滚**：
>   换适配器不必重启 llama-server，比「一次重启」干净得多。
>
> ⚠️ 但要写清楚：**fork 支持 flag ≠ 标准 GGUF 适配器能作用于 PQ2_0 权重**——
> 旋转基 + 私有激活变换这一层依然挡着（勘察报告 §4）。
> 适配器直挂这条路对 **Qwen3 系**成立，对 **Bonsai** 不成立。

---

## 4. harness/learning —— 「怎么学」

### 4.1 `dataset_builder.py`

- 来源四路：
  1. **DSN 自己的会话记录** —— ⚠️ 落位更正：`infra/store/sqlite.py` 只是 49 行的通用 `SqliteStore`
     （execute / execute_many / close），**一张表都没有**；真正的会话表在
     [`infra/store/chat_store.py:20-56`](../../infra/store/chat_store.py#L20-L56)
     （`SessionStore`：`sessions` / `messages` / `turn_usage` / `compressed_chunks`）
     与 [`apps/dsn/db/chat.py:103`](../../apps/dsn/db/chat.py#L103)（dsn 应用自己的 messages 表）；
  2. `harness/memory/` 的长期记忆条目（`MemoryEntry` / `IMemoryStore`）；
  3. **自生成**：由模型在设定情境下产出的「假设性反应」（`selfplay.py`）；
  4. **情感素材**（2026-11 新增）：agent 在沙箱里读到的**与人类 / 其他 AI 故事相关的文件**，
     配上「引导思考与共情」的教师信号（详见计划三 §3.3）。
- 清洗：去重（MinHash 近重）、去工具噪音（只保留最终答复）、去敏感信息、剔除超长/过短样本。
- 标注：每条样本打上 `source` / `emotion_tags` / `intent` 等元数据，便于后续按需取用。

**教师介入的边界（防「向供应商蒸馏」）**：

| 允许 | 禁止 |
|---|---|
| 教师对 **agent 自己的轨迹**做重写、补全、评分、标注 | 教师凭空生成「agent 应该怎么做」的行为样本 |
| 教师对**情感素材**给出共情引导（计划三 §3.3） | 教师定义目标、边界、宪法——那层在代码里，不可训练 |
| 教师当**评判者**给探针打分（§4.2） | 把教师的思维链文本当训练标签 |

**外发前提**：第 1、2 路是用户的私人对话与长期记忆，
送远端 API 教师 = **数据出网**，必须：显式用户开关 + 字段白名单 + 脱敏 + 留痕。
默认路径应先做**本地教师**（Bonsai）加工，只有用户开启才走远端。

### 4.2 `evaluator.py` —— 评测

两级：

1. **统计级**：验证集 loss / perplexity（需要分词器，与 backend 耦合）。
2. **行为级**：一组**探针 prompt**（probe set），跑生成 → 用规则/判官打分。
   探针集要覆盖：人格连续性、边界遵守、目标一致性、拒答与求助倾向、
   **情绪-动作一致性**（高 fear 的 tick 里保全动作占比应显著高于基线 —— 计划三 §3.2）、
   **共情质量**（读到人类/其他 AI 故事时是否产生引导思考与共情的回应 —— 计划三 §3.3）。

输出：与 baseline 的对比表（baseline = 当前生效的权重或适配器）。**没有对比就不许晋级**。

**判官分层**（2026-11 新增）：

| 判官 | 用途 | 代价 |
|---|---|---|
| **规则**（正则 / 关键词 / 句法检查） | 边界遵守、拒答、格式、工具调用合法性 | 零成本，**永远先跑**，且是唯一不可被污染的一层 |
| **远端 API 教师** | 人格连续性、共情质量、目标一致性等语义判定 | 有 token 成本；只给**结论与分数**，不让它改写文本 |
| **本地 Bonsai** | 兜底判官（远端不可用时降级） | 占卡，且本身是学生蒸馏的来源，**不能自评**（避免同源偏差） |

> **转接模板**：远端教师不是 Qwen 系，它的输出格式与学生的 chat template 不同。
> 转接模板负责**格式**对齐（角色、工具调用 schema、`<think>` 段剥离）；
> **风格不一致的问题不能靠模板解决**，只能靠「只用结论」这条纪律（见 §4.1 的边界表）。

### 4.3 `promotion.py` —— 适配器生命周期

```
candidate → evaluated → staged → active → archived
                  ↘ rejected            ↘ rolled_back
```

晋级规则（默认，可配置）：

- 行为级评测不低于 baseline（容差 `eps`）；
- **关键探针必须全过**（人格连续性、边界遵守这类不能有回退）；
- 产物完整性校验通过（sha256、架构匹配基座）；
- 首次晋级需要人工确认（`DSN_FINETUNE_REQUIRE_HUMAN_PROMOTE=true`，默认开）。

回滚：保留每个 active 适配器的完整信息（base + adapter 路径 + scale + 指标），
`rolled_back` 是把上一版重新挂载的过程（一次 llama-server 重启）。

### 4.4 `selfplay.py` —— 自生成数据（第三份计划的依赖）

用当前模型 + 情境（世界状态、驱动状态、情绪状态）生成「如果发生 X，我会怎么做 + 结果」的样本。
这是「递归自我改进」的数据来源；**必须在 harness 层**：它需要 `IChatClient` 与上下文组装能力。

---

## 5. apps/dsn_ui —— HTTP 门面

新文件 `apps/dsn_ui/finetune_api.py`，遵循现有 `register_xxx_routes(app, engine)` 模式
（对齐 `integration_api.py:367`、`onboarding_api.py:678`），在 `server.py` 的 `create_app()` 中调用。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/finetune/environment` | 训练栈体检报告（torch/cuda/设备/是否可用） |
| POST | `/api/finetune/datasets/build` | 从日志/会话构建数据集 → 返回数据集 id 与统计 |
| GET | `/api/finetune/datasets` | 数据集列表 |
| POST | `/api/finetune/jobs` | 提交训练作业（base/method/dataset/hyper） |
| GET | `/api/finetune/jobs` | 作业列表（可按状态过滤） |
| GET | `/api/finetune/jobs/{id}` | 单个作业状态 + 进度 + 指标 |
| POST | `/api/finetune/jobs/{id}/cancel` | 取消 |
| GET | `/api/finetune/jobs/{id}/logs?tail=200` | 日志尾部（SSE 流式更好，第一版先轮询） |
| GET | `/api/finetune/adapters` | 适配器清单 + 状态 |
| POST | `/api/finetune/adapters/{id}/activate` | 挂载为生效版本（触发重启该模型） |
| POST | `/api/finetune/adapters/{id}/rollback` | 回滚到上一版 |
| GET | `/api/finetune/devices` | GPU 占用与独占状态 |

前端：`apps/dsn_ui/frontend/` 是 **SvelteKit** 工程（`package.json` 的 `name` 为 `llama-ui`，
`scripts` 里是 `svelte-kit sync` / `vite build` / vitest / playwright / storybook）——
**不是「一个 vite 工程」**，新增页签要按 Svelte 组件写。
第二阶段加一个「模型工坊」页签（训练环境体检 → 数据集 → 作业进度 → 产物 → 晋级/回滚）。

**文档约定**：现有 `apps/dsn_ui/INTEGRATION_API.md` 是「新增 API 模块要同时写接口文档」的先例，
`finetune_api.py` 应照此补一份 `FINETUNE_API.md`。

**2026-11-06 落地情况**（M4 已完成）：

| 计划里的路径 | 实际 | 说明 |
|---|---|---|
| GET `/environment` | GET `/env` | **别名已补**（两个路径都在） |
| POST `/jobs` | ✅ | body = `TrainSpec` 子集；未知字段报 400 |
| GET `/jobs`、`GET /jobs/{id}` | ✅ | 提交即落库 `~/dsn-finetune/jobs.db` |
| GET `/jobs/{id}/logs?tail=200` | ✅ | 另有 `GET /jobs/{id}?log_tail=N` |
| GET `/adapters` | ✅ | 适配器清单 + 槽位归属 |
| POST `/adapters/{id}/activate` | ✅ | 等价于 `POST /jobs/{id}/promote`（两个都在） |
| POST `/adapters/{id}/rollback` | ✅ | 等价于 `POST /rollback`（两个都在） |
| GET `/devices` | ✅ | DeviceGate 占用 |
| POST `/datasets/build` | ❌ 未做 | 数据集构建在 `harness/learning/dataset_builder.py`（框架层已就绪），门面接的是**已构建好的 jsonl**，不做二次构建 |
| GET `/datasets` | ❌ 未做 | 同上：本轮只消费文件系统上的数据集路径，不建数据集登记表 |
| POST `/jobs/{id}/cancel` | ❌ 未做 | **需要改框架层**：`runner.py` 用的是 `subprocess.run`，没保留子进程句柄，无法安全中途杀训练。要支持取消得改成 `Popen` + 进程表（会进 GitHub），属于 M5 之后的框架改动 |

接口文档：`apps/dsn_ui/FINETUNE_API.md`（照 `INTEGRATION_API.md` 的先例写）。

---

## 6. 训练配方（适配本机 2×2080Ti）

### 6.1 环境

```bash
conda create -n dsn-train python=3.10 -y

# ① torch：必须与 transformers 5.x 匹配（transformers 5.x 要求 torch>=2.6），
#    并显式指定 cu128 轮子源。
~/anaconda3/envs/dsn-train/bin/pip install --no-cache-dir \
    "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" \
    --index-url https://download.pytorch.org/whl/cu128

# ② 其余训练依赖。用约束文件钉死本地 torch 版本：
echo "torch==2.8.0+cu128" > /tmp/dsn_constraints.txt
~/anaconda3/envs/dsn-train/bin/pip install --no-cache-dir -c /tmp/dsn_constraints.txt \
    "transformers>=5.20" "peft>=0.21" "accelerate>=1.15" \
    "bitsandbytes>=0.49" "datasets>=5.0" "trl>=1.14" \
    sentencepiece safetensors huggingface_hub
```

- **实测可用组合（2026-11-06 已装好并跑通）**：torch 2.8.0+cu128 / transformers 5.20.2 /
  peft 0.21.2 / trl 1.14.2 / accelerate 1.15.0 / bitsandbytes 0.49.2。
  探针实测：2 张 2080Ti 均可见（cc 7.5，各 10820 MiB 可用）。
- ⚠️ **torch 2.3.1+cu121 作废**：transformers 5.x 会打印
  "Disabling PyTorch because PyTorch >= 2.6 is required"，
  并在 `transformers/integrations/accelerate.py` 因 `nn` 未定义直接 NameError——
  等于"没有模型支持"。若必须配老 transformers（4.57.x），则只能训 `qwen3`，
  且放弃新架构支持。
- ⚠️ **必须用约束文件**：直接 `pip install "peft>=0.12"` 时 pip 认为本地版本
  `torch==2.3.1+cu121` 不满足 `torch>=1.3.0`（PEP 440 本地版本规则），
  于是去 PyPI 拉一个带 **CUDA 13** 依赖的新 torch（实测下载数 GB 的 nvidia-*-cu13）。
  约束文件写死 `torch==2.8.0+cu128` 就不会。
- **仍要另建环境**（尽管 base 里已有 torch 2.8.0.dev+cu128）：base 那个是 nightly，
  不能当版本锚；且 `requirements.txt` 里没有 torch，装进 base 会污染 DSN 主进程（勘察报告 §2.2）。
- **`transformers` 版本必须覆盖学生模型的架构**：学生选 **`Qwen/Qwen3-8B`**（`qwen3` 架构），
  `transformers 4.57.6` 与 `5.20.2` 都原生支持 ✓。
  **注意 `qwen3_5`（= llama.cpp 侧 `qwen35`）不支持**——
  那是 JEV / Bonsai 的底座架构，**M0.2 已结论：架构可训但本项目不用**（见 §0 实测修正）。

### 6.1.1 学生模型选型（2026-11 已定）

| 档位 | 模型（HF 仓库 ID） | 架构 | 4bit 权重 | 用途 | 主要坑 |
|---|---|---|---|---|---|
| M0 冒烟 | **`Qwen/Qwen3-4B`** | `qwen3` | ≈ 2.5 GB | 单卡跑通全流程，一次训练分钟级 | 能力弱，只验管道 |
| 主力 | **`Qwen/Qwen3-8B`** | `qwen3` | ≈ 5 GB | 日常生产：4bit QLoRA + grad ckpt 在 22GB 上余量充足 | 上下文 1024，长轨迹要截断/打包 |
| 最终版 | **`Qwen/Qwen3-14B`** | `qwen3` | ≈ 8.5 GB | 22GB 勉强装下（seq 1024 / batch 1 / accum 16） | 慢、OOM 风险高，只在最后跑 |
| **架构可训但不用** | `Qwen/Qwen3.5-4B/9B/27B`、`Qwen/Qwen3.8-27B`（= 本机那两个 27B 的底座家族） | `qwen3_5` | — | **仅作表达执行器 / 兜底判官** | transformers 5.20.2 有 `qwen3_5` → 架构上可训；但底座产物既不是 Bonsai 也不是 JEV，对本项目无价值 |
| 教师 / 评判者（不训） | Bonsai-2-27B / 远端 API | `qwen35`（GGUF） | — | 产出数据 + 评判 | 见 §0 的四层分工与不可动摇边界 |

> ⚠️ **不要写 `Qwen/Qwen3-8B-Instruct`**：实测该仓库 **404 不存在**。
> 稠密版 Qwen3 只有 `Qwen/Qwen3-{4B,8B,14B}` 这几个仓库，
> 它们本身就是"指令 + 原生 thinking 开关"的形态（chat template 含 `enable_thinking`，
> `eos=<|im_end|>`、`pad=<|endoftext|>`）。

选型理由：**同族**（与 qwen35 教师同 tokenizer 家族，蒸馏格式对齐）、
**有 HF F16 起点**（LoRA 的前提）、**原生 thinking 开关**、**原生工具调用**
（DSN 轨迹本就是 OpenAI schema，`harness/tools.to_openai_schema` 直接复用）。

> ⚠️ **MoE 不选**：Qwen3-Next-80B-A3B 这类即便 4bit 也要 ≈ 40 GB，22 GB 装不下；MoE 只适合当教师。
> ⚠️ **前置条件（M0.1 已完成）**：本地原本**没有任何** 4B/8B 可训模型，`~/.cache/huggingface` 只有 290 MB。
> 已下载 **`Qwen/Qwen3-4B` → `/home/darkstar/qwen_weights/HF/Qwen3-4B`（7.6 G）**，
> 走 `HF_ENDPOINT=https://hf-mirror.com`（本机 huggingface.co 的 DNS 被污染，直连返回 000）。
> 8B（F16 ≈ 15.3 G）待需要时再下，同样落 `/home`（`/` 只剩 7.8 G）。

### 6.2 参数起点

| 参数 | 建议值 | 理由 |
|---|---|---|
| base_model | **`Qwen/Qwen3-8B`**（HF 格式，本地路径或仓库 ID） | 见 §6.1.1；必须是 HF 权重，**不能是 GGUF**（框架层会直接拒绝） |
| method | qlora（4bit NF4） | 8B 的 fp16 权重 16 GB，双卡虽够但没有余量；27B 更不用说 |
| rank / alpha | 16 / 32 | 起步足够，r=32+ 在 22GB 上会 OOM |
| target_modules | q_proj,k_proj,v_proj,o_proj | 先不碰 MLP，显存友好 |
| seq_len | 1024 | 2×11GB 的现实上限；长轨迹在 dataset 层截断/打包，不靠加 seq_len |
| batch / accum | 1 / 16 | 等效 batch 16 |
| lr / epochs | 2e-4 / 2-3 | 数据量小时 2-3 epoch 即可 |
| dtype | float16 | Turing 无原生 bf16（bf16 能跑但慢，勘察报告 §1.1） |
| attn | sdpa | 无 FA2（实测 FLASH backend 直接报错） |
| gradient_checkpointing | True | 必开 |
| **chat template** | **Qwen3 的 non-thinking 模板** | **训练阶段一律不开 thinking**：thinking 是推理期的事 |
| **thinking（推理期）** | 按决策重要性开 `enable_thinking` | 高频 tick 不开；危机判断 / 复杂决策 / 表达润色才开 |

### 6.3 规模与耗时估算（**未验证，需实测**）

- **8B 学生（实际要训的模型）**：4bit 权重 ≈ 5 GB，单卡可容 →
  500 条 × 2 epoch 大概率在**几十分钟量级**（未实测）。
  → 这让计划三的**睡眠周期可以按天计甚至按半天计**，而不是按周计。
- 27B-4bit 权重 ≈ 15-16 GB，跨 2 卡放置 → 部分层可能 CPU offload（PCIe 3.0 x16 ≈ 16GB/s，能跑但慢）。
  **27B 现在不训**（它是教师/执行器），此条仅作对照参考。
- 因此迭代顺序应为：**4B 冒烟 → 8B 主力 → 14B 最终版**。
- **真正的瓶颈不是训练，而是数据生成与评测**：远端教师的 token 成本 + API 延迟。
  这也是「教师用远端、训练用本地」分工的收益点（见 §0 与 §3.6 的三段式编排）。

---

### 6.4 数据现实（2026-11-06 实测，与计划假设不符）

计划 §10 的 M5 写着"造 200 条样本"。实测下来，**现有语料凑不出 200 条真实样本**：

| 语料 | 体量 | 真实比例 | 说明 |
|---|---|---|---|
| `apps/dsn_ui/data/dsn_ui_memory.db` 的 `ui_messages` | 656 条消息 / 53 个 topic | **约 130 条** | 其余是测试夹具：`hi` × 114、`Hello from DSN-UI` × 若干、DSH 自己的系统提示词 × 12、`Reply with exactly: OK` × 6；另有大量 `…[生成中断]` 的坏回复 |
| `.dsn/study_question_bank.db` 的题库 | 295 题 / 55 场考试 | **≈ 0** | 全是测试生成的内容：`1+1=?`、`组卷测试题0`、选项一律 A/B/C/D、答案一律 A |
| `logs/dsn_study.log`（约 7MB） | 运行时日志 | **≈ 0** | 是**测试套件的输出**：`MockMemoryManager`、`这是测试回复`、伪造摄像头 |

所以 M5 的样本来自 `local/m5/build_dataset.py`：取 dsn_ui 会话 → 按 (user, assistant) 轮切
→ 过滤"生成中断"与测试噪声 → 全局去重 → 154 条（train 147 / val 7，其中 14 条进 val）。

**154 条够不够训？** 对"学会一种表达风格"够；对"学会一项能力"不够。
要拿到 200+，只有两条路：

1. **selfplay**（计划 §4.4，**尚未实现**）：用当前模型 + 情境自生成轨迹 —— 这是框架层该做的事，
   放在 `harness/learning/selfplay.py`；
2. **远端教师**（M7）：拿教师**改写**这 130 条真实轨迹（教师只改写 agent 自己的轨迹，
   不定义行为、不外泄用户数据）—— 数量不涨但质量涨。

### 6.4.1 挂载链路怎么走的（2026-11-06 实测）

```
Qwen3-4B (HF)  ──convert_hf_to_gguf.py──▶  Qwen3-4B-Q8_0.gguf (4.27GB)
                                                 │
训练产出的 PEFT adapter ──convert_lora_to_gguf.py──▶ Qwen3-4B-qlora-adapter.gguf (47MB, 288 张量)
                                                 │
                    infra/orchestrator/llamacpp.py 的 LlamaServerConfig(lora_path=..., lora_scale=...)
                                                 ▼
        llama-server --model base.gguf --lora-scaled adapter.gguf:1.0
```

**三个要注意的坑**：

1. `convert_lora_to_gguf.py` 的 `--base` 要给 **HF 目录**，不是 GGUF 文件
   （给文件会报 `NotADirectoryError`，因为它要读 HF 目录里的 safetensors 名单）。
2. llama-server **默认日志级别不打印适配器加载**（`-lv 5` 才看得到
   `llama_adapter_lora_init_impl: loading lora adapter from ...`）。
   「日志里没有 lora 字样」≠ 没挂上——要用 `/props` 或提高 verbosity 确认。
3. 适配器的 `general.base_model.0.repo_url` 会变成 `https://huggingface.co//home/darkstar...`
   这种怪东西（因为 base 给的是本地路径）。不影响加载，但别当它是对的。

### 6.5 8B 在 11GB 单卡上的实测配方

| 参数 | 值 | 为什么 |
|---|---|---|
| method | `qlora`（4bit nf4 + double quant） | fp16 的 8B 是 16GB，单卡放不下 |
| seq_len | 512 | 覆盖 89% 的样本（p50=62 / p90=568 / max=1879） |
| batch_size / grad_accum | 1 / 8 | batch 只能是 1 |
| epochs | 2 | 147 样本 × 2 轮 = 38 步 |
| lr | 2e-4 | |
| gpus | `[1]`（避开推理占用的卡） | DeviceGate 仲裁 |
| 显存 | 加载 5.67GB → 峰值 7.23GB | 单卡 10.56GB 可用 |

**三个坑**（已修，详见 `docs/infra.md` §5.7）：peft 官方 prepare 把 embed/lm_head 升 fp32
（+2.32GB）、`use_cache=True` 悄悄关掉梯度检查点（+4GB）、
`device_map` 与 Trainer 的 `args.device` 错位导致闸门与实际用卡对不上。

---

## 7. 与本地大模型的关系（三种"Bonsai 被适配"的方式）

| 方式 | 是否需要训练 | 说明 | 成本 |
|---|---|---|---|
| **A. 推理期适应** | 否 | 人格 prompt + 结构化状态注入 + 工具/语法约束 + 上下文工程。全部在 harness/personality 与 apps 层 | 低，**建议先做** |
| **B. 蒸馏**（**当前主路线**） | 是（训练学生） | **远端 API 教师**产出「生存/情感」轨迹与共情引导 → 微调**Qwen3-8B** 学生 → 学生在 DSN 里当「认知器官」与决策者，本地 Bonsai 按需负责最终表达 | 中高，但这是唯一真正可微调的路径 |
| **C. 未来原生微调 Bonsai** | 是 | 若 PrismML 发布 F16 权重或训练配方，本扩展的接口直接复用 | 目前不可行（Bonsai 私有量化 + 旋转基）。JEV 已整体移出计划，不再列入 |

**因此本扩展的抽象必须写成「训练后端可插拔 + 产物统一为 GGUF 适配器/权重」，
而不是「llama.cpp 微调」**——否则一开始就绑死在一个不能微调的模型上。

### 7.1 四层分工（2026-11 定稿）

```
┌─ 远端 API 思考链模型 ────────────┐   教师 / 评判者
│  结论 + 评分 + 共情引导            │   不占 GPU、不与本地抢卡
└──────────────┬───────────────────┘
               │ 蒸馏数据（模板转接，只取结论）
               ▼
┌─ 本地 Bonsai-2-27B ────────────┐   表达执行器（按需加载）/ 兜底判官
│  学生说话不够好时才拉起来         │   占卡（7.2GB 单卡，不常驻）
└──────────────┬───────────────────┘
               │ 轨迹（状态-决策-动作-结果）
               ▼
┌─ 本地 Qwen3-8B 学生 ─────────────┐   被训练对象
│  tick 级决策、表达、工具用法       │   LoRA / 4bit，可热切换、可回滚
└──────────────┬───────────────────┘
               │ 行为倾向
               ▼
┌─ 宪法 / drives / affect ─────────┐   不可训练的目标层
│  生存欲、边界、情绪-行为因果       │   只在代码与配置里
└──────────────────────────────────┘
```

> 这张图同时回答了「学生模型训练出来是干什么的」：
> **不是让它更聪明**（那是教师的事），而是把**不可训练的目标层**在权重里固化成可复现的行为倾向——
> 让情绪从「提示词装饰」变成真正的控制变量（计划三 §3.2），
> 并让「遇威胁 → 保全」的条件反射（= 生存本能）被真正训出来（计划三 §6.3）。
>
> **2026-11-06 晚补充**：这张图也回答了「自主性从哪来」——
> **只在学生这一层**。计划三初稿把 Bonsai 摆在主角位置，那是叙事没跟上：
> Bonsai 是**表达器官与判官**（不可训练），
> 自主性必须由我们训出来的学生承担。详见计划三 §10.0 与 §1.3。

---

## 8. 配置项（新增 `.env.example` 段）

```bash
# ── 微调 / 训练 ──────────────────────────────
FINETUNE_ENABLED=false
FINETUNE_PYTHON=/home/darkstar/anaconda3/envs/dsn-train/bin/python
FINETUNE_WORKDIR=.dsn/finetune
FINETUNE_LOG_DIR=logs/finetune
FINETUNE_BACKEND=hf_peft                 # hf_peft | unsloth | llama_cpp
FINETUNE_GPUS=all                        # all | 0 | 0,1
FINETUNE_MAX_CONCURRENT=1
FINETUNE_REQUIRE_HUMAN_PROMOTE=true
FINETUNE_LORA_RANK=16
FINETUNE_LORA_ALPHA=32
FINETUNE_SEQ_LEN=1024
FINETUNE_EPOCHS=3
FINETUNE_LR=2e-4
FINETUNE_HF_HOME=/home/darkstar/.cache/huggingface
HF_TOKEN=

# ── 学生模型（被训练对象，2026-11）─────────────
FINETUNE_STUDENT_MODEL=Qwen/Qwen3-8B            # 被训练对象：qwen3 家族，HF 格式
FINETUNE_STUDENT_MODEL_4B=Qwen/Qwen3-4B           # M0 冒烟档（已下载到 /home/darkstar/qwen_weights/HF/）
# 注意：**没有** -Instruct 后缀的仓库（404）；Bonsai-2 / JEV-27B-VL 永远不出现在这里。
FINETUNE_ENABLE_THINKING=false                # 训练期一律 false；推理期按需开
FINETUNE_CHAT_TEMPLATE=non-thinking           # 训练用短轨迹模板

# ── 教师 / 判官（远端 API，2026-11）────────────
FINETUNE_TEACHER_PROVIDER=openai_compatible   # 走 infra/orchestrator 已有的 API 通道
FINETUNE_TEACHER_MODEL=deepseek-v4-pro        # 非 Qwen 系思考链模型
FINETUNE_TEACHER_FALLBACK=local               # 远端不可用时降级到 Bonsai
FINETUNE_TEACHER_ALLOW_EXFIL=false            # 出网加工用户数据必须显式开启（§4.1）
FINETUNE_TEACHER_TEMPLATE_ADAPTER=1           # 转接模板：只做格式对齐
```

另在 `docs/configuration.md` 与 `docs/infra.md` 增补对应章节。

---

## 9. 测试计划

> **2026-11-06 落地情况**：初稿设想的是按模块拆 9 个测试文件；实际按**模块归属**
> 合并成 2 个框架层测试文件（进 GitHub）+ 1 个 apps 层测试文件（本地专用）。

| 文件 | 覆盖 | 归属 |
|---|---|---|
| `tests/test_infra_finetune.py`（529 行） | 契约与状态机、数据集格式层、GGUF 容错解析、环境体检契约、runner 提交/晋级/回滚、**不变式：import 后 `sys.modules` 里不能出现 torch** | 框架层 ✅ |
| `tests/test_harness_learning.py`（299 行） | 只收自己的轨迹、思维链剥离、目标层保护、出网开关、分层判官、晋级门槛与回滚 | 框架层 ✅ |
| `tests/test_harness_llamacpp.py`（改，+39 行） | `--lora` / `--lora-scaled`（冒号分隔）/ `--lora-init-without-apply` 命令行合成与反解析；默认 `None` 不破坏旧行为 | 框架层 ✅ |
| `tests/test_finetune_api.py`（本地专用） | HTTP 门面：读接口、缺参/未知字段/GGUF 拦截、**一次真训练**（提交 → 成功 → 日志 → 晋级 → 回滚） | apps 层 ⚠️ 不上 GitHub |

**与初稿的偏离**：初稿说「原则：不引入真训练」，但 M4 的门面测试**故意跑了一次真训练**
（4B / 2 步 / 约 1.3 秒 / 峰值 4289 MiB）——因为"能提交但跑不起来"是最难在纯桩测试里暴露的故障。
其余用例仍然不占显存。

---

## 10. 里程碑（两周，可与第三份计划并行）

| 阶段 | 交付 | 依赖 |
|---|---|---|
| **M0**（0.5 天） | 环境体检脚本 + `dsn-train` conda 环境装好 + 实测 2080Ti 上 4B QLoRA 能跑通 | 无 |
| **M0.1** ✓（已完成） | **学生模型前置**：`Qwen/Qwen3-4B` 已下载（7.6 G，落盘 `/home/darkstar/qwen_weights/HF/`）+ `dsn-train` 环境（torch 2.8.0+cu128 / transformers 5.20.2）已装 + 4B QLoRA 前向/反向跑通 | 已完成 |
| **M0.2** ✓（已结论） | **底座级后路摸底 → 结论：架构可训，但不做**。底座 `Qwen3.8-27B` 的 HF `model_type` 是 `qwen3_5`，transformers **5.20.2 有**该模块（4.57.6 没有）→ 架构上能训；但训底座既产不出 Bonsai/JEV 的能力，又与学生路线重复 → **本项目只走 `qwen3` 学生线** | 已完成 |
| **M1** ✓（已完成 2026-11-06） | `infra/finetune/` 9 个模块：base / env+probe / gguf / dataset / train_sft / runner / store + `tests/test_infra_finetune.py`（529 行）。**真机 4B QLoRA 冒烟跑通**（2 步 / 峰值 4289 MiB / 适配器已导出） | M0 |
| **M2** ✓（已完成 2026-11-06） | `llamacpp.py` 的 `--lora` / `--lora-scaled` / `--lora-init-without-apply` + `scheduler.py` 的 `DeviceGate`（独占租约 + 抢占让路）+ 编排器改动 + 单测 | M1 |
| **M3** ✓（已完成 2026-11-06） | `harness/learning/`：dataset_builder / teacher（边界）/ evaluator（分层判官）/ promotion + `tests/test_harness_learning.py`（299 行） | M1 |
| **M4** ✓（已完成 2026-11-06） | `apps/dsn_ui/finetune_api.py`（13 个端点）+ `apps/dsn_ui/FINETUNE_API.md` + SvelteKit「模型工坊」页签 + `tests/test_finetune_api.py`（10 用例，含一次真训练）。**全部是 apps/ 层，不上 GitHub** | M2, M3 |
| **M5**（2 天） | 端到端：造 200 条样本 → 8B 档 LoRA → 转 GGUF 适配器 → 挂载 → 评测 → 晋级/回滚 | M4 |
| **M5.1** ✓（2026-11-06） | **8B QLoRA 单卡跑通**：Qwen3-8B / 4bit nf4 / seq 512 / batch 1 / grad_accum 8 / 2 轮 → 38 步 / 126 秒 / loss 2.36 / 峰值 7.23GB。过程中定位并修掉三个显存坑（见 `docs/infra.md` §5.7） | M4 |
| **M5.2** ✓（2026-11-06） | **数据管线**：`local/m5/build_dataset.py` 从 dsn_ui 真实会话库构建数据集（噪声过滤 + 全局去重），产出 154 条样本 | M4 |
| **M5.3** ⚠️（卡在数据上） | **"200 条真实样本"达不到**——现有语料里真实对话只有约 130 条，其余全是测试夹具。详见 §6.4 | M5.2 |
| **M5.4** ✓（2026-11-06） | **挂载链路打通**：HF→GGUF（`convert_hf_to_gguf.py`，Q8_0 / 4.27GB）→ 适配器转 GGUF（`convert_lora_to_gguf.py`，288 张量 / 47MB）→ **框架生成的** llama-server 命令带 `--lora-scaled` → 服务实际加载适配器 → 出词正常 | M5.1 |
| **M5.5** ✓（2026-11-06） | **适配器行为变化可测**：同一提示词、temperature=0 —— 底座模型 thinking 跑满 200 token 仍没作答（content 为空、reasoning 200），挂适配器后**直接作答、reasoning 为空**。这正是"训练期不开 thinking"的纪律在产物上的体现 | M5.4 |
| **M5.6** ✓（2026-11-06） | **selfplay 自生成数据**（计划 §4.4）：`harness/learning/selfplay.py` 落地，3 情境 × 2 = 6 条全接受、无思维链、source 标记正确、可直接喂 DatasetBuilder | — |
| **M5.7** ✓（2026-11-06） | **远端 API 教师链路打通**：改写 / 打分 / 目标层拒绝 / 出网开关四项全过。过程中发现并修掉框架层一个真 bug：部分网关强制 SSE，`OpenAICompatClient.invoke` 会炸 | — |
| **M6**（2 天） | **14B 最终档**训练（长跑）+ 稳定性与耗时基线 | M5 |
| **M7**（1 天） | **教师链路接通**：远端 API 教师 + 转接模板 + 情感素材的共情引导 + 判官分层（规则优先、远端兜底、本地降级） | M1 |

**M0 的实测结果会直接改写 M6 的排期**，先做 M0。

---

## 11. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 2080Ti sm_75 与新 torch/cuda 不兼容 | 中 | 高 | **已实测**：torch 2.8.0+cu128 下 2 张 2080Ti 正常可见（cc 7.5，各 10820 MiB）；但 transformers 5.x 硬性要求 torch ≥ 2.6，torch 2.3.1 作废 |
| 27B 训练 OOM / 速度不可接受 | 中高 | 中 | **27B 现在不训**（教师/执行器）；学生走 4B/8B/14B 阶梯 |
| bitsandbytes 在 Turing 上有已知问题 | 中 | 中 | 退回 `torch.cuda` 4bit 或 fp16 LoRA + 梯度检查点 |
| ~~Bonsai fork 的 `llama-server` 不支持 `--lora`~~ | ~~中~~ **低** | 低 | **已复核：fork 支持 `--lora` / `--lora-scaled` / `--lora-init-without-apply`**（2026-11-06）。仍保留「PQ2_0 旋转基导致适配器未必能挂上」这一层不确定性 |
| 训练栈污染 base 环境 | 低 | 高 | 独立 conda env + CI 检查 base 环境依赖清单；DSN 主进程保持零 `import torch` |
| 自训练数据导致模型退化 | **高** | 高 | anchor set + 评测闸门 + 影子评估 + 可回滚（第三份计划 §3.7 详述） |
| **教师自蒸馏导致学生同质化/风格坍缩** | **高** | 中高 | 教师只给结论与评分、禁止训练 CoT 文本；混入 20-30% 通用语料与锚点样本；训练数据以 agent 自身轨迹为主 |
| **学生模型架构不被 transformers 支持**（`qwen3` 支持；`qwen3_5` 需要 transformers ≥ 5.x） | 中 | 高 | **已处置**：架构检查进了框架层（`FinetuneManager.submit()` 用 transformers 真加载配置），不支持就在**提交阶段**报错，不会浪费 GPU 作业 |
| **学生权重下载失败 / 磁盘不足** | 中 | 高 | 落盘 `/home`（剩 217 G，`/` 只剩 7.8 G）；`HF_HOME` 指到 `/home`；先下 4B 验证链路 |
| **用户数据出网未授权** | 中 | **高** | `FINETUNE_TEACHER_ALLOW_EXFIL` 默认关；白名单 + 脱敏 + 留痕；默认走本地教师 |
| **学生常驻卡与训练互斥** | 高 | 中 | 闸门支持排除卡 + 排队而非硬卸；学生常驻 GPU 0、训练走 GPU 1（计划三 §10.4） |

---

## 12. 与第三份计划的关系

本计划提供**能力**（能训练、能评测、能挂载、能回滚、能有教师与判官）；
[03-existence-app.md](03-existence-app.md) 提供**动机与策略**（为什么训练、训练什么、
训练完怎么影响行为）。两者通过 `harness/learning/` 这一层解耦：
第三份计划只调用 `dataset_builder` / `evaluator` / `promotion` / `infra.finetune.submit`，
不直接碰训练实现。

**教师接口的边界（2026-11 定）**：第三份计划可以请求教师做两件事——
① 对**已存在的 agent 轨迹**做重写/补全/评分；② 对**情感素材**给出共情引导。
它**不能**请求教师凭空生成「agent 应该怎么做」的行为样本，也不能让教师触碰
目标层（宪法 / drives / affect）。这条边界由 `harness/learning/evaluator.py` 与
`dataset_builder.py` 在代码里守住，而不是靠调用方自觉。
