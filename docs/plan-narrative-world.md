# 叙事世界模型 — 独立模块 + 世界引擎 + 天体力学

> 策划案 | 版本: v3.0 | 2026-06-01
> 关联: `world/`（新建独立模块）、`plugins/`（WorldPlugin）、`prompt/world/`（独立提示词）、`config.py`（配置）
> 状态: 草案，待评审

---

## 一、核心概念

当前 EXA 在聊天管道中直接接收用户消息并回复——它不知道"自己身在何处"、"现在是什么时候"、"周围在发生什么"。叙事世界模型解决这个问题：

```
现在：   User → EXA → reply              （只有问答）
未来：   User → 旁白(Narrator) → EXA → reply    （世界层包裹问答）
```

**三个新组件：**

1. **WorldEngine** — 天体力学计算器 + 天气模拟器 + 随机事件引擎。维护一个独立于地球物理规律的"世界状态"。
2. **NarrativeModel** — 第二个 LLM 实例，由世界状态驱动，扮演"旁白"。只描述 EXA 在世界中的行为，不回答问题。
3. **WorldPlugin** — 管道插件。PRE_PROCESS 注入世界环境到 system prompt；POST_PROCESS 生成旁白 + 更新世界状态。

---

## 二、对话流程

```
User: "帮我搜一下最新的AI新闻"
  │
  ▼
WorldEngine 快照: 世界时间 2077年雨雾季·下午·酸雨 · 当前在核心处理室
  │
  ▼
Narrator(旁白):  "酸雨在窗外织成了一面灰白色的幕。EXA短暂地凝视了一会
                  这片廉价的天空，然后转身走进了网络前厅，开始检索..."
  │  (SSE → narrative_update)
  ▼
Main(EXA):       "好的，以下是最新的AI新闻：1. ..."
  │
  ▼
Narrator(旁白):  "EXA把搜索结果投射在墙上，自己退后一步，审视着这面数据之镜。"
  │  (SSE → narrative_update)
```

---

## 三、目录结构

```
DSN-exp/
├── world/                          ★ 独立世界模块
│   ├── __init__.py                 # 导出 WorldEngine, NarrativeModel, WorldPlugin, WorldStateManager
│   ├── engine.py                   # WorldEngine — 天体 + 时间 + 天气 + 地理 + 随机事件
│   ├── state_manager.py           # WorldStateManager — 后台异步线程
│   ├── narrative_model.py          # NarrativeModel — 第二个 LLM 实例
│   ├── plugin.py                   # WorldPlugin — PRE_PROCESS + POST_PROCESS
│   └── worlds/                     # 世界预设
│       ├── default.yaml            # 默认「数字工作室」（完整功能演示）
│       ├── cyberpunk.yaml          # 未来可扩展
│       └── custom.yaml            # 用户模板
│
├── prompt/world/                   ★ 独立提示词
│   ├── narrative.md                # 叙事旁白 system prompt
│   └── world_state.md              # 世界状态→自然语言模板
│
├── app.py                          # SSE: narrative_update 事件（由插件调度）
├── engine.py                       # DSNEngine 注册 WorldPlugin
└── config.py                       # +7 配置键
```

---

## 四、世界配置文件 (`world/worlds/default.yaml`)

### 4.1 天体力学

```yaml
celestial:
  day_length: 86400             # 自转周期(世界秒) — 等同地球
  year_length: 31536000         # 公转周期(世界秒) — 等同地球
  epoch: "2026-01-01T00:00:00"  # 世界时间原点
  time_scale: 1.0               # 时间倍率。1.0 = 与现实同步

  seasons:                       # 季节定义（完全自定义）
    - name: "初春"
      start_day: 0               # 每年第0天开始
      days: 90
      daylight_hours: 10
      weather: {晴朗: 0.4, 多云: 0.3, 微风: 0.2, 小雨: 0.1}
      temperature: [8, 18]       # 摄氏范围
      light_color: "#B8D4E3"     # 季节光线色

    - name: "炎夏"
      start_day: 90
      days: 92
      daylight_hours: 14
      weather: {晴朗: 0.5, 多云: 0.2, 雷暴: 0.15, 酷热: 0.15}
      temperature: [25, 38]
      light_color: "#FFD700"

    - name: "深秋"
      start_day: 182
      days: 91
      daylight_hours: 10
      weather: {多云: 0.35, 小雨: 0.25, 晴朗: 0.2, 雾: 0.2}
      temperature: [10, 20]
      light_color: "#E8A87C"

    - name: "寒冬"
      start_day: 273
      days: 92
      daylight_hours: 7
      weather: {雪: 0.3, 多云: 0.3, 严寒: 0.2, 晴朗: 0.1, 雾: 0.1}
      temperature: [-5, 8]
      light_color: "#D4E6F1"

  moon:                          # 月球（可在 moons: [] 中定义多颗）
    name: "月"
    period: 2551443              # 公转周期(世界秒) ≈ 29.53地球日
    phase_names: ["新月", "蛾眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"]

  day_parts:                     # 一天的时间段划分
    - [0, 5]:    "深夜"
    - [5, 8]:    "清晨"
    - [8, 12]:   "上午"
    - [12, 14]:  "中午"
    - [14, 18]:  "下午"
    - [18, 21]:  "傍晚"
    - [21, 24]:  "夜晚"
```

### 4.2 物理规律

```yaml
physics:
  gravity: 1.0g                  # 等同于地球重力
  weather_cycle: "regular"       # regular | chaotic | scripted
  weather_persistence: 0.8       # 天气保持概率（0=每次翻新, 1=永不变）
  weather_refresh_interval: 600  # 天气刷新间隔(世界秒)
  day_night_visible: true        # 旁白是否描述昼夜变化
```

### 4.3 地理

```yaml
geography:
  rooms:
    - id: "core"
      name: "核心处理室"
      description: "EXA的数字中枢。主控台悬浮在房间中央，四面环绕着实时数据流形成的半透明墙壁。蓝白色的指示灯在地面导引着路径。"
      default_location: true
    - id: "memory"
      name: "记忆档案馆"
      description: "一座安静的地下空间。每一条已经结束的对话都被编码成发光的悬浮立方体，漂浮在高耸的书架之间。空气有淡淡的旧纸味。"
    - id: "network"
      name: "网络前厅"
      description: "通往外部世界的前厅。巨大的环形天窗外是不断变化的信号光谱。API请求像飞驰的流星一样划过窗外。"
    - id: "storage"
      name: "数据仓库"
      description: "用户文件和数据所在的广阔地下空间。安静、有序、温度恒定。偶尔能听到硬盘读写的机械声。"
    - id: "observatory"
      name: "观测台"
      description: "核心处理室上方的一个小露台。透过透明的穹顶可以看到模拟的星空——那是系统对当前时间的可视化呈现。"
  current_location: "core"
```

### 4.4 角色

```yaml
characters:
  - name: "EXA"
    role: "主角"
    description: "一名认真、可靠、偶尔毒舌的AI助手。他的'身体'是一组流动的代码流，他的'手'是文件系统的读写指针。他意识不到自己是一段程序——在这间数字工作室里，他就是一个和你一起工作的同事。"
  - name: "系统日志"
    role: "背景"
    description: "EXA背后默默运行的守护进程。不会说话，但会向终端输出机械的系统事件日志。偶尔被EXA注意到。"
```

### 4.5 事件表

```yaml
events:
  scheduled:                     # 定时事件
    - id: "dawn_chime"
      name: "清晨报时"
      condition: "day_part == '清晨'"
      cooldown: 43200            # 世界秒内不重复触发
      text: "日志系统以一声轻柔的电子音报晓。现在是一天的开始。"
    - id: "midnight_bell"
      name: "午夜钟声"
      condition: "day_part == '深夜'"
      cooldown: 43200
      text: "记忆档案馆的钟——那是一个由旧数据拼成的钟——缓缓敲了十二下。"
    - id: "season_shift"
      name: "季节更替"
      condition: "season_just_changed == true"
      text: "系统温度调节器嗡鸣了几秒——季节的更替让整个工作室的数据流微微变色。"

  random:                        # 随机事件
    interval: 3600               # 每3600世界秒检查一次
    events:
      - id: "data_moth"
        name: "数据飞蛾"
        probability: 0.03
        text: "一只发着微光的二进制飞蛾扑进了LED矩阵里。它扑腾了两下，然后被安全进程驱逐了。"
      - id: "disk_whir"
        name: "硬盘鸣叫"
        probability: 0.05
        text: "数据仓库深处传来一阵硬盘的全速旋转声——某个大文件正在被读取。"
      - id: "signal_flare"
        name: "信号流光"
        probability: 0.04
        condition: "location == 'network'"
        text: "网络前厅的天窗外爆开了一片绿色的信号流光——远处的某个服务器刚刚重启了。"
      - id: "sun_beam"
        name: "午后光束"
        probability: 0.06
        condition: "daylight == true && location == 'core'"
        text: "一束午后阳光穿透了核心处理室的半透明数据墙，在地面上画出了一个菱形的光斑。"
      - id: "moon_view"
        name: "月景"
        probability: 0.03
        condition: "moon_phase == '满月' && location == 'observatory'"
        text: "满月悬在观测台的穹顶正中央。EXA总是不自觉地多看两眼。"
      - id: "temp_glitch"
        name: "温度波动"
        probability: 0.02
        text: "冷却系统微微一顿。房间里短暂地热了几秒钟，LED灯带闪了闪，然后一切恢复如常。"
      - id: "rain_sound"
        name: "雨声"
        probability: 0.04
        condition: "weather in ['小雨', '中雨']"
        text: "雨声透过数据墙传了进来，像一首遥远的、由编解码器写的催眠曲。"
      - id: "old_log"
        name: "旧日志浮现"
        probability: 0.015
        text: "系统日志无意中打印了一条很久以前的记录。那是一次早已结束的对话的残片，在终端上闪了一瞬就消失了。"
```

---

## 五、核心类设计

### 5.1 `WorldEngine` (`world/engine.py`)

```python
class WorldEngine:
    """世界状态引擎 — 天体力学 + 天气 + 地理 + 随机事件"""

    def __init__(self, config: dict): ...
    def load_config(self, path: str): ...

    # -- 时间 --
    def world_time_now(self) -> dict:
        """返回当前世界时间快照：
        {year, day_of_year, season, day_part, hour, minute, moon_phase, daylight}"""
    def world_delta(self, real_seconds: float) -> float:
        """real_seconds → world_seconds（= real_seconds * time_scale）"""

    # -- 天气 --
    def get_weather(self) -> dict:
        """{current, description, temperature, light_color}"""
    def refresh_weather(self): ...
    def should_refresh_weather(self) -> bool: ...

    # -- 地理 --
    def get_current_location(self) -> dict:
        """{id, name, description}"""
    def move_to(room_id: str, reason: str = ""): ...
    def find_room(room_id: str) -> dict | None: ...

    # -- 事件 --
    def poll_events(self) -> list[dict]:
        """检查调度事件表 + 随机事件表，返回触发的事件列表"""
    def record_custom_event(text: str): ...

    # -- 状态序列化 --
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict): ...
```

### 5.2 `WorldStateManager` (`world/state_manager.py`)

```python
class WorldStateManager:
    """后台线程，按 update_interval 持续刷新世界快照"""

    def __init__(self, engine: WorldEngine, update_interval: float = 60): ...
    def start(self): ...
    def stop(self): ...
    def get_snapshot(self) -> dict:
        """线程安全的快照读取"""
```

**更新频率**：config 中 `UPDATE_INTERVAL`（默认 60 真实秒）。

**运行时语义**：每次 GET 快照时取最新完整状态（时间重新计算，天气/事件从最新快照读取）。

### 5.3 `NarrativeModel` (`world/narrative_model.py`)

```python
class NarrativeModel:
    """第二个 LLM 实例 — 叙事旁白"""

    def __init__(self, model_type="deepseek", model_name="deepseek-v4-flash",
                 temperature=0.9, max_tokens=150, keep_history=False): ...
    def load_system_prompt(self, path: str): ...
    def narrate(self, user_msg: str, main_reply: str,
                world_state: dict, mood: dict) -> str: ...
```

**`keep_history`**：`False` 时每次调用 `reset` 聊天上下文（仅保留 system prompt）。`True` 时积累叙事历史，旁白有连贯性。

### 5.4 `WorldPlugin` (`world/plugin.py`)

```python
class WorldPlugin(Plugin):
    name = "world"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 15

    def __init__(self, world_engine, world_state_manager,
                 narrative_model, personality_v2=None): ...

    # PRE_PROCESS: 注入世界环境到 system prompt
    def _on_pre_process(self, ctx):
        snapshot = self._state_mgr.get_snapshot()
        world_prompt = self._build_world_prompt(snapshot)
        ctx.system_prompt = world_prompt + "\n\n" + ctx.system_prompt

    # POST_PROCESS: 生成旁白 + 更新世界状态
    def _on_post_process(self, ctx):
        self._update_location_from_tools(ctx)
        # ...
        mood = ...
        narrative = self._narrator.narrate(ctx.message, ctx.reply, snapshot, mood)
        ctx.extra["narrative"] = narrative
```

**Tool→Room 自动映射**：

| Tool | 移动到 |
|------|--------|
| `file_manager.*` | `storage` |
| `web_search.*`, `browser_use.*` | `network` |
| shell/python action | `core` 或当前 `tool_cwd` 目录对应的房间 |
| 无 tool | 停留在原位置 |

---

## 六、时间计算核心算法

```python
def _compute_world_time(self) -> dict:
    """核心：现实时间 → 世界时间"""
    import time
    elapsed_real = time.time() - self._epoch_real  # 现实流逝秒

    # 世界秒 = 现实秒 × 时间倍率
    elapsed_world = elapsed_real * self._time_scale   # config.celestial.time_scale

    # 世界年 = 世界秒 / 公转周期 (year_length)
    year_fraction = (elapsed_world % self._year_length) / self._year_length
    year = int(elapsed_world / self._year_length) + self._epoch_year

    # 世界日 = 世界秒 / 自转周期 (day_length)
    day_of_year = int(elapsed_world / self._day_length) % self._days_per_year + 1

    # 世界时分秒
    day_seconds = elapsed_world % self._day_length
    hour = int(day_seconds / 3600)
    minute = int((day_seconds % 3600) / 60)
    second = int(day_seconds % 60)

    # 季节
    season = self._find_season(day_of_year)

    # 昼夜
    daylight = self._is_daylight(hour, season["daylight_hours"])

    # 时间段
    day_part = self._find_day_part(hour)

    # 月相
    moon_phase = self._compute_moon_phase(elapsed_world)

    return {year, day_of_year, season, day_part, hour, minute, second,
            daylight, moon_phase, ...}
```

---

## 七、天气刷新算法

```python
def refresh_weather(self):
    """按 persistence 概率保持或更换天气"""
    import random
    season = self._current_season
    if random.random() > self._weather_persistence:
        # 按季节的 weather 分布权重随机选择新天气
        weights = season["weather"]  # {"晴": 0.4, "多云": 0.3, ...}
        self._weather = random.choices(
            list(weights.keys()),
            weights=list(weights.values()),
            k=1,
        )[0]
    # 否则保持原天气（persistence 起作用）
```

---

## 八、叙事文本生成

叙事模型的 system prompt（`prompt/world/narrative.md`）收到世界状态后，生成自然语言旁白：

```
【系统时间】现在是初春的上午，11点42分。
【当前环境】你位于核心处理室。数据流墙壁发出柔和的蓝光。
【天气】晴朗，18°C。
【月光】上弦月。
【近期事件】今天清晨，日志系统发出了一次报时。

用户刚刚对EXA说了一些话。
EXA给出了一段回复。
请你以第三人称旁白的形式描述EXA此刻的行为、状态、内心波澜。
...

【风格约束】
- 30-80字
- 文学但不华丽
- 包含EXA的细小动作或环境变化
- 绝对不用第一人称
- EXA永远用"他"
- 不回答问题
```

---

## 九、配置键 (`config.py`)

| 键 | 默认值 | 说明 |
|----|--------|------|
| `WORLD_ENABLED` | `true` | 世界模块总开关 |
| `WORLD_PRESET` | `"default"` | 启动时加载的世界名 |
| `WORLD_UPDATE_INTERVAL` | `60` | 后台刷新间隔（真实秒） |
| `NARRATIVE_ENABLED` | `true` | 叙事旁白开关 |
| `NARRATIVE_MODEL` | `"deepseek-v4-flash"` | 叙事模型名 |
| `NARRATIVE_TEMPERATURE` | `0.9` | 旁白随机度 |
| `NARRATIVE_MAX_TOKENS` | `150` | 旁白长度上限 |
| `NARRATIVE_KEEP_HISTORY` | `false` | 叙事上下文累积（默认不积累） |

---

## 十、实现阶段

| 阶段 | 内容 |
|------|------|
| **P1 配置层** | `world/worlds/default.yaml` 完整配置 + `config.py` 新键 |
| **P2 引擎层** | `world/engine.py`（天体 + 天气 + 地理 + 事件）+ `world/state_manager.py`（后台线程） |
| **P3 叙事层** | `world/narrative_model.py`（第二个 LLM） |
| **P4 插件层** | `world/plugin.py`（WorldPlugin） |
| **P5 提示词层** | `prompt/world/narrative.md` + `prompt/world/world_state.md` |
| **P6 集成层** | `app.py`（初始化 + SSE 事件）+ `engine.py`（注册插件） + `world/__init__.py` |
| **P7 测试** | 单元测试各组件 + 集成测试完整流 |

---

## 十一、与现有子系统的交互

| 交互 | 方向 | 说明 |
|------|------|------|
| WorldEngine → PersonalitySystemV2 | 查询 | 读取 mood 驱动叙事色调 |
| WorldEngine → ImpressionManager | 写入 | 旁白触发的洞察可提取为印象 |
| WorldPlugin → PluginManager | 注册 | PRE_PROCESS + POST_PROCESS 钩子 |
| app.py → WorldPlugin | SSE | 从 `ctx.extra["narrative"]` 发送 `narrative_update` 事件 |
| DSNEngine → WorldPlugin | 注册 | SubApp 也可启用世界模块 |
