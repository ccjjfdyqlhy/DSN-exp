# infra/ —— 基础设施层

> 读者：要改模型调度、资源管理、存储或策略的维护者。
> 这一层**不知道任何业务**：只管进程、HTTP、显存、磁盘、密钥。

---

## 一、orchestrator：四层结构，一层套一层

这是全层最复杂、也最容易改出事故的部分。真实骨架是**四个文件纵向串联**：

```
router.py         ModelOrchestrator   模型注册表 + 状态 + 对外 API
      │           决定「有哪些模型、现在什么状态」
      ▼
scheduler.py      ModelScheduler      插槽与驱逐
      │           决定「显存给谁用、谁先被踢」
      ▼
local_chat.py     OpenAICompatChat    本地引擎的 HTTP/SSE 客户端
      │           决定「怎么发请求、怎么读流」
      ▼
local_engine.py   LocalServerLauncher 子进程生命周期
                  决定「进程怎么起、怎么死、怎么确保不泄漏」
```

改任何一层之前，先确认问题到底属于哪一层。

### 1.1 契约层（`base.py`）

`IChatClient` 是上层唯一需要知道的接口：

```python
class IChatClient(Protocol):
    model: str
    def invoke(self, messages, tools=None, *, temperature, max_tokens, timeout) -> ChatResponse
    async def stream(self, messages, tools=None, ...) -> AsyncGenerator
```

`stream()` 的产出契约（`base.py:199`）：

| 产出 | 含义 |
|---|---|
| `str` | 文本增量 |
| `{"content": ...}` | 结构化文本增量 |
| `{"tool_calls": [{"index","id","name","arguments"}]}` | 工具调用（分片） |
| `{"usage": {...}}` | token 用量 |
| `{"timings": ...}` | llama-server 的计时信息 |
| `{"reasoning": ...}` / `{"reasoning_content": ...}` | 思考链增量 |

> ⚠️ docstring 只列了前四种，**后两种是实现里真实存在的**。
> 消费端请写成「未知键直接忽略」，不要 `assert` 键集合。

### 1.2 `ModelScheduler`：插槽与驱逐

单例，进程级唯一（`scheduler.py:94`）。核心字段 `ModelProfile`：

| 字段 | 含义 |
|---|---|
| `priority` | 数值越大越优先，默认 50 |
| `resident` | 常驻：永不被插槽压力卸载 |
| `immediate` | 即时回收：任务排空后立即卸载 |
| `orchestrated` | 是否受调度器管理（API 模型为 False） |
| `load_timeout` / `request_timeout` | 超时 |

**驱逐算法**（`scheduler.py:351`）：只选 `refcount == 0` 的空闲模型，
普通请求要求 `requester.priority > victim.priority`，`immediate` 可放宽。
排序键 `(是否有排队者, priority, last_used)`。

**单飞加载**（`scheduler.py:399`）：`_do_load` 用 `info.loading` 标志保证
同一模型只拉起一次。注释里记录了原始 bug：4 个并发 `use()` 曾拉起 4 个子进程导致 OOM。
**`load_fn` 必须在锁外执行**（`scheduler.py:432` 显式 release/acquire）——
这是维护高危区，改动前请先读懂那段锁管理。

### 1.3 `ModelOrchestrator`：注册表与状态机

`router.py`（1049 行，全 infra 最大文件）。四个注册入口：

| 方法 | 用途 | 备注 |
|---|---|---|
| `register_local_llamacpp(name, config, ...)` | 本地 GGUF | 完整调度语义 |
| `register_local_strata(name, config, ...)` | 自研引擎 | `request_timeout` 默认 600 |
| `register_api_lmstudio(name, base_url, ...)` | 本地 GUI 模型库 | 完整调度语义 |
| `register_api_openai(name, api_key, base_url, ...)` | 远程 API | **固定** `priority=10, resident=True, orchestrated=False`，**不进调度器** |

三个必须知道的行为：

1. **首次注册自动成为 default 模型**（`router.py:429` 等四处）。注册顺序影响默认值。
2. **构造时改写全局调度器插槽数**：`__init__` 里 `self._scheduler.max_concurrent = ...`（`router.py:101`）。
   因此 `get_instance()` 只有**首次**调用的参数生效。
3. **`status()` 带自愈**：本地引擎的 `launcher.is_running()` 为假时反向 `mark_unloaded`（`router.py:749`）。

> ⚠️ `load_model` / `unload_model` 必须与 `mark_preloaded` / `mark_unloaded` 成对出现，
> 任何绕过都会让 `status()` 永久错报。

### 1.4 各 provider 客户端

| 类 | 基类 | 特点 |
|---|---|---|
| `OpenAICompatChat` | `ChatClientAdapter` | 本地引擎通用基类，支持 scheduler + launcher 联动 |
| `LlamaCppChat` | `OpenAICompatChat` | 只改 label |
| `StrataChat` | `OpenAICompatChat` | 只改 label |
| `LMStudioChat` | `ChatClientAdapter` | **独立实现**，不走 local_chat |
| `OpenAICompatClient` | `ChatClientAdapter` | 远程，支持 `chat` 与 `responses` 双协议 |
| `AnthropicCompatClient` | `ChatClientAdapter` | system 抽成独立参数 |
| `FailoverChat` | `ChatClientAdapter` | 多端点故障转移 |
| `StubChatClient` / `StubEmbeddingClient` | — | 测试用，确定性输出 |

**`FailoverChat` 的流式语义**（`failover.py:193`）：未产出任何内容前失败 → 换端点重试；
**已开始输出后失败 → 直接上抛**（不能重放，否则用户会看到重复内容）。

**`OpenAICompatClient.invoke` 的 SSE 兜底**（`openai.py`）：有一批网关
（实测：`newapi.gay`）**无视 `stream=false`，直接返回 `text/event-stream`**。
openai SDK 这时交回来的是原始字符串而不是 Completion 对象，
不兜住就是 `'str' object has no attribute 'choices'`。
网关是别人的，改不了，只能自己兜：`invoke` 发现响应没有 `choices` 时，
自动改走流式请求再把增量拼成一次普通响应（工具调用也会按 index 拼回去）。
这条路径影响面不小——**教师链路**（`harness/learning/teacher.py`）走的正是 `invoke`，
远端教师一旦遇到这种网关就整条链断掉。

### 1.5 `LocalServerLauncher`：子进程的两个硬约束

**约束一：Popen 必须发生在指定线程上**（`local_engine.py:61` `_popen_on_launch_thread`）。
原因：`PR_SET_PDEATHSIG` 绑定的是**发起 fork 的那个线程**。如果在事件循环的
线程池里起进程，loop 关闭时模型会被误杀。这是踩过的坑，注释就在文件里。

**约束二：所有 launcher 登记进全局集合**（`local_engine.py:49` `_ACTIVE_LAUNCHERS`），
配合 `atexit` 与 `kill_process_tree`（`killpg(SIGTERM)` → 等 → `killpg(SIGKILL)`）
保证进程不会被漏掉。

子类只需覆写钩子：`build_command()` / `preflight()` / `child_env()` / `working_dir()`。
`create_scheduler_hooks()` 直接生成调度器要的 `(load_fn, unload_fn)` 对，
**两者都吞异常返回 False**（调度器契约要求如此，抛异常会让调度器死锁）。

---

## 二、resources：异构资源池

`ResourcePool` **直接继承 `ModelScheduler`**，因此天然获得优先级、插槽、常驻、
加载/卸载钩子等全部能力，零算法重复。

```python
pool.register_resource(name, spec, load_fn, unload_fn)

with pool.acquire("tts") as lease:
    url = lease.url          # 进程内资源为空串
    ...                      # 期间独占
# 退出即归还；release() 幂等
```

三种资源形态由三个启动器承载：

| 启动器 | 形态 | 说明 |
|---|---|---|
| `InProcessModelLauncher` | 进程内模型 | 无 HTTP 端点，`is_ready()` 语义是「对象存在」（如 FunASR） |
| `HTTPServiceLauncher`（adopt） | 既有 HTTP 服务 | **只探测、不拉起、不停进程** |
| `HTTPServiceLauncher`（托管） | 子进程 | 用 `start_command` 拉起 |
| `DockerServiceLauncher` | 容器 | 全程走 `docker` CLI，不复用 Popen 生命周期 |

> `ResourceKind` **只有 `ASR` 和 `TTS` 两个成员**（`pool.py:33`），注释明确写了
> 「不得凭空发明成员」。LLM 由 orchestrator 管，不走资源池。

---

## 三、policy：可插拔行为策略

每个策略都是「构造即配置、方法即决策、repr 即状态」的纯对象。

| 策略 | 文件 | 作用 |
|---|---|---|
| `ModelRouter` | `router.py` | 选档：手动覆盖 > 预算压力(≥0.8) > 廉价任务 > 高峰 > 默认 |
| `TokenMeter` | `token_meter.py` | 记账，缓存命中分账 |
| `TokenBudget` | `budget.py` | 预算与 `pressure()`，超限**只回调一次** |
| `DurationPredictor` | `predictor.py` | 耗时预测，死区学习 |
| `CacheWarmer` | `warmer.py` | 空闲保活前缀缓存 |
| `RetryPolicy` | `retry.py` | 重试 + 退避 + 限流 + 熔断 |

**两个使用陷阱：**

- `CacheWarmer.start()` 要求**当前已有运行中的事件循环**（内部 `asyncio.create_task`）；
  `stop()` 是协程，不能同步调用。
- `RetryPolicy.call_sync()` 内部 `asyncio.run()`，**在事件循环里调用会直接炸**。

> 这套「Token 经济闭环」目前是**设计完成、接入未完成**：`AgentSpec` 会接收
> `router` / `budget` 配置，但 `AgentLoop` 并没有真正调用它们。
> 见 [technical-debt.md](technical-debt.md#p1-1-token-经济闭环未接入)。

---

## 四、store / tasks / auth / gateway / observability

### store

| 类 | 作用 |
|---|---|
| `IStore` | 存储契约 |
| `SqliteStore` | 连接 + RLock + `busy_timeout=10s`；`execute()` 按 SQL 首词判断是否 SELECT，写操作自动 commit |
| `SessionStore` | 会话/消息/用量/压缩块/摘要，构造时自动跑迁移 |
| `MigrationRunner` | 版本化迁移 |

### tasks

`Task`（7 种状态，含 `MISSED` / `SKIPPED`）、`TaskExecutorRegistry`、
`TaskScheduler`（SQLite 持久化 + 重试）、`AsyncTaskStore`（TTL 缓存）。

### auth

`APIKeyManager`、`SessionManager`（HMAC-SHA256）、`TOTP`、`UserStore`（pbkdf2 200k）。

### gateway

`IGateway` 协议 + `FlaskGateway` 适配器。dsn_study 用它挂载 Blueprint。

### observability

`MetricsCollector`（计数/计时）、`UsageTracker`（用量与费用）。
`UsageRecord` / `fmt_tokens` 的**唯一实现**在 `policy/token_meter.py`，这里反向复用。

---


## 五、finetune：训练子系统（框架层）

> 本节只描述**框架层能力**（`infra/finetune/`）。具体实验应用、数据来源、
> 混沌演练等属于本地实验，不在本仓库。

### 5.1 边界：主进程永远不 import torch

仓库里 `infra/` `harness/` `apps/` **零 `import torch`**（唯一例外是
`apps/dsn/models/asr_engine.py:92` 用 `sys.modules.get("torch")` 做防御性检查）。
训练因此跑在**独立解释器 + 独立脚本**里：

```
DSN 主进程                    训练解释器（dsn-train 环境）
------------                  -------------------------
infra/finetune/runner.py  --写 spec.json-->  infra/finetune/train_sft.py
        |                                     （零仓库依赖，只 import torch/…）
        <--读 result.json / train.log---------
```

`infra/finetune/probe.py` 是**独立脚本**（不 import 仓库任何模块），
由 `infra/finetune/env.py` 用子进程调用来体检环境，主进程只拿到 JSON。
测试 `tests/test_infra_finetune.py` 里有一条不变式测试：
`import infra.finetune` 之后 `sys.modules` 里不能出现 `torch`。

### 5.2 模块分工

| 模块 | 职责 |
|---|---|
| `base.py` | **契约**：`JobState` / `TrainSpec` / `TrainJob` / 异常族；参数自检 |
| `env.py` | 解释器定位（`FINETUNE_PYTHON` → `~/anaconda3/envs/dsn-train/bin/python` → `sys.executable`）与体检 |
| `probe.py` | 独立探针脚本：torch/cuda/设备/bf16/依赖版本/SDPA 后端真探针 |
| `gguf.py` | GGUF 头部元数据读取（**容错私有量化类型**） |
| `dataset.py` | 数据集**格式层**：角色归一、结构校验、train/val 切分、写盘 |
| `train_sft.py` | 训练脚本（独立运行于训练解释器；QLoRA/LoRA/full 三种方法） |
| `runner.py` | `FinetuneManager`：提交 / 查询 / 晋级 / 回滚；排队与等卡 |
| `store.py` | 作业与槽位登记（SQLite，走 `infra/store` 的迁移机制） |

### 5.3 公开 API

```python
from infra.finetune import FinetuneManager, TrainSpec

mgr = FinetuneManager()
job = mgr.submit(TrainSpec(
    base_model="Qwen/Qwen3-4B",       # HF 权重，不能是 GGUF
    dataset_path="~/dsn-finetune/data/train.jsonl",
    output_dir="~/dsn-finetune/out/j1",
    method="qlora",                    # 单卡 11GB 的现实选择
))
mgr.status(job.id); mgr.list_jobs()
mgr.promote(job.id, slot="student")   # 候选 -> 生效
mgr.rollback("student")               # 生效 -> 上一个
```

训练作业复用仓库既有的通用任务系统（`infra/tasks`）：作业就是一个
`Task(type="finetune.train")`，由**单 worker** 的 `TaskExecutorRegistry` 执行
——训练在本机天然串行（同时跑两个 QLoRA 必 OOM）。

### 5.4 显存闸门（`DeviceGate`）

`DeviceGate` 在 `infra/orchestrator/scheduler.py` 里，**不新建** `device_pool.py`：
`infra/resources/pool.py` 的 `ResourceKind` 只有 ASR/TTS 且明确禁止凭空发明成员，
LLM 的显存由编排器管。

规则：

- `ModelProfile.llama_config` 里 `n_gpu_layers == -1`（全量分层）→ **独占所有卡**；
  部分分层不独占（它只吃一部分显存）。
- 模型加载成功 → `DeviceGate.claim()`；卸载 → `release_holder()`。
- 训练作业通过 `DeviceGate.acquire()` / `acquire_any()` 排队等卡，
  拿不到就在 `FINETUNE_DEVICE_TIMEOUT`（默认 3600s）后失败，**不硬抢**。

### 5.5 GGUF 容错读取

`infra/finetune/gguf.py` 自带只读头部的 GGUF 解析器，因为**上游 gguf-py 读不了
私有量化类型**：`general.file_type` 与张量类型是**两套独立编号**
（`LLAMA_FTYPE_*` vs `GGML_TYPE_*`），Bonsai-2 的 PQ2_0 用的张量类型 id 141/142
越过了上游 `GGML_TYPE_COUNT`（本地 llama.cpp 为 43），上游会抛
`ValueError: 142 is not a valid GGMLQuantizationType`。
本模块把未知 id 当作"私有类型"记录，并用 `upstream_compatible()` 给出结论——
**不用真的加载 7.2GB 权重就能判断上游能不能跑**。

### 5.6 纪律

- **训练期不开 thinking**：`TrainSpec.validate()` 直接拒绝 `enable_thinking=True`。
- **训练标签不含推理内容**：剥离在 `harness/learning/dataset_builder.py` 做。
- **教师只能改写/标注/打分**，不能定义行为、不能输出思维链标签、
  不能在未授权时把用户数据送出机器（见 `docs/harness.md` 的学习子系统一节）。


### 5.7 单卡 11GB 上的显存纪律（2026-11-06 实测）

2×RTX 2080Ti（各 11GB / sm_75）上跑 8B QLoRA，连踩三个坑才跑通。
这三条都写进了 `tests/test_infra_finetune.py` 的不变式测试，改回去会红。

| 坑 | 现象 | 规则 |
|---|---|---|
| `prepare_model_for_kbit_training` 把**所有** fp16 参数升 fp32 | `embed_tokens` 与 `lm_head` 各 1.24GB（词表 151936 × 隐层 4096），一起升 fp32 ＝ **一次多花 2.32GB**，11GB 卡直接 OOM | 用 `train_sft._prepare_for_qlora`：只升 **1 维**参数（LayerNorm/bias） |
| `use_cache=True` 让 transformers **拒绝启用梯度检查点** | 36 层激活全量留在显存里，实测多吃约 4GB | 训练期必须 `model.config.use_cache = False` |
| `device_map={"": g}` 只决定**权重**放哪 | HF Trainer 仍按 `args.device`（默认 `cuda:0`）放优化器状态与激活 → 「模型在物理 GPU 1、训练状态在物理 GPU 0」，而 DeviceGate 记的是「占了 GPU 1」 | 用 `CUDA_VISIBLE_DEVICES` 圈卡，且**必须在 `import torch` 之前**设置（transformers 的导入会触发 `torch.cuda.is_available()`，那一次就把 CUDA 运行时初始化了） |

实测结果（Qwen3-8B / 4bit nf4 / seq_len 512 / batch 1 / 单卡）：

```
加载后            5.67 GB
训练峰值          7.23 GB   ← 之前的实现会在这里 OOM
147 样本 × 2 轮   38 步 / 126 秒 / train_loss 2.36
```

另有一条：`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 已在
`infra/finetune/env.py` 的子进程环境里默认打开——11GB 卡上的碎片化能省下几百 MB。

## 六、`infra.models` 是兼容 shim（重要）

`infra/models/` 目录里**只有一个 `__init__.py`**，它把 `infra.orchestrator.*`
镜像进 `sys.modules["infra.models.*"]`（`models/__init__.py:8-20`）。

```python
# 这两个写法在运行时等价：
from infra.models.base import ChatMessage      # 历史写法
from infra.orchestrator.base import ChatMessage # 推荐写法
```

**新代码一律写 `infra.orchestrator.*`。** 理由：shim 依赖 `sys.modules` 投毒，
存在隐藏的导入顺序不变式；且它没有映射 `infra.models.router`，覆盖并不完整。

---

## 七、改这一层时的检查清单

- [ ] 是否引入了新的**进程级全局**？先看能不能通过构造参数注入。
- [ ] 涉及 `ModelScheduler` 的锁，是否保证 `load_fn` 在**锁外**执行？
- [ ] 起子进程是否走了 `_popen_on_launch_thread`？
- [ ] `IChatClient` 实现是否仍满足 `stream()` 的产出契约？
- [ ] 新增配置走 `Settings.namespace()` 还是环境变量？与既有惯例保持一致。
- [ ] 跑 `python -m pytest tests/test_harness_*.py tests/test_orchestrator.py tests/test_model_scheduler.py -q`。
