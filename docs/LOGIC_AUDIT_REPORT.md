# 人格系统(蒸馏) + 待机系统 — 逻辑审查报告

---

## 第一部分：整体流程（大白话讲清楚这两块代码想干什么）

### 人格/蒸馏系统到底在干什么

这个系统的核心目标是：**让 AI 助手"有性格"，并且这个性格能在和用户聊天过程中动态变化。**

整个流程分三步：

**Step 1 — 建立"角色画像"。** 有一张 YAML 格式的"角色卡"（`character_cards/exa.yaml`），里面用自然语言描述了角色是什么样的人（性格、说话方式、价值观等），还可以附带"经历素材"（像角色的人生履历）和"语料"（类似角色的作品集）。通过一个叫"蒸馏"的过程，用一个 LLM 分 4 步把这些材料变成一套结构化的数据：一段角色全貌描述 + 行为模式列表 + 言语模式列表 + 情绪模型 + 关系模型 + 50 维度的量化性格向量（每个维度 0~1，0.5 是中性）。

**Step 2 — 每次聊天时注入"动态性格"。** 每次生成回复前，系统取蒸馏出来的 50 维向量，叠加上：基于时间的随机噪声（让性格每小时有微小的自然波动）+ 当前情绪调制（开心→某些维度偏高）+ 亲密度调制（关系越亲→某些维度如社交主动性偏高）+ 长期漂移。合成后生成一段自然语言的人格提示词，注入到主 AI 的 system prompt 里。

**Step 3 — 每次聊天后回收"反馈"。** 每次用户发消息+AI 回复后，调用一个"性格判定模型"（也是一个 LLM），分析这段对话让角色情绪发生了什么变化（joy/sadness/anger/fear 四个维度的 delta）和亲密度变化了多少（0~100）。这些变化累积下来，影响下一次 Step 2 的动态合成。

技能蒸馏（引擎 B）是另一个独立的东西：从用户的聊天历史里挖掘出可重用的"模式"（如"用户反复问天气预报"），自动生成技能草案。但这个引擎实际上**从没被正确初始化过**（见下面的 Bug #13）。

### 待机系统到底在干什么

这个系统做三件事：**追踪活跃度、自动待机节能、自动跑后台维护。**

**追踪活跃度**：每分钟记录一次用户请求密度，维护一个 7 天 x 1440 分钟的时间窗。能回答"过去 7 天的凌晨 3:15 平均有多少请求"这样的问题。

**自动待机**：一个内部时钟每 60 秒 tick 一次。如果 tick 时系统处于 READY 状态，且距离上次请求已经 ≥ 60 分钟，就自动进入 STANDBY（待机）。用户下次发请求时自动唤醒。

**自动维护**：在 READY 状态下，tick 时还会检查是否到了维护时间。两种策略：
- `fixed`：每天凌晨 4:00 整执行
- `predictive`：同时满足"用户已空闲 ≥ 60 分钟"+"当前时段在历史活跃度低窗口"

维护时依次跑三个任务（优先级序）：记忆整理 → 人格蒸馏（导入新素材+触发 V3 蒸馏）→ 日志清理。维护期间新请求返回 503。

---

## 第二部分：发现的问题

### 🐛 严重 Bug

#### Bug #1 — `dynamic_synthesizer.py:38-51`：4 个维度下标全部错位，情绪/亲密度调制影响的是错误维度

```python
# dynamic_synthesizer.py 第 38-51 行
B_EMOTIONAL_EXPRESSIVENESS_IDX = 6   # 实际指向: B2 情绪外显度 ✓
B_RESILIENCE_IDX = 8                 # 实际指向: B4 共情能力 ✗  本应指向 B3 情绪恢复力(应为7)
B6_DOMINANT_MOOD_IDX = 11            # 实际指向: C1 理性-直觉 ✗  本应指向 B6 主导情绪基调(应为10)
H_PROACTIVITY_IDX = 45               # 实际指向: H1 主动性 ✓
H_PATIENCE_IDX = 46                  # 实际指向: H2 耐心 ✓
H_RISK_TAKING_IDX = 49               # 实际指向: H5 秩序感 ✗  本应指向 H4 冒险倾向(应为48)
# 亲和维度:
D_AFFILIATION_NEED_IDX = 17          # 实际指向: D1 亲和需求 ✓
D_SOCIAL_INITIATIVE_IDX = 19         # 实际指向: D3 社交主动性 ✓
D_TRUST_IDX = 20                     # 实际指向: D4 信任倾向 ✓
G_INTIMACY_CAPACITY_IDX = 40         # 实际指向: G2 依赖倾向 ✗  本应指向 G1 亲密能力(应为39)
E_VERBOSITY_IDX = 25                 # 实际指向: E1 话量 ✓
E_FORMALITY_IDX = 32                 # 实际指向: E8 语气词密度 ✓
```

**后果**：当角色生气时，系统本应降低"情绪恢复力"(B3)，实际降低的是"共情能力"(B4)。当角色开心时，系统本应提升"主导情绪基调"(B6) 为乐观，实际提升的是"理性-直觉"(C1)。当亲密度升高时，本应提升"亲密能力"(G1)，实际提升的却是"依赖倾向"(G2)。整个动态调制的 4/13 个效果是**错的**。

**根本原因**：这些下标是手工数的，但 ALL_DIMENSIONS 列表的顺序和程序员预期的不一致。应该用字符串 trait ID（如 "B3"）从 TRAIT_MAP 查找，而不是硬编码数字。

---

#### Bug #2 — `maintenance/api.py:70,81`：枚举与字符串比较，两个 API 端点永久失效

```python
# api.py 第 70 行（trigger_maintenance 端点）
if ms.state.state != "ready":      # ✗ ServerState.READY != "ready" → 永远是 True
    return jsonify({"error": f"服务器当前状态: {ms.state.state.value}"}), 409

# api.py 第 81 行（toggle_standby 端点）
if ms.state.state == "standby":    # ✗ ServerState.STANDBY == "standby" → 永远是 False
    ms._wake_from_standby()
```

`ms.state.state` 返回的是 `ServerState` 枚举成员（如 `ServerState.READY`），不是字符串。Python 中枚举成员和字符串的比较永远是 `False`/`True`（取决于 `==` 还是 `!=`）。

**后果**：
- `POST /api/maintenance/trigger` — **永远返回 409 错误**，无法手动触发维护
- `POST /api/maintenance/toggle_standby` — 在 STANDBY 状态下点击"切换"**永远无法唤醒**（枚举比较失败 → 走 else → `trigger_standby()` 因为状态不是 READY 而失败 → 什么也没发生）

**修复**：改为 `ms.state.state != ServerState.READY` 和 `ms.state.state == ServerState.STANDBY`。

---

#### Bug #3 — `maintenance/tracker.py:42-57`：日期轮转在跳过天数 > 1 时数据错乱

```python
# tracker.py 第 42-57 行
def _rotate_if_new_day(self):
    ...
    days_diff = (today - self._base_date).days
    for s in range(_SLOTS):
        row = self._buffer[s]
        for i in range(6, days_diff - 1, -1):        # ← 这里循环从 6 到 days_diff
            row[i] = row[i - days_diff] if i - days_diff >= 0 else 0
        for i in range(min(days_diff - 1, 6)):        # ← 这里只清 [0, days_diff-2] 
            row[i] = 0
        row[0] = 0
```

当 `days_diff = 2`（跳过一天）时：
- 第二个循环 `range(1)` 只清理了 `row[0]`
- `row[1]` **从来没被清零**，保留旧数据
- 导致 `row[1]` 和 `row[3]` 都包含同一份旧数据（重复了）

正确的做法应该是 `range(min(days_diff, 7))`，而不是 `range(min(days_diff - 1, 6))`。

**触发条件**：用户上次请求是前天，今天第一次请求 → days_diff=2 → 数据错乱。日常使用可能偶尔触发。

---

#### Bug #4 — `distillation_engine.py:198-199`：手动覆盖值在 LLM 没返回该维度时被静默丢弃

```python
# distillation_engine.py 第 196-202 行 (run 方法中的顺序)
indicator_vector = self._pass3_quantization(...)     # 可能缺少某些维度的 LLM 返回值
indicator_vector = self._apply_manual_overrides(...) # ← 只覆盖已存在的 key (if tid in vec)
indicator_vector = self._validate_vector(...)        # ← 把缺失维度补为 0.5
```

执行顺序：
1. LLM 返回的 50 维向量可能缺某些维度 → `_pass3_quantization` 补充为 0.5
2. 但 `_apply_manual_overrides` 在**步骤 1 和步骤 3 之间**、且**只覆盖已存在的 key**（`_apply_manual_overrides:329: if tid in vec`）
3. `_validate_vector` 在之后把剩余缺失维度补为 0.5，**覆盖值已丢失**

**后果**：如果用户手动指定了维度 A1 的值为 0.9，但 LLM 恰好没返回 A1，这个手动覆盖写在 YAML 里但实际**完全没有生效**。

**修复**：将 `_apply_manual_overrides` 移到 `_validate_vector` 之后调用。

---

#### Bug #5 — `skills/distill.py` 的技能蒸馏（引擎 B）从未被正确初始化

`engine.py:594-597`：
```python
DistillationEngine(              # 注意：这是 skills/distill.py 的 DistillationEngine
    db=self.db, skill_manager=self.skill_manager,
    llm_client=None,             # ← 没有传入 LLM 客户端！
)
```

`skills/distill.py:217-219`：
```python
def _mine_patterns(self, conversations: list[dict]) -> list[dict]:
    if not self.llm:             # ← llm_client=None → 直接返回空列表
        return []
```

`engine.py:987-998` 中第二次创建也是同样的问题。

**后果**：DistillPlugin 声称是"双引擎蒸馏"，但**技能蒸馏（引擎 B）永远返回 0 个模式**。"定时 + 关键词触发技能蒸馏"的整个功能是僵尸代码——代码完整存在，但从没运行过。只有 V3 人格蒸馏（引擎 A）在正常工作。

---

### ⚠️ 逻辑缺陷

#### Issue #6 — `_send_with_temp` 临时修改 chat 对象的 temperature/max_tokens，线程不安全

这个模式出现在 `distillation_engine.py:258-272`、`personality_judge.py:147-160`、`experience_importer.py:112-127`、`personality_generator.py:150-163` 四处。

```python
@staticmethod
def _send_with_temp(chat, prompt, temperature, max_tokens):
    old_temp = getattr(chat, 'temperature', None)
    old_max = getattr(chat, 'max_tokens', None)
    try:
        chat.temperature = temperature    # ← 无锁修改共享对象
        chat.max_tokens = max_tokens
        return chat.send_message(prompt)
    finally:
        chat.temperature = old_temp       # ← 恢复到旧值
        chat.max_tokens = old_max
```

蒸馏在后台线程运行（`distill_plugin.py:99` 的 daemon 线程），而 `chat.send_message()` 可能被主线程（聊天管线）同时使用。如果两个线程共享同一个 chat 对象——而在 `app.py` 中 `_v3_personality_chat`（用于性格判定）和 `_distill_chat`（用于蒸馏）是**两个独立客户端**，所以主聊天和蒸馏不会冲突。但蒸馏内部的 `_pass3_quantization` 和 `_pass1_global_understanding` 可能在同一个线程的不同调用之间被其他代码并发调用——不过因为蒸馏是单线程跑的（`distill()` 方法同步执行 4 个 pass），所以当前不会冲突。

**风险等级**：当前不发生竞态，但代码结构上是不安全的（任何未来引入并发蒸馏的改动都会触发）。

---

#### Issue #7 — `dynamic_synthesizer.py:115-119`：噪声基于小时粒度切换，每小时整点突然变化

```python
def _generate_noise_vector(self, seed: int, amplitude: float) -> list[float]:
    period = int(time.time() // 3600)    # ← 每小时一个不同的 period
    rng = random.Random(f"dsn_pv3_{seed}_{period}")
    noise = [rng.uniform(-amplitude, amplitude) for _ in range(DIMENSION_COUNT)]
```

在 XX:59:59 和 XX:00:00 之间，50 个维度的噪声值会**全部同时突变**。性格在每小时整点有 ±12% 的抖动。这是设计选择，不是在聊天过程中很明显的"断崖感"但技术上不是 bug。

---

#### Issue #8 — `character_card.py:150-158`：指纹不包含 manual_overrides 和 dynamic_config

`compute_fingerprint()` 只 hash 了 card_id + natural_language + corpus + experiences。修改 `manual_overrides` 或 `dynamic_config` 不会改变指纹，因此不会触发重蒸馏。

**后果**：用户改了手动覆盖值或噪声参数后，系统认为"内容没变"而跳过蒸馏。得手动触发蒸馏 API（又是 broken 的 — 见 Bug #2）或等维护任务。

---

#### Issue #9 — `state_manager.py:131`：每次交互后缓存全清，下次重建做两次文件 IO

```python
def on_interaction(self, uid, new_mood, new_affinity):
    ...
    self._invalidate_snapshot(uid)    # ← 清除快照缓存

def _invalidate_snapshot(self, uid):
    self._snapshot_cache.pop(uid, None)
```

每次交互 → 清缓存 → 下一个请求调 `get_current_snapshot` → 缓存 miss → **重新读角色卡 YAML + 蒸馏 JSON 文件**。但实际上每次交互只变了 mood/affinity/interactions，角色卡和蒸馏产物完全没变。性能浪费。

---

#### Issue #10 — `personality_v3_plugin.py:50`：每次用户消息同步调用 LLM 做性格判定

`PersonalityV3Plugin.on_hook()` 在 POST_PROCESS 阶段**同步**调用 `PersonalityJudge.analyze()` → `chat.send_message()`。这意味着每个用户消息的响应链路都被阻塞，等待 LLM 判定完成才返回。

**后果**：即使判定模型跑在本地 LMStudio，每次对话额外增加 300~1000ms 延迟。理论上这个判定可以后台异步做（类似蒸馏的做法），但当前是同步的。

---

#### Issue #11 — `maintenance/api.py:43-53`：SSE 队列永不清理，内存泄漏

```python
def sse_stream():
    q = subscribe()                 # ← 添加到全局 _sse_queues 列表
    def generate():
        while True:
            data = q.get(timeout=30)
            yield data
    return Response(generate(), ...)
```

`subscribe()` 把队列加入全局列表，但**没有任何地方调用 `unsubscribe(q)`**。客户端断连、刷新页面后，旧队列永远留在列表里。`frontend_bridge.py` 的 `unsubscribe` 函数从头到尾没被调用过。

---

#### Issue #12 — `maintenance/tracker.py:124`：`best_idle_window` 只扫描凌晨 0~8 点

```python
def best_idle_window(self, min_free_hours=3, max_hour=8):
    for start_slot in range(0, max_hour * 60 - window_slots + 1):
```

硬编码扫描范围是午夜到早上 8 点。如果用户的活跃低谷在下午（比如上午睡觉、下午活动），这个算法永远找不到。配置值 `PREDICTIVE_MAX_HOUR = 8` 写死了这个限制。

---

### 💡 设计层面的问题

#### Issue #13 — personality_judge 的启发式回退只处理 joy/sadness/anger

`_heuristic_analyze:162-202` 只根据关键词修改 joy/anger/sadness，从不更新 fear。另外 `DEFAULT_MOOD` 定义了 7 个维度（joy/sadness/anger/fear/disgust/surprise/neutral），但 `JUDGE_PROMPT_TEMPLATE` 和 LLM 解析代码都只处理前 4 个。disgust/surprise/neutral 在整个系统中是僵尸维度——定义了但从未被读写。

#### Issue #14 — `_affinity_level` 的阈值定义了三份完全相同的映射

`personality_v3/__init__.py:469-481` 和 `personality_generator.py:213-226` 中各自维护了一套相同的 0~100 亲密度分级逻辑（陌生人/相识/朋友/密友/伙伴/挚友）。任何修改都得同时改两处。应该只存一处。

#### Issue #15 — maintenance 的 fixed 策略只在整分触发 + 时钟偏移问题

```python
if config.SCHEDULE_STRATEGY == "fixed":
    return hour == config.FIXED_HOUR and minute == 0
```

MaintenanceClock 使用 `time.sleep(60)` 循环，60s 间隔意味着 tick 触发时间相对启动时间偏移。如果启动时恰好是 4:00:30，那 tick 会在 4:01:30 触发 → minute=1 → 错过。错过就要等 24 小时。没有"补偿执行"逻辑。

#### Issue #16 — tracking 数据的 `total_requests` 和 `_request_count` 会随时间发散

`_request_count` 是自启动以来的累加计数器，从不减少。`total_requests()` 从 buffer 实时计算（只包含最近 7 天）。超过 7 天后两者必然不一致——但只有 `total_requests()` 用于决策，`_request_count` 只是展示用，所以不影响功能，但会误导。

---

## 第三部分：问题汇总表

| # | 严重度 | 文件 | 行号 | 描述 |
|---|--------|------|------|------|
| 1 | 🐛 Bug | `dynamic_synthesizer.py` | 38-51 | 4 个维度下标偏移 1，情绪/亲密度调制应用在错误维度 |
| 2 | 🐛 Bug | `maintenance/api.py` | 70,81 | ServerState 枚举 vs 字符串比较，trigger/toggle API 永久失效 |
| 3 | 🐛 Bug | `maintenance/tracker.py` | 42-57 | 日期轮转在 days_diff>1 时 row[days_diff-1] 不清零，数据重复 |
| 4 | 🐛 Bug | `distillation_engine.py` | 196-202 | manual_override 在 validate_vector 前执行，缺失维度的覆盖值丢失 |
| 5 | 🐛 Bug | `engine.py` | 594-597, 987-998 | skills/DistillationEngine 初始化时 llm_client=None，技能蒸馏完全失效 |
| 6 | ⚠️ 缺陷 | 4 处 | — | _send_with_temp 无锁修改 chat 对象属性，架构级别 unsafe |
| 7 | ⚠️ 缺陷 | `dynamic_synthesizer.py` | 116 | 噪声按整小时切换，整点突变 |
| 8 | ⚠️ 缺陷 | `character_card.py` | 150-158 | 指纹不含 manual_overrides/dynamic_config，修改不会触发重蒸馏 |
| 9 | ⚠️ 缺陷 | `state_manager.py` | 131 | 每次交互全清缓存，下次重建重复文件 IO |
| 10 | ⚠️ 缺陷 | `personality_v3_plugin.py` | 50 | 同步 LLM 判定阻塞每个请求的响应链路 |
| 11 | ⚠️ 缺陷 | `maintenance/api.py` | 44 | SSE subscribe 无对应 unsubscribe，队列泄漏 |
| 12 | ⚠️ 缺陷 | `maintenance/tracker.py` | 124 | best_idle_window 只扫描 0~8 点，下午空闲窗口被忽略 |
| 13 | 💡 设计 | `personality_judge.py` | 162-202 | 启发式回退忽略 fear，disgust/surprise/neutral 僵尸维度 |
| 14 | 💡 设计 | 两处 | — | 亲密度分级逻辑重复定义（__init__.py + personality_generator.py） |
| 15 | 💡 设计 | `maintenance/system.py` | 105 | fixed 策略只整分触发，错过等 24h |
| 16 | 💡 设计 | `maintenance/tracker.py` | 68,117 | _request_count vs total_requests() 长期发散 |

---

## 第四部分：优先修复建议

**立即修复（影响功能正确性）：**
1. Bug #1 — 维度下标错位（改为用字符串 trait ID 索引）
2. Bug #2 — API 枚举比较（改成 ServerState.READY/STANDBY）
3. Bug #4 — 手动覆盖顺序（移动到 validate_vector 之后）

**短期修复（功能不可用/数据错误）：**
4. Bug #3 — 日期轮转逻辑
5. Bug #5 — 技能蒸馏引擎注入 LLM 客户端

**中期修复（性能/鲁棒性）：**
6. Issue #11 — SSE 队列泄漏（注册 generator close 回调）
7. Issue #10 — 性格判定异步化
8. Issue #9 — 缓存策略优化（只清除动态部分）
9. Issue #8 — 指纹补全

**长期重构（架构整洁）：**
10. Issue #6 — _send_with_temp 重构为线程安全的参数传递方式
11. Issue #13 — 统一 mood 维度（7→4 或全量支持）
12. Issue #14 — 消除亲密度分级的代码重复
