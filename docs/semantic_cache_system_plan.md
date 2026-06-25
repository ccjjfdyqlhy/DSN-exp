# DSN-exp 语义缓存系统 — 详细设计策划案

> 基于语义相似度，缓存 AI 对重复性用户需求的完整回复（文本 + 动作序列），减少无效算力消耗。
> 策划版本: v1.0

---

## 目录

1. [问题与目标](#1-问题与目标)
2. [总体架构](#2-总体架构)
3. [L1 静态语素层](#3-l1-静态语素层)
4. [L2 动作拓扑层](#4-l2-动作拓扑层)
5. [L3 实体槽位寄存器](#5-l3-实体槽位寄存器)
6. [双路仲裁器（硬分类 + 向量判别）](#6-双路仲裁器)
7. [动态状态指纹与多轮上下文校验](#7-动态状态指纹与多轮上下文校验)
8. [缓存置信度衰减与异步自愈](#8-缓存置信度衰减与异步自愈)
9. [缓存存储与索引](#9-缓存存储与索引)
10. [Pipeline 集成方案](#10-pipeline-集成方案)
11. [实施路线图](#11-实施路线图)
12. [与现有基础设施的关系](#12-与现有基础设施的关系)

---

## 1. 问题与目标

### 1.1 现状

用户频繁向 AI 发起重复性/相似性请求（如"扫描一下文件"、"帮我查天气"、"翻译这段文字"），但系统每次均执行完整管线：

```
用户消息 → PRE_FILTER → PRE_PROCESS → MODEL_INVOKE(LLM API) → POST_PROCESS → POST_TTS
                                                                     ↓
                                                             每次消耗 API 额度 + 算力
```

**典型重复场景：**
- 每日固定操作（早间播报、计划推送）
- 高频工具调用（扫描、打印、查天气、翻译）
- 标准流程应答（确认语、错误提示、任务完成通知）

### 1.2 目标

设计三层异构缓存池，对用户请求进行语义层面的匹配，命中时直接返回缓存结果：

```
用户消息 → 语义缓存仲裁器 ── 命中 ──→ 直接返回缓存（文本 + 音频 + 动作）
                          └── 未命中 ──→ 正常管线执行 → 结果写入缓存
```

预期收益：
- 重复请求 LLM API 调用减少 40-60%
- 平均响应延迟从秒级降至毫秒级
- TTS 音频复用，减少推理开销
- 动作序列复用，避免重复工具执行

---

## 2. 总体架构

### 2.1 系统分层

```
┌──────────────────────────────────────────────────────────────────┐
│                      语义缓存系统                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  L1 静态语素层    │  │  L2 动作拓扑层    │  │ L3 实体槽位   │   │
│  │  (无参短语缓存)   │  │  (DAG + 占位符)   │  │ (上下文KV)   │   │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘   │
│           │                     │                     │           │
│           └─────────────────────┼─────────────────────┘           │
│                                 │  模板即时编译 (JIT)              │
│                                 ▼                                 │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                   双路仲裁器                               │    │
│  │  ┌────────────────┐  ┌────────────────────────────────┐  │    │
│  │  │ 前置硬分类器    │  │  后置向量判别器                 │  │    │
│  │  │ TinyBERT       │──▶  Siamese + Slot-Forced Masking  │  │    │
│  │  │ <20M 参数       │  │  余弦距离 + 槽位强制掩码        │  │    │
│  │  └────────────────┘  └────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │             滑动窗口状态编码器                              │    │
│  │  GRU(3轮) → S_t(64维) + 槽位填充率 r → 复合指纹           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │             缓存置信度管理系统                              │    │
│  │  积分系统 C(0~1) + 用户行为观察窗口 + 异步自愈任务          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 与现有 Pipeline 的关系

```
用户消息
   │
   ▼
┌──────────────────────────────────────────────────┐
│  CacheInterceptorPlugin (新)                     │
│  ├─ 前置阶段: 在 PRE_FILTER 前拦截               │
│  │   - 生成复合缓存键                             │
│  │   - 查询 L1 → L2+L3 → L3 三级缓存             │
│  │   - 命中 → 短路管线，直接返回                   │
│  │   - 未命中 → 标记 ctx 继续执行                 │
│  │                                                │
│  └─ 后置阶段: 在 POST_TTS 后写入                   │
│      - 缓存 LLM 回复文本                          │
│      - 缓存 TTS 音频                              │
│      - 缓存动作序列（提取 <tool>/<task> 标签）     │
└──────────────────────────────────────────────────┘
   │
   ▼ (未命中时继续)
正常 Pipeline 执行
```

---

## 3. L1 静态语素层

### 3.1 定位

缓存"无实体依赖"的固定语用片段。这些短语不依赖任何用户上下文参数，完全静态。

### 3.2 缓存内容

| 类别 | 示例 | intent_id | speech_act_type |
|------|------|-----------|-----------------|
| 任务确认 | "好的，正在为您处理" | confirm | acknowledgement |
| 任务确认 | "收到，马上开始" | confirm | acknowledgement |
| 错误安抚 | "抱歉，出了点问题，请稍后再试" | error | apology |
| 错误安抚 | "当前服务不可用，请检查设置" | error | instruction |
| 任务结束 | "已完成，请查收" | complete | closure |
| 任务结束 | "任务已执行完毕" | complete | closure |
| 等待提示 | "正在处理中，请稍候" | waiting | progress |
| 拒绝提示 | "抱歉，我无法执行这个操作" | reject | explanation |

### 3.3 存储格式

```python
@dataclass
class L1Entry:
    intent_id: str                    # "confirm" / "error" / "complete" / "waiting" / "reject"
    speech_act_type: str              # "acknowledgement" / "apology" / "closure" / ...
    text: str                         # "好的，正在为您处理"
    tts_spectrogram: bytes            # TTS 频谱张量 (float32 序列化)
    duration_ms: int                  # 音频时长 (毫秒)
    created_at: datetime
    hit_count: int = 0
```

### 3.4 索引

```sql
-- L1 缓存表
CREATE TABLE IF NOT EXISTS cache_l1 (
    intent_id       TEXT NOT NULL,
    speech_act_type TEXT NOT NULL,
    text            TEXT NOT NULL,
    tts_blob        BLOB,                    -- TTS 频谱张量
    duration_ms     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count       INTEGER DEFAULT 0,
    PRIMARY KEY (intent_id, speech_act_type)
);
```

### 3.5 命中逻辑

```python
def lookup_l1(intent_id: str, speech_act_type: str) -> Optional[L1Entry]:
    """精确匹配 intent_id + speech_act_type，直接返回"""
    return db.execute(
        "SELECT * FROM cache_l1 WHERE intent_id=? AND speech_act_type=?",
        (intent_id, speech_act_type),
    )
```

命中率 100%（精确匹配），无需向量检索，延迟 < 1ms。

---

## 4. L2 动作拓扑层

### 4.1 定位

缓存"可执行有向无环图（Executable DAG）"，描述完成某类请求需要执行的操作序列，不缓存具体 API 载荷。

### 4.2 DAG 定义

```python
@dataclass
class ActionNode:
    node_id: str                        # 唯一标识
    operation: str                      # 原子操作名: "auth" / "scan" / "convert_format" / "read_sensor" / ...
    params: dict[str, str]              # 参数映射: {"file": "{{file_path: Path}}"}
    timeout_sec: int = 30
    retry_count: int = 0

@dataclass
class ActionEdge:
    source: str                         # 源节点 ID
    target: str                         # 目标节点 ID
    data_flow: list[str]                # 流转的数据字段: ["file_path", "mime_type"]

@dataclass
class L2Entry:
    intent_id: str
    action_signature: str               # 操作序列的梅克尔哈希
    dag: ActionGraph                    # ActionGraph {nodes: list[ActionNode], edges: list[ActionEdge]}
    created_at: datetime
    model_version: str
    hit_count: int = 0
```

### 4.3 强类型占位符

叶子节点所有参数必须定义为强类型占位符：

| 占位符 | 类型 | 示例值 |
|--------|------|--------|
| `{{file_path: Path}}` | `pathlib.Path` | `/tmp/scan_001.png` |
| `{{recipient_email: Email}}` | `str` (email 格式) | `user@example.com` |
| `{{target_format: str}}` | `str` (枚举) | `"pdf"` |
| `{{query_keyword: str}}` | `str` | `"天气预报"` |
| `{{sensor_id: int}}` | `int` | `0` |
| `{{duration_sec: int}}` | `int` | `30` |

### 4.4 动作签名（梅克尔哈希）

```python
def compute_action_signature(operations: list[str]) -> str:
    """对操作序列生成梅克尔哈希作为缓存键"""
    hashes = [hashlib.sha256(op.encode()).hexdigest() for op in sorted(operations)]
    # 构建梅克尔树
    while len(hashes) > 1:
        pairs = zip(hashes[::2], hashes[1::2])
        hashes = [hashlib.sha256((a + b).encode()).hexdigest() for a, b in pairs]
    return hashes[0]
```

这保证：相同的操作序列 → 相同签名 → 相同缓存条目。操作顺序变化 → 不同签名 → 新缓存。

### 4.5 存储

```sql
-- L2 缓存表: DAG 定义
CREATE TABLE IF NOT EXISTS cache_l2_dags (
    action_signature TEXT PRIMARY KEY,
    intent_id        TEXT NOT NULL,
    dag_json         TEXT NOT NULL,          -- ActionGraph 序列化
    model_version    TEXT DEFAULT '',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count        INTEGER DEFAULT 0,
    last_hit_at      TIMESTAMP
);

-- L2 缓存表: DAG 执行结果 (具体参数填充后)
CREATE TABLE IF NOT EXISTS cache_l2_results (
    result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    action_signature TEXT NOT NULL,
    slot_hash        TEXT NOT NULL,          -- 占位符填充值的哈希
    result_text      TEXT NOT NULL,          -- 执行结果文本
    tts_blob         BLOB,                  -- TTS 音频
    executed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms      INTEGER DEFAULT 0,
    FOREIGN KEY (action_signature) REFERENCES cache_l2_dags(action_signature)
);
```

---

## 5. L3 实体槽位寄存器

### 5.1 定位

独立于 L2 存储"当前上下文中的实体键值对"。当 L2 命中时，执行 JIT 编译将占位符替换为 L3 当前值。

### 5.2 数据结构

```python
@dataclass
class SlotEntry:
    slot_name: str                    # "file_path"
    slot_type: str                    # "Path"
    value: Any                        # /tmp/scan_001.png
    confidence: float = 1.0
    source: str = "extracted"         # "extracted" / "inferred" / "user_provided"
    expires_at: Optional[datetime] = None
```

### 5.3 存储

```sql
-- L3 实体槽位表（当前上下文，强时效性）
CREATE TABLE IF NOT EXISTS cache_l3_slots (
    slot_name      TEXT NOT NULL,
    slot_type      TEXT NOT NULL,
    value_json     TEXT NOT NULL,           # JSON 序列化
    confidence     REAL DEFAULT 1.0,
    source         TEXT DEFAULT 'extracted',
    session_id     TEXT,                    # 关联对话会话
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP,
    PRIMARY KEY (session_id, slot_name)
);

-- 定时清理过期槽位
CREATE INDEX idx_l3_expires ON cache_l3_slots(expires_at);
```

### 5.4 类型匹配规则

```python
TYPE_CHECK_MAP = {
    "Path":       lambda v: isinstance(v, (str, pathlib.Path)),
    "Email":      lambda v: isinstance(v, str) and re.match(r"[^@]+@[^@]+\.[^@]+", v),
    "URL":        lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
    "int":        lambda v: isinstance(v, int) or (isinstance(v, str) and v.isdigit()),
    "float":      lambda v: isinstance(v, (int, float)),
    "str":        lambda v: isinstance(v, str),
    "list[str]":  lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
}
```

### 5.5 JIT 编译流程

```python
def jit_compile(dag: ActionGraph, slots: dict[str, Any]) -> ExecutablePlan:
    """
    将 L2 DAG 中的占位符替换为 L3 当前实体。
    
    步骤:
    1. 遍历所有 ActionNode.params
    2. 对每个 {{name: Type}} 占位符:
       a. 在 slots 中查找 name
       b. TYPE_CHECK_MAP[Type](value) 类型检查
       c. 通过 → 替换为实际值
       d. 不通过 → 触发异常回落 (Fallback)
    3. 返回可执行计划
    """
    for node in dag.nodes:
        for key, placeholder in node.params.items():
            match = re.match(r"\{\{(\w+):\s*(\w+)\}\}", placeholder)
            if match:
                name, typ = match.groups()
                if name not in slots:
                    raise FallbackException(f"缺失必填槽位: {name}")
                if not TYPE_CHECK_MAP.get(typ, lambda _: False)(slots[name]):
                    raise FallbackException(
                        f"类型不匹配: {name} 期望 {typ}, 实际 {type(slots[name]).__name__}"
                    )
                node.params[key] = slots[name]
    return ExecutablePlan(nodes=dag.nodes, edges=dag.edges)
```

---

## 6. 双路仲裁器

### 6.1 定位

废弃单一余弦相似度阈值，升级为"硬分类前置 + 加权距离后置"。

### 6.2 前置硬分类器

```python
@dataclass
class HardClassification:
    intent_class: str                 # "scan_document" / "check_weather" / "translate_text" / ...
    modality: str                     # "ACTION" / "INFO"
    required_slot_schema: list[str]   # ["file_path"] / ["city", "date"] / ...
    confidence: float

class HardClassifier:
    """
    部署蒸馏式 TinyBERT (<20M 参数)，将用户查询映射为三要素标签。
    
    输入: 用户原始查询文本
    输出: <Intent_Class, Modality, Required_Slot_Schema>
    
    分库隔离: 当前查询的 Intent_Class 与历史缓存不一致时，
             直接拦截，不进入向量空间检索。
    """
    
    MODEL_PATH = "models/tinybert_intent_distilled"  # 蒸馏模型路径
    MAX_SEQ_LEN = 64
    INTENT_CLASSES = [
        "scan_document", "check_weather", "translate_text",
        "set_reminder", "compose_exam", "print_file",
        "search_web", "play_music", "send_email",
        "check_schedule", "read_document", "unknown",
    ]
    
    def classify(self, query: str) -> HardClassification:
        # TinyBERT 推理
        encoded = self._tokenizer(query, truncation=True, max_length=self.MAX_SEQ_LEN)
        outputs = self._model(**encoded)
        intent_id = outputs.logits.argmax().item()
        return HardClassification(
            intent_class=self.INTENT_CLASSES[intent_id],
            modality="ACTION" if intent_id in ACTION_CLASSES else "INFO",
            required_slot_schema=self._get_slot_schema(intent_id),
            confidence=outputs.logits.softmax(-1).max().item(),
        )
```

### 6.3 后置向量判别器

```python
class SiameseDiscriminator:
    """
    在同 Intent_Class 分库内计算向量余弦距离。
    
    使用已有 EmbeddingClient (768 维向量，LMStudio 嵌入模型)。
    
    关键改进: 槽位强制掩码 (Slot-Forced Masking)
    - 对包含关键实体词（文件名、日期、金额）的 Token 嵌入维度进行加权惩罚
    - Penalty Factor = 2.0
    """
    
    def compute_distance(
        self,
        query_embedding: list[float],
        cached_embedding: list[float],
        query_entities: list[tuple[int, int]],    # [(start, end), ...] 实体位置
        alpha: float = 0.45,
    ) -> tuple[float, bool]:
        """
        返回: (加权距离, 是否命中)
        
        步骤:
        1. 将 query_embedding 和 cached_embedding 转为 numpy array
        2. 对实体位置的维度施加 Penalty Factor=2.0
        3. 计算加权余弦距离
        4. 距离 < alpha → 候选命中
        5. 检查 Required_Slot_Schema 中的非空必填项是否齐全
           - 缺项 → 强制 Cache Miss
        """
        q = np.array(query_embedding)
        c = np.array(cached_embedding)
        
        # 槽位强制掩码
        mask = np.ones_like(q)
        for start, end in query_entities:
            mask[start:end] *= 2.0  # 惩罚因子
        
        weighted_q = q * mask
        weighted_c = c * mask
        
        cos_sim = np.dot(weighted_q, weighted_c) / (
            np.linalg.norm(weighted_q) * np.linalg.norm(weighted_c) + 1e-8
        )
        distance = 1.0 - cos_sim
        
        return distance, distance < alpha
```

### 6.4 双路仲裁流程

```
用户查询
   │
   ▼
┌─────────────────────────────┐
│ 1. 前置硬分类器 (TinyBERT)  │
│    → Intent_Class           │
│    → Modality               │
│    → Required_Slot_Schema   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 2. Intent_Class 分库隔离     │◀── 与历史缓存中所有 Intent_Class 比对
│                              │
│    匹配吗？                  │
│    ├─ 否 → Cache Miss (不检索)
│    └─ 是 → 进入该分库         │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 3. 后置向量判别器            │
│    → 余弦距离 (Slot-Forced)  │
│    → 距离 < α?               │
│                              │
│    匹配吗？                  │
│    ├─ 否 → Cache Miss        │
│    └─ 是 → 候选命中           │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 4. 槽位完整性检查            │
│    → Required_Slot_Schema   │
│      中的非空必填项是否存在   │
│                              │
│    齐全吗？                  │
│    ├─ 否 → 强制 Cache Miss   │
│    └─ 是 → Cache Hit         │
└─────────────────────────────┘
```

---

## 7. 动态状态指纹与多轮上下文校验

### 7.1 定位

解决多轮对话中上下文突变导致的缓存误用。

### 7.2 滑动窗口状态编码器

```python
class SlidingWindowStateEncoder:
    """
    将最近 K=3 轮对话 (User + Assistant 对) 编码为 64 维状态向量。
    
    架构:
    - 小型 GRU 网络 (参数冻结)
    - 输入: K 轮对话的嵌入向量 (每轮取 EmbeddingClient 编码)
    - 输出: 64 维浮点状态向量 S_t
    - 附加: 当前轮次槽位填充率 r (0~1)
    """
    
    GRU_HIDDEN_SIZE = 64
    WINDOW_SIZE = 3  # K=3
    
    def __init__(self, embedding_client: EmbeddingClient):
        self._embedder = embedding_client
        self._gru = self._build_gru()  # 参数冻结的小型 GRU
    
    def encode_state(
        self, recent_turns: list[tuple[str, str]]
    ) -> tuple[np.ndarray, float]:
        """
        输入: [(user_msg, assistant_reply), ...] 最近 K 轮
        输出: (S_t: 64维向量, r: 槽位填充率)
        """
        # 编码每轮对话
        turn_vectors = []
        for user_msg, assistant_reply in recent_turns[-self.WINDOW_SIZE:]:
            combined = f"用户: {user_msg} | AI: {assistant_reply}"
            vec = self._embedder.embed(combined)
            if vec:
                turn_vectors.append(vec)
        
        # GRU 编码
        if not turn_vectors:
            return np.zeros(self.GRU_HIDDEN_SIZE), 0.0
        
        state = self._gru(np.array([turn_vectors]))  # [1, K, 768] → [1, 64]
        
        # 槽位填充率
        slot_fill_rate = self._compute_slot_fill_rate(recent_turns)
        
        return state[0], slot_fill_rate
```

### 7.3 复合缓存键

```python
def build_composite_key(
    intent_id: str,
    state_vector: np.ndarray,
    task_phase: str,
) -> str:
    """
    复合缓存键结构:
    Composite_Key = {Intent_ID} | {S_t 二进制汉明编码前 16 位} | {任务阶段标志位}
    
    示例: "scan_document_1011001100110011_initial"
    """
    # 将 64 维向量转为 64 位二进制 (取符号位)
    binary_bits = (state_vector > 0).astype(int)
    hamming_code = "".join(str(b) for b in binary_bits[:16])  # 前 16 位
    
    return f"{intent_id}_{hamming_code}_{task_phase}"
```

### 7.4 严格匹配逻辑

```python
def check_context_match(
    cached_state: np.ndarray,
    current_state: np.ndarray,
    cached_fill_rate: float,
    current_fill_rate: float,
    dialog_turns: int,
) -> tuple[bool, str]:
    """
    双条件判定:
    
    条件 A: 汉明距离 < 动态阈值 β
      - β 随对话轮次增加而线性放宽
      - β = 4 + dialog_turns * 0.5, 上限 12
    
    条件 B: 槽位填充率波动 ≤ ±0.15
    
    返回: (是否匹配, 降级模式)
    """
    # 条件 A: 汉明距离
    base_threshold = 4
    beta = min(base_threshold + dialog_turns * 0.5, 12.0)
    
    hamming_dist = np.sum(
        (cached_state > 0).astype(int) != (current_state > 0).astype(int)
    )
    
    state_matched = hamming_dist < beta
    
    # 条件 B: 槽位填充率
    rate_matched = abs(current_fill_rate - cached_fill_rate) <= 0.15
    
    if state_matched and rate_matched:
        return True, "full"          # 全缓存模式
    
    if not state_matched:
        # 结构性偏移 → 降级为半缓存: 仅复用 L1
        return False, "l1_only"
    
    # 槽位填充率变化大 → 降级为半缓存
    return False, "param_recompute"
```

---

## 8. 缓存置信度衰减与异步自愈

### 8.1 积分系统

```python
class CacheScoreManager:
    """
    每个缓存条目给予初始置信度积分 C = 1.0。
    
    命名后进入"用户行为观察窗口" (T+30 秒):
    - 正反馈 → C = min(C + 0.05, 1.0)
    - 负反馈 → C = C * 0.8
    """
    
    INITIAL_SCORE = 1.0
    POSITIVE_INCREMENT = 0.05
    NEGATIVE_DECAY = 0.8
    OBSERVER_WINDOW_SEC = 30
    RED_THRESHOLD = 0.4
    HEAL_RESET_SCORE = 0.6
    OVERWRITE_RESET_SCORE = 0.8
    
    NEGATIVE_SIGNALS = [
        "停止", "重新生成", "不对", "不是这样",
        "stop", "regenerate", "wrong", "not this",
        "重新", "算了", "换一个",
    ]
    
    def feed_positive(self, cache_key: str) -> None:
        """用户无负反馈且继续下达指令 → 奖励"""
        current = self._get_score(cache_key)
        new_score = min(current + self.POSITIVE_INCREMENT, 1.0)
        self._update_score(cache_key, new_score)
    
    def feed_negative(self, cache_key: str) -> None:
        """用户发出纠偏信号 → 惩罚"""
        current = self._get_score(cache_key)
        new_score = current * self.NEGATIVE_DECAY
        self._update_score(cache_key, new_score)
    
    def check_negative_signal(self, user_message: str) -> bool:
        """检测用户消息是否为纠偏信号"""
        msg_lower = user_message.lower().strip()
        return any(signal in msg_lower for signal in self.NEGATIVE_SIGNALS)
```

### 8.2 观察窗口机制

```python
class ObserverWindow:
    """
    缓存命中后，开启 T+30s 观察窗口。
    
    通过监听 ChatPipeline 的后续用户消息来判断反馈类型。
    """
    
    def __init__(self, cache_key: str, user_id: int, score_manager: CacheScoreManager):
        self.cache_key = cache_key
        self.user_id = user_id
        self.score_mgr = score_manager
        self.window_end = time.time() + 30
        self.feedback_received = False
    
    def observe(self, user_message: str) -> None:
        if time.time() > self.window_end:
            # 窗口结束，无负反馈 → 正反馈
            if not self.feedback_received:
                self.score_mgr.feed_positive(self.cache_key)
            return
        
        if self.score_mgr.check_negative_signal(user_message):
            self.feedback_received = True
            self.score_mgr.feed_negative(self.cache_key)
```

### 8.3 异步自愈任务

```python
class AsynchronousHealingJob:
    """
    当缓存条目 C < 0.4 时触发。
    
    流程:
    1. 将原始请求重新发送至当前最新版 LLM
    2. 获取新回复 (文本 + 动作序列)
    3. 调用 Critique Model 进行结构化差异比对
    4. 根据差异类型决定处理方式
    """
    
    def heal(self, cache_entry: CacheEntry) -> None:
        if cache_entry.score >= 0.4:
            return  # 未达红色阈值
        
        # 1. 发送至当前生产环境 LLM
        new_response = self._llm.invoke(cache_entry.original_query)
        
        # 2. 结构化差异比对
        diff_report = self._critique_model.compare(
            old_text=cache_entry.response_text,
            new_text=new_response.text,
            old_actions=cache_entry.action_sequence,
            new_actions=new_response.actions,
        )
        
        if diff_report.only_wording_changed:
            # 仅措辞差异 → 保留原缓存，重置 C=0.6
            self._update_score(cache_entry.key, 0.6)
            self._logger.info("缓存 %s: 仅措辞差异，保留原缓存 C=0.6", cache_entry.key)
        
        elif diff_report.core_logic_changed:
            # 核心逻辑差异 → 原子性覆盖
            self._atomic_overwrite(cache_entry.key, new_response)
            self._update_score(cache_entry.key, 0.8)
            self._update_model_version(cache_entry.key, CURRENT_MODEL_VERSION)
            self._logger.info("缓存 %s: 核心逻辑变更，已原子覆盖 C=0.8", cache_entry.key)
```

### 8.4 裁判模型 (Critique Model)

```python
class CritiqueModel:
    """
    对比新旧响应的结构化差异。
    
    使用轻量级 LLM 或规则引擎判断差异类型。
    """
    
    def compare(
        self,
        old_text: str,
        new_text: str,
        old_actions: list[dict],
        new_actions: list[dict],
    ) -> DiffReport:
        """
        返回差异报告:
        - only_wording_changed: True/False
        - core_logic_changed: True/False
        - diff_details: str
        """
        # 规则 1: 动作序列不同 → 核心逻辑变更
        if old_actions != new_actions:
            return DiffReport(
                only_wording_changed=False,
                core_logic_changed=True,
                diff_details="动作序列不同",
            )
        
        # 规则 2: 语义相似度 > 0.85 (使用 EmbeddingClient)
        old_emb = self._embedder.embed(old_text)
        new_emb = self._embedder.embed(new_text)
        if old_emb and new_emb:
            similarity = cosine_similarity(old_emb, new_emb)
            if similarity > 0.85:
                return DiffReport(
                    only_wording_changed=True,
                    core_logic_changed=False,
                    diff_details=f"语义相似度 {similarity:.3f}",
                )
        
        # 规则 3: 混合判断
        return DiffReport(
            only_wording_changed=False,
            core_logic_changed=True,
            diff_details="文本和/或动作存在差异",
        )
```

---

## 9. 缓存存储与索引

### 9.1 存储架构

```
┌──────────────────────────────────────────────────┐
│                    SQLite DB                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ cache_l1 │  │cache_l2_ │  │cache_l3_ │        │
│  │          │  │dags/res  │  │slots     │        │
│  └──────────┘  └──────────┘  └──────────┘        │
├──────────────────────────────────────────────────┤
│                  文件系统                           │
│  cache_tts/                                       │
│  ├── l1/{intent_id}_{act_type}.wav                │
│  ├── l2/{action_signature}_{slot_hash}.wav         │
│  └── l2/{action_signature}_{slot_hash}.json        │
├──────────────────────────────────────────────────┤
│                   向量索引                           │
│  cache_vectors/                                   │
│  ├── index.faiss (FAISS IVF 索引)                  │
│  └── index.mapping (向量 ID → 缓存键 映射)         │
└──────────────────────────────────────────────────┘
```

### 9.2 向量搜索

复用现有 `EmbeddingClient` 基础设施：

```python
class VectorCacheIndex:
    """
    基于 FAISS 的向量索引，用于 L2 候选检索。
    
    使用 IVF (Inverted File) 索引，支持 768 维向量。
    """
    
    def __init__(self, dims: int = 768, index_path: str = "cache_vectors/"):
        self._dims = dims
        self._index_path = pathlib.Path(index_path)
        self._index = faiss.IndexIVFFlat(
            faiss.IndexFlatL2(dims), dims, 100  # 100 聚类中心
        )
        self._mapping: dict[int, str] = {}  # vector_id → cache_key
    
    def search(
        self, query_vector: list[float], top_k: int = 5
    ) -> list[tuple[str, float]]:
        """搜索最相似的 top_k 个缓存条目"""
        q = np.array([query_vector])
        distances, indices = self._index.search(q, top_k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx in self._mapping:
                results.append((self._mapping[idx], float(dist)))
        return results
```

### 9.3 TTS 音频文件存储

```python
TTS_CACHE_DIR = pathlib.Path("cache_tts")

class TtsCacheManager:
    """
    TTS 音频缓存管理。
    
    L1 文件: cache_tts/l1/{intent_id}_{act_type}.wav
    L2 文件: cache_tts/l2/{action_signature}_{slot_hash}.wav
    """
    
    def get_l1_path(self, intent_id: str, act_type: str) -> pathlib.Path:
        return TTS_CACHE_DIR / "l1" / f"{intent_id}_{act_type}.wav"
    
    def get_l2_path(self, action_signature: str, slot_hash: str) -> pathlib.Path:
        return TTS_CACHE_DIR / "l2" / f"{action_signature}_{slot_hash}.wav"
    
    def cache_tts(self, text: str, audio_bytes: bytes, level: str, **tags) -> None:
        """
        缓存 TTS 音频。
        - level="l1": tags={intent_id, act_type}
        - level="l2": tags={action_signature, slot_hash}
        """
        if level == "l1":
            path = self.get_l1_path(tags["intent_id"], tags["act_type"])
        else:
            path = self.get_l2_path(tags["action_signature"], tags["slot_hash"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
```

---

## 10. Pipeline 集成方案

### 10.1 CacheInterceptorPlugin

```python
class CacheInterceptorPlugin(Plugin):
    """
    语义缓存拦截插件。
    
    前置: 在 PRE_FILTER 之前拦截请求（priority 在 PRE_FILTER 之前）
    后置: 在 POST_TTS 之后写入结果（priority 在 POST_TTS 之后）
    
    Hook: PRE_FILTER (优先级 0, 最先执行)
          POST_TTS (优先级 100, 最后执行)
    """
    
    name = "cache_interceptor"
    description = "语义缓存：拦截重复请求，缓存回复"
    hooks = [HookPoint.PRE_FILTER, HookPoint.POST_TTS]
    priority_pre = 0    # PRE_FILTER 中最高优先级 (最先执行)
    priority_post = 100  # POST_TTS 中最低优先级 (最后执行)
    
    def __init__(self):
        self._embedder = EmbeddingClient()
        self._hard_classifier = HardClassifier()
        self._siamese = SiameseDiscriminator()
        self._state_encoder = SlidingWindowStateEncoder(self._embedder)
        self._score_mgr = CacheScoreManager()
        self._observer_windows: dict[str, ObserverWindow] = {}
        self._vector_index = VectorCacheIndex()
    
    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_FILTER:
            return self._try_serve_from_cache(ctx)
        elif hook == HookPoint.POST_TTS:
            return self._write_to_cache(ctx)
        return ctx
    
    def _try_serve_from_cache(self, ctx: PluginContext) -> PluginContext:
        """尝试从缓存回复"""
        
        # 1. 硬分类
        classification = self._hard_classifier.classify(ctx.message)
        ctx.extra["cache_intent"] = classification.intent_class
        
        # 2. 查询复合缓存键
        state, fill_rate = self._state_encoder.encode_state(
            ctx.extra.get("recent_turns", [])
        )
        composite_key = build_composite_key(
            classification.intent_class, state, ctx.extra.get("task_phase", "initial")
        )
        ctx.extra["cache_composite_key"] = composite_key
        
        # 3. 尝试 L1 (静态语素)
        l1_entry = self._query_l1(classification.intent_class)
        if l1_entry and self._is_pure_speech_act(ctx.message):
            # 纯语用请求 → L1 命中
            ctx.reply = l1_entry.text
            ctx.extra["cache_hit"] = "l1"
            ctx.extra["cache_tts"] = l1_entry.tts_spectrogram
            ctx.filtered = True  # 短路管线
            return ctx
        
        # 4. 尝试 L2 + L3 (动作拓扑)
        #   a. 向量搜索候选
        query_vec = self._embedder.embed(ctx.message)
        if query_vec:
            candidates = self._vector_index.search(query_vec, top_k=3)
            for cache_key, distance in candidates:
                #   b. 上下文匹配
                cached_state, cached_fill_rate = self._get_cached_state(cache_key)
                matched, degrade_mode = check_context_match(
                    cached_state, state, cached_fill_rate, fill_rate,
                    len(ctx.extra.get("recent_turns", [])),
                )
                if matched:
                    #   c. JIT 编译 (L2 DAG + L3 slots)
                    dag = self._load_dag(cache_key)
                    slots = self._load_l3_slots(ctx.session_id)
                    try:
                        plan = jit_compile(dag, slots)
                    except FallbackException:
                        continue  # 槽位不匹配，继续下一候选
                    
                    #   d. 执行 DAG 或返回缓存结果
                    result = self._load_l2_result(cache_key, slots)
                    if result:
                        ctx.reply = result.result_text
                        ctx.extra["cache_hit"] = "l2"
                        ctx.extra["cache_tts"] = result.tts_blob
                        ctx.filtered = True
                        # 开启观察窗口
                        self._start_observer_window(cache_key, ctx.user_id)
                        return ctx
                elif degrade_mode == "l1_only":
                    # 降级半缓存：仅复用 L1
                    l1 = self._query_l1(classification.intent_class, "fallback")
                    if l1:
                        ctx.extra["cache_hint"] = f"上下文偏移，半缓存模式"
        
        # 5. 全部未命中 → 正常执行
        ctx.extra["cache_hit"] = "miss"
        return ctx
    
    def _write_to_cache(self, ctx: PluginContext) -> PluginContext:
        """将执行结果写入缓存"""
        if ctx.extra.get("cache_hit") != "miss":
            return ctx  # 已命中，不需写入
        
        intent_class = ctx.extra.get("cache_intent", "unknown")
        
        # 提取动作序列
        actions = self._extract_actions(ctx.original_reply)
        
        # 写入向量索引
        query_vec = ctx.extra.get("query_embedding", [])
        if query_vec:
            composite_key = ctx.extra.get("cache_composite_key", "")
            self._vector_index.add(query_vec, composite_key)
            self._vector_index.save()
        
        # 写入 L2 结果
        if actions or len(ctx.original_reply or "") > 50:
            self._save_l2_result(
                composite_key=composite_key,
                text=ctx.original_reply,
                actions=actions,
            )
        
        # 缓存 TTS 音频
        tts_blob = ctx.extra.get("tts_audio")
        if tts_blob:
            TtsCacheManager().cache_tts(
                ctx.original_reply, tts_blob,
                level="l2",
                action_signature=composite_key,
                slot_hash=self._compute_slot_hash(ctx),
            )
        
        return ctx
```

### 10.2 整合到现有 Pipeline

在 `engine.py` 中注册新插件：

```python
# engine.py 注册部分 (在 _register_context_plugins 中)

if self._plugin_enabled("semantic_cache"):
    from plugins.builtin.cache_interceptor import CacheInterceptorPlugin
    self.plugin_manager.register(CacheInterceptorPlugin())
    self._logger.info("语义缓存插件已注册")
```

在 `boot.py` 中初始化：

```python
# boot.py 初始化部分

# ── 语义缓存系统 ──
_semantic_cache_enabled = Config.get("SEMANTIC_CACHE_ENABLED", True)
if _semantic_cache_enabled:
    from plugins.builtin.cache_interceptor import CacheInterceptorPlugin
    # 预加载 TinyBERT 分类器
    _cache_plugin = CacheInterceptorPlugin()
    app.logger.info("语义缓存系统: 已启用 (TinyBERT + FAISS + EmbeddingClient)")
```

### 10.3 数据库表

```sql
-- L1 静态语素
CREATE TABLE IF NOT EXISTS cache_l1 (
    intent_id       TEXT NOT NULL,
    speech_act_type TEXT NOT NULL,
    text            TEXT NOT NULL,
    tts_blob        BLOB,
    duration_ms     INTEGER DEFAULT 0,
    hit_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (intent_id, speech_act_type)
);

-- L2 DAG 定义
CREATE TABLE IF NOT EXISTS cache_l2_dags (
    action_signature TEXT PRIMARY KEY,
    intent_id        TEXT NOT NULL,
    dag_json         TEXT NOT NULL,          -- ActionGraph JSON
    model_version    TEXT DEFAULT '',
    hit_count        INTEGER DEFAULT 0,
    last_hit_at      TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- L2 执行结果
CREATE TABLE IF NOT EXISTS cache_l2_results (
    result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    action_signature TEXT NOT NULL,
    slot_hash        TEXT NOT NULL,
    result_text      TEXT NOT NULL,
    tts_blob         BLOB,
    response_json    TEXT,                   -- 完整的结构化回复
    executed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms      INTEGER DEFAULT 0,
    FOREIGN KEY (action_signature) REFERENCES cache_l2_dags(action_signature)
);

-- L3 实体槽位
CREATE TABLE IF NOT EXISTS cache_l3_slots (
    slot_name      TEXT NOT NULL,
    slot_type      TEXT NOT NULL,
    value_json     TEXT NOT NULL,
    confidence     REAL DEFAULT 1.0,
    source         TEXT DEFAULT 'extracted',
    session_id     TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP,
    PRIMARY KEY (session_id, slot_name)
);

-- 缓存置信度积分
CREATE TABLE IF NOT EXISTS cache_scores (
    cache_key      TEXT PRIMARY KEY,
    score          REAL DEFAULT 1.0,
    model_version  TEXT DEFAULT '',
    hit_count      INTEGER DEFAULT 0,
    last_hit_at    TIMESTAMP,
    last_heal_at   TIMESTAMP,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 缓存索引映射 (向量 ID → 缓存键)
CREATE TABLE IF NOT EXISTS cache_vector_mapping (
    vector_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key      TEXT NOT NULL,
    intent_class   TEXT NOT NULL,
    embedding      BLOB,                    -- float32 768-dim
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_cache_vec_intent ON cache_vector_mapping(intent_class);
```

---

## 11. 实施路线图

### Phase 1 — 基础架构 (Week 1-2)

```
Week 1:
  - L1 静态语素层: 表结构 + 基础 CRUD + 预置 20+ 常用短语
  - TTS 音频缓存: TtsCacheManager 文件存储
  - CacheInterceptorPlugin 骨架: PRE_FILTER/POST_TTS 拦截点

Week 2:
  - 前置硬分类器: TinyBERT 蒸馏训练 (6 个 Intent 类)
  - 后置向量判别器: Siamese + Slot-Forced Masking
  - 基础向量索引: FAISS IVF 集成
```

### Phase 2 — 核心系统 (Week 3-4)

```
Week 3:
  - L2 动作拓扑层: DAG 定义 + 序列化/反序列化
  - JIT 编译引擎: 占位符替换 + 类型检查
  - L3 实体槽位: 提取/存储/过期

Week 4:
  - 滑动窗口状态编码器: GRU 实现 + 复合键生成
  - 上下文匹配逻辑: 汉明距离 + 动态阈值 β
  - 降级模式: 全缓存/半缓存/参数重算
```

### Phase 3 — 自愈与优化 (Week 5-6)

```
Week 5:
  - 置信度积分系统: 观察窗口 + 奖惩逻辑
  - 异步自愈任务: LLM 重新生成 + Critique Model 差异比对
  - 原子性覆盖: 旧缓存替换 + 版本标签

Week 6:
  - 集成测试: 全管线端到端验证
  - 性能基准: 命中率 / 延迟 / API 节省
  - 预置 Intent 扩展: 12 → 20+ 类
```

---

## 12. 与现有基础设施的关系

| 现有组件 | 与本系统的关系 | 复用程度 |
|----------|---------------|---------|
| `EmbeddingClient` (768-dim) | 后置向量判别器的特征提取 + 状态编码器的输入 | ✅ 直接复用 |
| `MemorySystem` 向量存储 | 参考其 float32 BLOB 存储格式 | ⚠️ 参考设计 |
| `PromptCache` (SQLite + 向量) | 索引结构参考，但语义缓存使用 FAISS 替代 LIKE 搜索 | ⚠️ 参考设计 |
| `ChatPipeline` 5 阶段 | CacheInterceptorPlugin 插入 PRE_FILTER(0) 和 POST_TTS(100) | ✅ 扩展 |
| `MessageCipher` (AES-256) | 缓存内容存储在加密 DB 中（可选加密） | ✅ 可复用 |
| `TTS Plugin` | 缓存 TTS 输出频谱，L1/L2 命中时跳过 TTS 推理 | ✅ 协作 |
| `Config` 系统 | 新增 `SEMANTIC_CACHE_ENABLED` / `CACHE_ALPHA` 等配置 | ✅ 扩展 |
| `TaskManager` | 异步自愈任务注册到 TaskManager 后台执行 | ✅ 协作 |
| `SkillManager` / `SkillRegistry` | DAG 中的原子操作对应 Skill Tool 调用 | ⚠️ 需要适配 |
| `LMStudioChat` | 自愈任务中调用 LLM 重新生成参考回复 | ✅ 复用 |

---

*策划案 v1.0 完*
