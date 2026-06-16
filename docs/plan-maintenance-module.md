# 服务器维护模块（Server Maintenance Module）策划案

## 1. 概述

三态维护系统，根据用户使用数据自动调度后台维护任务，在用户空闲窗口静默执行。

### 1.1 系统三态

```
   ┌──────────┐     无请求持续1h     ┌──────────┐
   │  待命    │ ──────────────────→ │  待机    │
   │ (ready)  │                     │ (standby)│
   └────┬─────┘                     └──────────┘
        │                                │
        │ 预定维护时间到                  │ 预定维护时间到
        ↓                                ↓
   ┌──────────┐     维护完成自动重启    ┌──────────┐
   │  整理    │ ──────────────────→   │  待命    │
   │(maint)  │                        │          │
   └──────────┘                        └──────────┘
```

| 状态 | 含义 | 后端行为 | 前端行为 |
|-------|------|----------|----------|
| `ready` | 正常服务 | 正常处理请求 | 正常交互 |
| `maint` | 整理中 | 屏蔽新请求，执行维护任务 | 显示"服务器整理中" + 进度条 |
| `standby` | 待机低功耗 | 停止非必要服务，保持心跳 | 唤醒发请求时自动切回 ready |

### 1.2 设计目标
- **零用户打扰**：维护仅在用户大概率不使用时运行
- **学习型调度**：根据历史请求分布预测空闲窗口
- **可扩展任务**：整理任务通过插件注册，无需修改核心
- **失败安全**：维护过程中断不丢失数据，下次继续

---

## 2. 架构设计

### 2.1 模块结构

```
maintenance/
├── __init__.py           # 导出 MaintenanceSystem
├── system.py             # MaintenanceSystem 核心：状态机 + 调度器
├── clock.py              # 内部时钟：每分钟 tick，检查预定事件
├── tracker.py            # 用户活跃度追踪：记录请求时段分布
├── state.py              # 三态定义 + 状态切换逻辑
├── tasks/                # 维护任务注册目录
│   ├── __init__.py
│   ├── memory_compact.py # 记忆整理 / 合并碎片
│   ├── personality_optimize.py # V3 人格蒸馏 / 优化
│   └── log_cleanup.py    # 旧日志清理
├── frontend_bridge.py    # 与 Flask 前端的 SSE 通信
├── api.py                # Flask Blueprint：/api/maintenance/*
├── config.py             # 可配置参数
└── README.md
```

### 2.2 核心数据流

```
Clock (1min tick)
  │
  ├──→ check_schedule(): 检查预定维护时间
  │      │
  │      └──→ if event_due:
  │              TransitionSystem.to_maintenance()
  │              Executor.start_maintenance(tasks)
  │
  ├──→ check_idle(): 检查是否 1h 无请求
  │      │
  │      └──→ if idle_too_long:
  │              TransitionSystem.to_standby()
  │
  └──→ Tracker.record_tick(): 记录空时钟点（用于分析）
```

### 2.3 SSE 进度推送

后端 → 前端（挂起用户时推送）：

```
event: maintenance_start
data: {"started_at": "...", "tasks": [{"name": "记忆整理", "task_id": "mem_01"}, ...]}

event: maintenance_progress  
data: {"completed": 1, "total": 3, "current_task": "记忆整理", "current_progress": 0.45, "log": "正在压缩第 3 轮旧记忆..."}

event: maintenance_complete
data: {"completed_at": "...", "results": {...}, "reboot_at": "..."}

event: maintenance_error
data: {"task": "人格蒸馏", "error": "模型响应超时", "will_retry": true}
```

---

## 3. 状态机 (`maintenance/state.py`)

```python
from enum import Enum

class ServerState(Enum):
    READY = "ready"         # 正常待命
    MAINTENANCE = "maint"   # 整理中
    STANDBY = "standby"     # 待机低功耗

class StateTransitionError(Exception):
    pass

class ServerStateMachine:
    """三态机，控制状态转换"""
    
    _ALLOWED_TRANSITIONS = {
        ServerState.READY:       {ServerState.MAINTENANCE, ServerState.STANDBY},
        ServerState.MAINTENANCE: {ServerState.READY},  # 整理完=重启→ready
        ServerState.STANDBY:     {ServerState.READY},  # 用户请求到来时
    }
    
    def __init__(self):
        self._state = ServerState.READY
        self._listeners: list[Callable] = []
    
    @property
    def state(self) -> ServerState:
        return self._state
    
    def transition(self, target: ServerState) -> bool:
        if target not in self._ALLOWED_TRANSITIONS[self._state]:
            return False
        old = self._state
        self._state = target
        for listener in self._listeners:
            listener(old, target)
        return True
    
    def on_transition(self, callback: Callable):
        self._listeners.append(callback)
```

**转换规则**：
- `ready → maint`：预定维护时间到达
- `ready → standby`：持续 1h 无任何用户请求
- `maint → ready`：全部维护任务完成，自动服务重启
- `standby → ready`：收到新的用户请求（立即唤醒）

---

## 4. 用户活跃度追踪 (`maintenance/tracker.py`)

### 4.1 数据结构

用环形缓冲区（24h 窗口）记录每分钟的请求计数：

```python
class ActivityTracker:
    """
    每分钟记录一次请求密度(0~N)。
    24h = 1440 格的环形缓冲区。
    用于预测用户的使用习惯。
    """
    SLOTS = 1440  # 24 × 60
    
    def __init__(self):
        self._buffer = [0] * self.SLOTS          # 请求计数
        self._timestamps: deque[float] = deque()  # 最近请求的精确时间戳
        self._idle_start = None                   # 何时开始空闲计时
```

### 4.2 核心方法

```python
def record_request(self) -> None:
    """每次用户请求调用，记录到当前分钟槽"""
    slot = self._current_slot()
    self._buffer[slot] += 1
    self._timestamps.append(time.time())
    self._idle_start = None  # 重置空闲计时

def minutes_since_last_request(self) -> int:
    """距离上次请求的分钟数（用于判断待机）"""
    if not self._timestamps:
        return 0
    return int((time.time() - self._timestamps[-1]) / 60)

def predict_idle_window(self) -> tuple[int, int]:
    """
    基于历史数据预测今天的空闲时间段。
    返回 (start_hour, end_hour) 预测用户最不可能使用的时段。
    简单策略：取过去 7 天同时段请求数最低的 4 小时窗口。
    """
    ...

def idle_probability(self, hour: int, minute: int = 0) -> float:
    """
    返回 0.0~1.0 的"空闲概率"。
    基于过去 7 天相同时段的活跃度计算。
    用于调度器决定是否值得启动维护。
    """
    ...
```

### 4.3 持久化

```python
def save(self, path: str) -> None:
    """保存追踪数据到磁盘（pickle / json），服务器重启时恢复"""
    ...

def load(self, path: str) -> bool:
    """从磁盘加载历史追踪数据"""
    ...
```

追踪数据文件位置：`_data/activity_tracker.dat`

---

## 5. 时钟与调度 (`maintenance/clock.py`)

### 5.1 内部时钟

```python
class MaintenanceClock:
    """
    每分钟 tick 一次的守护线程时钟。
    每次 tick 触发回调：检查预定、检查空闲。
    """
    TICK_INTERVAL = 60  # 秒
    
    def __init__(self, system: "MaintenanceSystem"):
        self._system = system
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
    
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def _run(self):
        while not self._stop.wait(self.TICK_INTERVAL):
            self._system.on_tick()
```

### 5.2 预定维护计划

预定策略（可配置）：

```yaml
# config.py
MAINTENANCE_SCHEDULE = {
    "strategy": "predictive",       # 可选 "fixed" / "predictive" / "manual"
    "fixed_hour": 4,                # fixed 时：凌晨 4:00
    "predictive_min_free_hours": 3, # predictive 时：至少需要 3h 连续空闲
    "predictive_max_hour": 8,       # 不晚于早上 8:00
    "idle_timeout_minutes": 60,     # 多久无请求进入待机
    "retry_on_failure": True,       # 失败后是否重试
    "retry_delay_minutes": 30,      # 重试间隔
}
```

---

## 6. 维护任务 (`maintenance/tasks/`)

### 6.1 任务接口

```python
@dataclass
class TaskProgress:
    current: int = 0
    total: int = 1
    message: str = ""
    failed: bool = False
    error: str = ""

class MaintenanceTask(ABC):
    """所有维护任务的基类"""
    
    name: str = ""         # 显示名称
    priority: int = 0      # 执行顺序（低→高）
    requires_db: bool = False
    requires_llm: bool = False
    
    @abstractmethod
    def run(self, reporter: Callable[[TaskProgress], None]) -> dict:
        """
        执行维护。
        
        :param reporter: 进度报告回调，任务内定时调用:
            reporter(TaskProgress(current=3, total=10, message="压缩第3/10轮记忆"))
        :return: 任务结果 dict（成功/失败/统计）
        """
        ...
```

### 6.2 预置任务

| 任务名 | 优先级 | 需要 LLM | 说明 |
|--------|--------|----------|------|
| `MemoryCompactTask` | 10 | 否 | 压缩旧记忆：合并碎片、清理过期记忆 |
| `PersonalityOptimizeTask` | 20 | 是 | V3 人格蒸馏：检查待处理素材、触发蒸馏 |
| `LogCleanupTask` | 30 | 否 | 清理 30 天前旧日志轮转文件 |
| `SkillDistillTask` | 40 | 是 | 技能蒸馏：对话模式分析→生成草案 |
| `PromptCacheRefreshTask` | 50 | 否 | 重载提示词缓存（mtime 变更检测） |

### 6.3 任务执行器

```python
class TaskExecutor:
    """
    按优先级顺序执行所有注册的维护任务。
    每个任务运行在独立线程，通过 reporter 回调更新进度。
    任何任务失败不阻断后续任务。
    """
    
    def __init__(self):
        self._tasks: list[MaintenanceTask] = []
    
    def register(self, task: MaintenanceTask):
        bisect.insort(self._tasks, task, key=lambda t: t.priority)
    
    def run_all(self, progress_sink: Callable) -> list[dict]:
        results = []
        for task in self._tasks:
            def reporter(p: TaskProgress):
                progress_sink(task, p)
            try:
                result = task.run(reporter)
                result["task"] = task.name
                result["success"] = True
            except Exception as e:
                result = {"task": task.name, "success": False, "error": str(e)}
            results.append(result)
        return results
```

---

## 7. 核心系统 (`maintenance/system.py`)

### 7.1 `MaintenanceSystem`

```python
class MaintenanceSystem:
    """
    三态维护系统。
    
    用法:
        ms = MaintenanceSystem()
        ms.start()
    """
    
    def __init__(self, app=None, db=None, v3=None, engine=None):
        self.state = ServerStateMachine()
        self.clock = MaintenanceClock(self)
        self.tracker = ActivityTracker()
        self.executor = TaskExecutor()
        self._flask_app = app
        
        # 注册预置任务
        self.executor.register(MemoryCompactTask(db=db))
        self.executor.register(PersonalityOptimizeTask(v3=v3))
        self.executor.register(LogCleanupTask())
        self.executor.register(SkillDistillTask(engine=engine))
        self.executor.register(PromptCacheRefreshTask())
        
        # 加载历史追踪数据
        self.tracker.load()
    
    def start(self):
        self.clock.start()
    
    def record_user_request(self):
        """每次用户请求时调用"""
        self.tracker.record_request()
        # 待机状态→立即唤醒
        if self.state.state == ServerState.STANDBY:
            self.wake_from_standby()
    
    def on_tick(self):
        """每分钟 clock tick"""
        # 检查预定维护
        if self.state.state == ServerState.READY:
            if self._should_start_maintenance():
                self._begin_maintenance()
        
        # 检查待机
        if self.state.state == ServerState.READY:
            idle_minutes = self.tracker.minutes_since_last_request()
            if idle_minutes >= config.IDLE_TIMEOUT_MINUTES:
                self._enter_standby()
    
    def _should_start_maintenance(self) -> bool:
        """判断是否应该启动维护"""
        hour = datetime.now().hour
        minute = datetime.now().minute
        
        if config.SCHEDULE_STRATEGY == "fixed":
            return hour == config.FIXED_HOUR and minute == 0
        
        if config.SCHEDULE_STRATEGY == "predictive":
            # 用户不在使用 + 空闲概率高 + 有足够空闲时间窗口
            return (self.tracker.minutes_since_last_request() >= 15
                    and self.tracker.idle_probability(hour, minute) > 0.7)
        
        return False
    
    def _begin_maintenance(self):
        """进入整理状态 + 执行任务"""
        if not self.state.transition(ServerState.MAINTENANCE):
            return
        
        # 通知 Flask 屏蔽请求
        if self._flask_app:
            self._flask_app.config["SERVER_IN_MAINTENANCE"] = True
        
        # 后台执行
        def _run():
            try:
                results = self.executor.run_all(self._progress_sink)
                self._on_maintenance_done(results)
            except Exception as e:
                logger.error("维护流程失败: %s", e)
                self._on_maintenance_error(e)
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    
    def _progress_sink(self, task: MaintenanceTask, progress: TaskProgress):
        """维护进度回调——通过 SSE 推送到前端"""
        event = {
            "status": "maintenance_progress",
            "task": task.name,
            "current": progress.current,
            "total": progress.total,
            "message": progress.message,
        }
        # 通过 Flask SSE 推送
        if self._flask_app:
            maintenance_sse_broadcast(event)
    
    def _on_maintenance_done(self, results: list[dict]):
        success_count = sum(1 for r in results if r.get("success"))
        logger.info("维护完成: %d/%d 成功", success_count, len(results))
        
        # 通知前端
        maintenance_sse_broadcast({
            "status": "maintenance_complete",
            "results": results,
            "reboot_at": datetime.now().isoformat(),
        })
        
        # 保存追踪数据
        self.tracker.save()
        
        # 自动重启 → ready
        self.state.transition(ServerState.READY)
        if self._flask_app:
            self._flask_app.config["SERVER_IN_MAINTENANCE"] = False
    
    def _enter_standby(self):
        """进入待机模式"""
        if not self.state.transition(ServerState.STANDBY):
            return
        logger.info("服务器进入待机模式（无请求 %d 分钟）", config.IDLE_TIMEOUT_MINUTES)
        # Flask 可以释放部分资源 (连接池等)
    
    def wake_from_standby(self):
        """用户请求时唤醒"""
        self.state.transition(ServerState.READY)
        logger.info("服务器从待机模式恢复")
```

### 7.2 启动注入

在 `app.py` 中：

```python
from maintenance import MaintenanceSystem

maint_system = MaintenanceSystem(
    app=app, db=db, v3=personality_v3, engine=engine,
)
maint_system.start()

# 挂载 API
from maintenance.api import maintenance_bp
app.register_blueprint(maintenance_bp)
```

每次进入 Flask 请求时：

```python
@app.before_request
def _record_maintenance_activity():
    """每次请求时记录活跃度 + 检查维护状态"""
    if app.config.get("SERVER_IN_MAINTENANCE"):
        return jsonify({"error": "服务器整理中，请稍后访问", "retry_after": 120}), 503
    maint_system.record_user_request()
```

---

## 8. 前端 API (`maintenance/api.py`)

### 8.1 Flask Blueprint 端点

| 方法 | 路径 | 用途 | 响应 |
|------|------|------|------|
| `GET` | `/api/maintenance/status` | 查询当前状态 | `{"state": "ready"/"maint"/"standby", "since": "..."}` |
| `GET` | `/api/maintenance/sse` | SSE 维护进度流 | SSE 事件流 |
| `POST` | `/api/maintenance/trigger` | 手动触发维护 | `{"success": true}` |
| `POST` | `/api/maintenance/toggle_standby` | 手动切换待机 | `{"state": "standby"}` |

### 8.2 前端交互

维护中时，API 返回 503，前端显示：

```
┌─────────────────────────────────────┐
│  🔧 服务器整理中                     │
│                                     │
│  记忆整理    ████████░░░░░░  8/15    │
│  人格蒸馏    ██████░░░░░░░░  3/7     │
│                                     │
│  当前：压缩第 8/15 轮旧记忆          │
│  预计完成：约 2 分钟后               │
│                                     │
│  [日志]                              │
│  18:32:01 开始记忆整理              │
│  18:32:05 压缩第 5 轮旧记忆完成     │
│  18:32:08 正在压缩第 6 轮...         │
│                                     │
└─────────────────────────────────────┘
```

维护完成后前端刷新即可恢复正常。

---

## 9. 与现有系统的关系

| 现有系统 | 维护模块行为 |
|----------|-------------|
| Flask 请求 | 整理中返回 503，待机时正常处理但会唤醒 |
| SSE 流 | 整理中拒绝新流，已在进行的流允许完成后中止 |
| Flask-Login/认证 | 不受影响 |
| 记忆系统 | `MemoryCompactTask` 在维护时调用 |
| V3 蒸馏 | `PersonalityOptimizeTask` 在维护时触发 |
| 技能蒸馏 | `SkillDistillTask` 在维护时触发 |
| WebSocket | 整理中发送 close frame，维护完成后前端重连 |

---

## 10. 配置参数 (`maintenance/config.py`)

```python
SCHEDULE_STRATEGY = "predictive"      # fixed / predictive / manual
FIXED_HOUR = 4                         # fixed 策略时固定时间
PREDICTIVE_MIN_FREE = 3                # predictive 需要至少 3h 连续空闲
PREDICTIVE_MAX_HOUR = 8                # predictive 不晚于 8:00
IDLE_TIMEOUT_MINUTES = 60              # 1h 无请求→待机
RETRY_ON_FAILURE = True                # 失败重试
RETRY_DELAY_MINUTES = 30               # 重试间隔
ESTIMATE_PER_TASK_SECONDS = 300        # 每个任务预估耗时（给前端显示预计完成时间）
SSE_BUFFER_SIZE = 100                  # SSE 事件缓冲
TRACKER_DATA_PATH = "_data/activity_tracker.dat"
```

---

## 11. 实现计划

| 阶段 | 内容 | 预计工作量 |
|------|------|-----------|
| P0 | `state.py` 状态机 + `clock.py` 时钟 | 半天 |
| P1 | `tracker.py` 活跃度追踪 + 持久化 | 半天 |
| P2 | `system.py` 核心 + 任务执行器 | 1 天 |
| P3 | `tasks/` 预置任务（memory/personality/log） | 1 天 |
| P4 | `api.py` + `frontend_bridge.py` SSE | 1 天 |
| P5 | `app.py` 注入 + 请求拦截 + 待机 | 半天 |
| P6 | 前端 UI（Psychoscope 维护页面） | 1 天 |
| P7 | `predictive` 调度算法调优 | 半天 |

总计约 **5 天**。

---

## 12. 未解决的考虑 & 风险

| 风险 | 缓解措施 |
|------|----------|
| 维护中 LLM 请求（蒸馏）耗时长，期间服务器无响应 | 设置任务超时（默认 10min），超时→跳过→下次重试 |
| predictive 策略预测不准 | 回退到 fixed 凌晨 4:00；数据积累 3 天后+准确 |
| 待机模式下唤醒不稳定 | 待机=释放非关键资源，不关闭 HTTP listener |
| 整理中用户强制请求 | 前端显示 503+预估时间，紧急通道 `/api/emergency/cancel` 可中止维护 |
| 多用户冲突蒸馏调用 | `_distillation_pending` 已经 per-card + lock，维护模块不额外加锁 |
