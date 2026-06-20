# DSN-exp 提醒系统增强 — 补全策划案

> 补齐 Phase 1 主线中剩余的提醒增强模块。
> 目标：DAILY_PLAN 每日计划提醒、PERIODIC 通用 cron 调度、COUNTDOWN 倒计时增强、SKIP 交互、standby 推送。

---

## 1. 现状分析

### 已实现

| 功能 | 位置 | 说明 |
|------|------|------|
| `TaskType.REMINDER / HABIT / COUNTDOWN` | `tasks.py:24-31` | 三种提醒类型已定义 |
| `TaskStatus.MISSED / SKIPPED` | `tasks.py:41-42` | 两种状态已定义 |
| `Task.skip_count` | `tasks.py:75` | 跳过计数已在模型上 |
| `_load_persistent_tasks()` | `tasks.py:240-303` | 重启恢复逻辑完备，过期自动标记 MISSED |
| `_schedule_reminder_task()` | `tasks.py:366-406` | 单次/周期性调度，>24h 轮询，HABIT 自排 |
| 数据库表 | `tasks.py:181-234` | `tasks` / `task_results` / `task_notifications` 齐备，`delivered` / `dismissed` 列已迁移 |
| 提醒 API | `reminder_api.py` | 列表/完成/取消端点完备 |
| TaskPlugin | `task_plugin.py` | `<task>` 标签解析，支持 reminder / habit / countdown |
| PlanPlugin | `plan_plugin.py` | 晨间计划注入 + 日终报告，可对接 DAILY_PLAN |

### 待实现

| 功能 | 难度 | 说明 |
|------|------|------|
| `TaskType.DAILY_PLAN` | 低 | 每日 07:30 触发计划播报，对接 PlanPlugin |
| `TaskType.PERIODIC` | 低 | 自定义 cron 表达式调度 |
| COUNTDOWN 剩余时间显示 | 低 | 触发时计算并注入 "距离目标还有 X 天" |
| Skip API（/api/reminder/skip） | 低 | 标记任务为 SKIPPED，递增 skip_count |
| Standby 推送 | 中 | standby 模式下提醒仍需投递到对话 |
| PlanPlugin 与 DAILY_PLAN 联动 | 中 | PlanPlugin 提供 `trigger_daily_plan()` 接口 |

---

## 2. 详细设计

### 2.1 新增 TaskType

```python
class TaskType(Enum):
    REMINDER = "reminder"
    HABIT = "habit"
    COUNTDOWN = "countdown"
    DAILY_PLAN = "daily_plan"     # 新增：每日固定时间触发（如 07:30）
    PERIODIC = "periodic"         # 新增：通用 cron 表达式
    REASONER = "reasoner"
    ANALYSIS = "analysis"
    ACTION = "action"
```

**DAILY_PLAN 参数**:
```json
{
  "type": "daily_plan",
  "params": {
    "trigger_time": "07:30",
    "text": "早安！今日计划已生成。"
  }
}
```

调度方式：`schedule.every().day.at("07:30").do(...)`（复用 schedule 库自带 `.day.at()`）。

**PERIODIC 参数**:
```json
{
  "type": "periodic",
  "params": {
    "cron": "0 7 * * 1-5",
    "text": "工作日早七点提醒"
  }
}
```

PERIODIC 用 `croniter` 库解析 cron 表达式，计算下一次触发时间，到期后重新计算下一次。

### 2.2 TaskPlugin 增强

在 `_handle_task()` 中新增两个分支：

```python
elif task_type == "daily_plan":
    return self._create_daily_plan(params, ctx)
elif task_type == "periodic":
    return self._create_periodic(params, ctx)
```

**DAILY_PLAN 创建** (`_create_daily_plan`):
```python
def _create_daily_plan(self, params, ctx):
    trigger_time = params.get("trigger_time", "07:30")
    # 解析 "HH:MM" → 今日该时刻，若已过则明天
    hour, minute = map(int, trigger_time.split(":"))
    now = datetime.now()
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        scheduled += timedelta(days=1)
    task_id = self._task_mgr.create_task(
        task_type=TaskType.DAILY_PLAN,
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        params=params,
        scheduled_time=scheduled,
        interval_seconds=86400,  # 每 24 小时重复
    )
    return task_id
```

复用 HABIT 的 `interval_seconds=86400` 实现每日自动重复。

**PERIODIC 创建** (`_create_periodic`):
```python
def _create_periodic(self, params, ctx):
    cron_expr = params.get("cron", "")
    # 用 croniter 计算下一次
    import croniter
    cron = croniter.croniter(cron_expr, datetime.now())
    next_time = cron.get_next(datetime)
    task_id = self._task_mgr.create_task(
        task_type=TaskType.PERIODIC,
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        params=params,
        scheduled_time=next_time,
    )
    # 额外保存 cron_expr 到 params
    return task_id
```

### 2.3 _schedule_reminder_task 增强

当前方法处理 REMINDER / HABIT / COUNTDOWN。需新增：

```python
# DAILY_PLAN: schedule.every().day.at()
if task.task_type == TaskType.DAILY_PLAN:
    time_str = task.params.get("trigger_time", "07:30")
    job = self.scheduler.every().day.at(time_str).do(reminder_job)
    job.tag(task.task_id)
    return

# PERIODIC: croniter 计算，单次调度后重算
if task.task_type == TaskType.PERIODIC:
    ...
```

### 2.4 COUNTDOWN 剩余时间显示

`_execute_reminder_task()` 中，对 COUNTDOWN 类型的任务，计算剩余时间：

```python
if task.task_type == TaskType.COUNTDOWN:
    target = task.scheduled_time
    if target:
        remaining = target - datetime.now()
        days = remaining.days
        hours = remaining.seconds // 3600
        text = task.params.get("text", "")
        reminder_text = f"{text}（距离目标还有 {days} 天 {hours} 小时）"
```

### 2.5 Skip API

在 `reminder_api.py` 新增端点：

```python
@reminder_bp.route("/api/reminder/skip", methods=["POST"])
def skip_reminder():
    """跳过一条提醒（标记为 SKIPPED，递增 skip_count）"""
    uid = g.user.get("uid", 0)
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    # 验证权限 → task.status = SKIPPED → task.skip_count += 1 → _save_task
    # 周期性 HABIT/DAILY_PLAN: 自动排下一次
```

### 2.6 Standby 推送

当前 standby 下，`_handle_task_result` 通过 `db.append_messages` 注入系统消息。standby 时管线不运行，所以需要：

在 `maintenance/system.py` 的 `_check_reminders_during_standby` 中加入一个检查线程（或利用现有 scheduler 线程），在 standby 下仍然执行 `scheduler.run_pending()`。当前 `_run_scheduler` 是独立线程，不受 standby 状态影响——它确实会触发 `_execute_reminder_task()` 并将结果写入数据库。但 `_handle_task_result` 中的 `db.append_messages` 可能被跳过（因为 `process_task_completion` 队列在 boot.py 中始终运行）。

实际检查：`boot.py:process_task_completion` 是一个 `while True` 线程，它读取 `completion_queue` 并处理。这个线程不受 standby 影响。所以当提醒触发时，任务结果会通过队列 → `_handle_reminder_completion` → `db.append_messages` 写入对话。这实际上是**已经能在 standby 下工作**的。

需要验证的是：前端或客户端在 standby 下是否轮询新消息。如果客户端在 standby 下不拉取，提醒就"到不了用户"。这个问题涉及前端行为，不在本次后端改造范围内。后端部分只需确保 `process_task_completion` 在 standby 下也处理提醒队列。

### 2.7 DAILY_PLAN ↔ PlanPlugin 联动

当 DAILY_PLAN 提醒触发时，不仅发送提醒文本，还应触发 PlanPlugin 生成今日计划。

在 `_execute_reminder_task()` 中，对 DAILY_PLAN 类型额外调用 PlanEngine：

```python
if task.task_type == TaskType.DAILY_PLAN:
    try:
        from plan_engine import PlanEngine
        from plan_store import PlanStore
        store = PlanStore(self.db)
        engine = PlanEngine(store)
        tasks = engine.generate_daily_plan(task.user_id, date.today().isoformat())
        if tasks:
            plan_text = "\n".join([f"  ☐ {t.title} ({t.duration_min}min)" for t in tasks])
            reminder_text += f"\n今日计划:\n{plan_text}"
    except Exception as e:
        self.logger.error("生成每日计划失败: %s", e)
```

---

## 3. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tasks.py` | 修改 +50 行 | 新增 DAILY_PLAN / PERIODIC 枚举和调度, COUNTDOWN 剩余时间 |
| `plugins/builtin/task_plugin.py` | 修改 +40 行 | `_create_daily_plan()`, `_create_periodic()`, 标签解析 |
| `reminder_api.py` | 修改 +30 行 | 新增 `POST /api/reminder/skip` |
| `requirements.txt` | 修改 +1 行 | 新增 `croniter` 依赖 |

---

## 4. 实施顺序

1. `tasks.py`: `TaskType` 补充 DAILY_PLAN / PERIODIC
2. `tasks.py`: `_schedule_reminder_task()` 处理新类型
3. `tasks.py`: `_execute_reminder_task()` COUNTDOWN 剩余时间 + DAILY_PLAN plan 生成
4. `task_plugin.py`: `_create_daily_plan()`, `_create_periodic()`
5. `reminder_api.py`: `POST /api/reminder/skip`
6. `requirements.txt`: 加 `croniter`

---

*策划案 v1.0*
