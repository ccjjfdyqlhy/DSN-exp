# 模型共存管理器 — 设计文档

## 1. 问题

LMStudio 上同时加载多个大语言模型（gemma-3-4b、deepseek-ocr 等）导致显存不足：
- 主对话模型（gemma-3-4b）~4GB
- deepseek-ocr ~ 3GB
- 词向量嵌入模型 ~ 数百 MB
- TTS / ASR / 2md 小模型若干

实际使用中，这些模型**不会同时被请求**（对话时不需要 OCR，OCR 时不需要聊天），
但 LRU 策略应该允许一定的并发（例如 max_concurrent=2 时可同时保留对话模型 + OCR 模型）。

## 2. 目标

- 限制同时加载的**语言大模型**数量（词向量嵌入模型不计入限制）
- 请求到来时自动加载所需模型，必要时卸载最近最少使用的模型
- 被卸载模型的**待处理请求自动排队**，模型重新加载后继续执行
- 任务队列**完全排空后**自动卸载该模型（按 LRU 策略驱逐）

## 3. 架构

```
┌─────────────────────────────────────────────────────┐
│                   ModelScheduler                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ Slot 0       │  │ Slot 1       │  │ Slot 2      │ │
│  │ base_url=A   │  │ base_url=B   │  │ (spare)     │ │
│  │ model=None   │  │ model=None   │  │             │ │
│  │ queue→[]     │  │ queue→[]     │  │             │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐                   │
│  │ Model Registry│  │ LRU Tracker  │                   │
│  │ gemma → slot0 │  │ ocr: t=100   │                   │
│  │ ocr  → slot1  │  │ gemma: t=200 │                   │
│  └──────────────┘  └──────────────┘                   │
└─────────────────────────────────────────────────────┘

       ▲ submit(request)               ▲ swap if needed
       │                               │
┌──────┴──────┐              ┌─────────┴────────┐
│ ModelClient │              │  LMStudio API    │
│ (LMStudioChat,│───────────│  /v1/chat/...     │
│  OCRModel,   │   HTTP     │  /v1/models/load  │
│  ...)        │            │  /v1/models/unload│
└─────────────┘              └──────────────────┘
```

### 3.1 核心概念

- **插槽（Slot）**：一个 LMStudio 进程（由一个 `base_url` 标识）。每个 slot 同一时间只能加载一个模型。
- **模型注册（Model Registration）**：每个需要管理的模型必须注册到 scheduler，指定 `model_name`、`base_url`、`load_fn`、`unload_fn`。
- **任务队列（Task Queue）**：每个 slot 有一个队列（`asyncio.Queue` 或线程安全队列），存放等待该 slot 执行的请求。
- **LRU 追踪**：记录每个模型最近被使用的时间，驱逐时选择最久未使用的模型。

## 4. 配置项

```python
# config.py 新增
# ==================== 模型共存管理 ====================
# 同时加载的语言大模型最大数量（词向量嵌入模型不计入）
MAX_CONCURRENT_LM_MODELS = _env("MAX_CONCURRENT_LM_MODELS", "1")
# 模型加载超时（秒）
MODEL_LOAD_TIMEOUT = int(_env("MODEL_LOAD_TIMEOUT", "180"))
# 模型空闲自动卸载超时（秒，0=不自动卸载，由 LRU 驱逐）
MODEL_IDLE_UNLOAD_TIMEOUT = int(_env("MODEL_IDLE_UNLOAD_TIMEOUT", "0"))
# 任务队列最长等待时间（秒，超时返回错误）
MODEL_REQUEST_TIMEOUT = int(_env("MODEL_REQUEST_TIMEOUT", "300"))

# 各模型名称（已在 config 中的保持不变，只新增 slot 分配配置）
# LMSTUDIO_BASE_URL=http://localhost:4501        # 主对话模型 slot
# OCR_BASE_URL=http://localhost:4502              # OCR 模型 slot
```

如果两个模型共享同一个 base_url（同一进程），则必须共享同一个 slot。

## 5. 组件 API

### 5.1 ModelScheduler（单例）

```python
class ModelScheduler:
    """模型共存调度器。全局单例，所有模型请求通过它调度。"""

    def __init__(self, max_concurrent: int = 1):
        self.max_concurrent = max_concurrent
        self._lock = threading.RLock()
        self._slots: list[ModelSlot] = []
        self._model_registry: dict[str, ModelRegistration] = {}
        # {model_name: ModelRegistration}
        # ModelRegistration = {model_name, base_url, load_fn, unload_fn}

    def register(self, model_name: str, base_url: str,
                 load_fn: Callable, unload_fn: Callable) -> None:
        """注册一个模型到 scheduler。如果 base_url 对应的 slot 已存在则复用，否则创建。"""

    async def submit(self, model_name: str, request_fn: Callable,
                     timeout: float = 300) -> Any:
        """
        向指定模型提交一个请求。
        - 如果模型已在加载的 slot 中，直接入队执行
        - 如果未加载且有空闲 slot，加载后入队执行
        - 如果未加载且无空 slot，驱逐 LRU 模型，加载后入队执行
        - 如果被驱逐的模型队列中还有待处理请求，挂起队列
        """
```

### 5.2 ModelSlot

```python
class ModelSlot:
    """一个 LMStudio 实例槽位。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.current_model: str | None = None     # 当前加载的模型名
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def enqueue(self, request_fn: Callable) -> Any:
        """将请求加入队列并等待执行完毕。"""

    async def _worker(self):
        """后台 worker：依次取出队列中的请求，执行（当前模型已确保加载）。"""

    async def swap_to(self, model_name: str, load_fn: Callable) -> None:
        """切换当前 slot 加载的模型：卸载旧模型 → 加载新模型。"""
```

### 5.3 ModelClient 感知变更

现有模型客户端**只需要修改构造时的注册**和**调用处的包装**：

```python
# LMStudioChat 示例
class LMStudioChat:
    def __init__(self, ..., managed: bool = True):
        ...
        if managed:
            self._scheduler = ModelScheduler.get_instance()
            self._scheduler.register(
                model_name=self.model_name,
                base_url=self.base_url,
                load_fn=lambda: self._ensure_model_loaded(),
                unload_fn=lambda: _unload_lmstudio_model(self.base_url, self.model_name),
            )

    async def _call_and_append(self) -> str:
        if self._scheduler:
            return await self._scheduler.submit(
                model_name=self.model_name,
                request_fn=self._do_api_call,
            )
        return self._do_api_call()  # 传统路径（managed=False）
```

对于继承/使用 `LMStudioChat` 但需要不同模型名的地方（如 `OCRModel`），
只需在构造时传入正确的 `model_name` 和 `base_url`，并调用 `register`。

## 6. 调度策略细节

### 6.1 submit() 执行流程

```
submit(model="deepseek-ocr", request_fn=ocr_request)
│
├─ [已加载] model="deepseek-ocr" 在某个 slot 上
│   └─ 直接入队 → worker 择机执行
│
├─ [有空闲 slot]
│   └─ 切换 slot 加载 deepseek-ocr → 入队 → worker 执行
│
└─ [无空 slot]
    ├─ 找出 LRU 模型（refcount=0 的最久未用模型）
    ├─ 卸载 LRU 模型（其队列挂起）
    ├─ 在释放出的 slot 上加载 deepseek-ocr
    └─ 入队 → worker 执行
```

### 6.2 LRU 驱逐算法

1. 收集所有已加载模型（slot 上 current_model 非空）
2. 按 `last_used` 时间戳升序排列
3. 排除 refcount > 0（正在执行请求）的模型
4. 取第一个作为驱逐候选
5. 如果所有模型 refcount > 0（全部繁忙），阻塞等待直到至少一个空闲

### 6.3 队列挂起与恢复

- 当模型被驱逐时，其 slot 的队列保留所有未完成的请求
- 当同型号模型再次被加载时（可能在另一个 slot，也可能是原 slot），队列 worker 恢复执行
- 如果模型在另一个 slot 上加载，原 slot 的队列转移到新 slot

实现简化：始终以 `model_name` 为粒度管理队列，slot 只是执行单元。

```
Queue 层（model_name 维度）：
    gemma_queue: [req1, req2, ...]
    ocr_queue:   [req3, ...]

Slot 层（base_url 维度）：
    slot_0 (4501): current = gemma
    slot_1 (4502): current = ocr
    
当 gemma 被卸载时，gemma_queue 保留，slot_0.current = None。
当下一个 gemma 请求到来，scheduler 重新加载 gemma 到 slot_0 或其他空 slot。
```

### 6.4 请求超时

每个 submit() 可设置 timeout，超时后请求从队列移除，抛出 TimeoutError。

### 6.5 模型加载排队

如果所有 slot 都在使用中，且所有已加载模型都 busy（refcount > 0），
新 submit() 会阻塞等待直到某个模型空闲可被驱逐。

## 7. 启动时模型加载策略

### 7.1 开机预加载

DSN-exp 启动时，在 **ASR 模型初始化之前**（`boot.py` 启动流程早期阶段），
向 `LMSTUDIO_BASE_URL`（主对话模型端口）发送 `GET /v1/models` 查询当前已加载的模型列表：

```python
GET http://localhost:4501/v1/models
# 返回示例：
# {
#   "data": [
#     {"id": "google/gemma-3-4b", "object": "model"},
#     {"id": "text-embedding-model", "object": "model"},
#     {"id": "tts-model", "object": "model"}
#   ]
# }
```

对以下模型，检查是否已在列表中：
1. **主对话模型**（`LMSTUDIO_MODEL_NAME`，如 `google/gemma-3-4b`）
2. **词向量嵌入模型**（`MEMORY_EMBEDDING_MODEL`，如 `text-embedding-model`）
3. **TTS 处理模型**（`TTS_MODEL_NAME`，如 `tts-model`）

对于**缺失的模型**，立即发送 `POST /v1/models/load` 加载请求。
加载顺序：嵌入模型 → TTS 模型 → 主对话模型（嵌入模型最小，先加载可立即就绪）。

### 7.2 OCR 模型不预加载

**`deepseek-ocr` 永远不在启动时加载。** OCR 模型仅在以下时机按需加载：
- AI 调用 `document.process_scan` 工具时
- 通过 Scheduler 的 LRU 机制与其他模型竞争 slot

### 7.3 与 Scheduler 的关系

- 开机预加载是**一次性初始化**，不通过 Scheduler 的 submit/queue 路径
- 预加载完成后，模型直接进入 Scheduler 的 `_loaded` 字典，refcount=0（可被 LRU 驱逐）
- 后续运行时请求全部走 Scheduler 的 submit 路径
- `boot.py` 中的预加载代码在 Scheduler 初始化完成后执行

## 8. 配置建议（生产环境）

```
MAX_CONCURRENT_LM_MODELS=1     # 严格串行，显存最省
# 或
MAX_CONCURRENT_LM_MODELS=2     # 可同时保留对话模型 + OCR 模型

MODEL_LOAD_TIMEOUT=180          # 3 分钟加载超时
MODEL_REQUEST_TIMEOUT=300       # 5 分钟请求超时
```

## 9. 涉及文件

| 文件 | 改动 |
|------|------|
| `config.py` | 新增 `MAX_CONCURRENT_LM_MODELS`、`MODEL_LOAD_TIMEOUT`、`MODEL_REQUEST_TIMEOUT` |
| `models/model_scheduler.py` | **新文件**：ModelScheduler、ModelSlot、ModelRegistration |
| `models.py` | LMStudioChat._call_and_append、OCRModel._ocr_single 接入 scheduler；EmbeddingClient 不变 |
| `document/doc_processor.py` | 不需要额外改动（通过 OCRModel 间接接入） |
| `boot.py` | 启动流程早期（ASR 初始化前）增加预加载逻辑：检查 LMStudio `/v1/models` → 缺失则加载 |

## 10. 实现建议

### 阶段零：启动预加载

1. 在 `boot.py` 中，ASR 初始化之前插入预加载逻辑：
   - 构造 `requests.get(f"{LMSTUDIO_BASE_URL}/v1/models")` 查询当前加载列表
   - 对比配置中的模型名称，找出缺失的模型
   - 按嵌入→TTS→主对话顺序逐一调用 `_load_lmstudio_model` 加载
2. 加载成功后，将模型信息注册到 Scheduler（标记 refcount=0）
3. OCR 模型**不注册**（始终走 scheduler 按需加载）

### 阶段一：ModelScheduler 核心

1. 新建 `model_scheduler.py`：ModelScheduler（单例）、ModelSlot、ModelRegistration
2. 实现 register / submit 核心逻辑
3. 实现 LRU 驱逐和队列挂起/恢复
4. 实现异步 worker 循环

### 阶段二：接入现有客户端

1. LMStudioChat：构造时注册，send_message/_call_and_append 通过 scheduler.submit 执行
2. OCRModel：构造时注册，_ocr_single 通过 scheduler.submit 执行（注意 OCRModel 有自己的 base_url）
3. 处理同步/异步边界：submit 是 async，但现有代码可能使用同步调用（thread pool executor）

### 阶段三：测试与调优

1. 单 slot 情景测试：chat → ocr → chat（验证卸载与重加载）
2. 多 slot 情景测试：chat + ocr 同时可用
3. 压力测试：大量并发请求，验证队列正确性
4. 显存占用验证

## 11. 同步模型的处理策略

现有代码中，模型调用有同步和异步两种方式：

- **同步路径**：`LMStudioChat.send_message()` — 在 thread pool executor 中执行，阻塞等待 HTTP 响应
- **异步路径**：`OCRModel.ocr()` — 同样同步，但在 async 上下文中通过 `run_in_executor` 包装

ModelScheduler 的 `submit` 设计为 **async 方法**，内部使用 `asyncio.Event` 来同步等待队列结果：

```python
async def submit(self, model_name, request_fn, timeout=300):
    """async 方法，可被同步代码通过 run_in_executor 调用"""
    event = asyncio.Event()
    result_container = []

    async def _wrapper():
        try:
            result = await request_fn()  # 如果 request_fn 是同步的，用 run_in_executor
            result_container.append(result)
        except Exception as e:
            result_container.append(e)
        event.set()

    await self._enqueue(model_name, _wrapper)
    
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"模型 {model_name} 请求超时")
    
    if result_container and isinstance(result_container[0], Exception):
        raise result_container[0]
    return result_container[0] if result_container else None
```

同步调用方通过 `asyncio.run_coroutine_threadsafe` 或 `loop.run_until_complete` 调用 submit。
