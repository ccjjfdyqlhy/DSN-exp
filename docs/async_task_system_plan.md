# 异步任务系统策划案 — 前端心跳轮询模式

> 版本: v1.0 | 日期: 2026-06-29

---

## 目录

1. [问题与目标](#1-问题与目标)
2. [总体架构](#2-总体架构)
3. [交互流程](#3-交互流程)
4. [后端设计](#4-后端设计)
5. [前端设计](#5-前端设计)
6. [API 定义](#6-api-定义)
7. [实施计划](#7-实施计划)

---

## 1. 问题与目标

### 1.1 现状

当前所有 AI 任务在 HTTP 连接生命周期内同步完成：

```
用户请求 → Pipeline(过滤→提示词→模型调用→后处理→TTS) → 返回回复
```

对于需要长时间执行的任务（扫描文档、批量 OCR、Git 大仓库操作、深度推理），此模式导致：

| 问题 | 影响 |
|------|------|
| HTTP 连接持续占用 | 代理服务器/网关超时（常见 60s-120s） |
| 前端空白等待 | 用户体验差，无进度反馈 |
| 流式 SSE 阻塞 | 一个慢任务拖垮后续请求 |
| 资源无法释放 | worker/线程被长时间占用 |

### 1.2 目标

设计前后端协同的异步任务系统：

```
用户请求 → 创建异步任务 → 后端立即返回 task_id
→ 后端后台执行任务 → 前端每 30s 轮询心跳接口
→ 任务完成 → 前端显示回复 + TTS 音频
```

### 1.3 适用场景

| 场景 | 当前耗时 | 异步化后 |
|------|---------|---------|
| OCR 批量文档处理 | 30s-5min | 2s 返回 task_id |
| Git clone 大仓库 | 10s-2min | 1s 返回 task_id |
| 深度推理 (reasoner) | 10s-60s | 1s 返回 task_id |
| Web 搜索多轮聚合 | 15s-40s | 1s 返回 task_id |
| 批量文件操作 | 5s-30s | 1s 返回 task_id |

---

## 2. 总体架构

```
┌─────────────────────┐          ┌──────────────────────┐
│     前端             │          │     后端              │
│                     │          │                       │
│  发送消息            │────POST──→  Pipeline 执行          │
│  POST /api/chat/    │          │   ↓ 模型调用            │
│  async_send         │          │   ↓ POST_PROCESS       │
│                     │          │   ↓ 检测"慢"工具调用    │
│                     │◂─返回────│   {task_id, status}    │
│                     │  task_id │                       │
│                     │          │                       │
│  ┌──────────┐       │          │  后端后台执行 Task      │
│  │ 轮询循环  │       │          │  ┌─────────────────┐  │
│  │ 每 30s   │────GET──────→    │  │ TaskManager      │  │
│  │ 查询状态  │       │          │  │ ├ reasoner       │  │
│  └────┬─────┘       │          │  │ ├ action         │  │
│       │             │          │  │ ├ scan/process   │  │
│       │◂─返回───────│          │  │ └ ...            │  │
│       │  {reply,    │          │  └─────────────────┘  │
│       │   audio,    │          │         ↓ 完成         │
│       │   status}   │          │  AsyncTaskStore 存储   │
│                     │          │  回复 + TTS 音频       │
│  显示回复 + 播放    │          │                       │
│  停止轮询           │          │                       │
└─────────────────────┘          └──────────────────────┘
```

### 2.1 核心概念

| 概念 | 说明 |
|------|------|
| **AsyncTask** | 一个异步执行的任务，包含输入、状态、输出 |
| **AsyncTaskStore** | 任务结果存储（内存 + SQLite） |
| **心跳接口** | `GET /api/task/status/<task_id>` 前端轮询入口 |
| **慢工具标记** | skill.yaml 中标记 `async: true` 的工具 |
| **任务切换点** | Pipeline 检测到慢工具调用 → 切换为异步模式 |

---

## 3. 交互流程

### 3.1 正常流程

```
前端                   后端                          TaskManager
 │                      │                              │
 │ POST /api/chat/      │                              │
 │ async_send           │                              │
 │─────────────────────→│                              │
 │                      │ Pipeline 执行到 MODEL_INVOKE   │
 │                      │ 模型返回 tool_calls            │
 │                      │ 检测 "process_scan" 等慢工具   │
 │                      │ ├ 创建 AsyncTask (status=run) │
 │                      │ │ 将执行结果存入 Store         │
 │                      │ └ 返回 {task_id, status}      │
 │◂────────────────────│                              │
 │                      │                              │
 │ ┌── 轮询循环 ──────  │                              │
 │ │ 每 30s             │                              │
 │ │───────────────────→│ GET /api/task/status/{id}    │
 │ │                    │ AsyncTaskStore.lookup(id)     │
 │ │                    │ → status=run → 返回空        │
 │ │◂──────────────────│ {"status": "running"}         │
 │ │                    │                              │
 │ │                    │         Task 完成             │
 │ │                    │◂─────────────────────────────│
 │ │                    │ ← store result (reply+audio) │
 │ │                    │                              │
 │ │───────────────────→│ GET /api/task/status/{id}    │
 │ │                    │ → status=done → 返回结果     │
 │ │◂──────────────────│ {reply, audio, status:done}  │
 │ │                    │                              │
 │ └── 停止轮询 ──────  │                              │
 │                      │                              │
 │ 显示回复 + 播放 TTS  │                              │
```

### 3.2 详细步骤

**步骤 1 — 前端发起异步请求**
```http
POST /api/chat/async_send
Content-Type: application/json

{
  "message": "扫描这堆文件",
  "chat_id": 1,
  "async": true
}
```

**步骤 2 — 后端创建任务并返回**
```json
// 202 Accepted
{
  "task_id": "async_abc123",
  "status": "running",
  "message": "任务已创建，稍后将通知你"
}
```

**步骤 3 — 前端轮询**
```http
GET /api/task/status/async_abc123
```

未完成：
```json
{"status": "running"}
```

已完成：
```json
{
  "status": "done",
  "reply": "扫描完成，共发现 5 页文档...",
  "audio": "<base64-wav>",
  "chat_id": 1,
  "task_id": "async_abc123"
}
```

**步骤 4 — 前端停止轮询，显示回复**

---

## 4. 后端设计

### 4.1 AsyncTaskStore

```python
# tasks/async_store.py

import json
import time
import threading
from datetime import datetime
from typing import Optional


class AsyncTaskRecord:
    """异步任务记录"""
    task_id: str
    user_id: int
    chat_id: int
    status: str          # "running" | "done" | "failed"
    reply: str = ""
    audio: bytes = b""
    audio_b64: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: str = ""


class AsyncTaskStore:
    """
    异步任务结果存储。
    
    双后端：
    - 内存 dict 用于快速读写
    - SQLite 用于持久化（服务重启后恢复）
    """

    def __init__(self, db=None):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._db = db
        self._init_db()

    def _init_db(self):
        if not self._db:
            return
        conn = self._db._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS async_tasks (
                task_id      TEXT PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                chat_id      INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'running',
                reply        TEXT DEFAULT '',
                audio_path   TEXT DEFAULT '',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                error        TEXT DEFAULT ''
            )
        """)
        conn.commit()

    def create(self, task_id: str, user_id: int, chat_id: int = 0) -> dict:
        record = {
            "task_id": task_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "status": "running",
            "reply": "",
            "audio": b"",
            "audio_b64": "",
            "created_at": datetime.now().isoformat(),
            "completed_at": "",
            "error": "",
        }
        with self._lock:
            self._tasks[task_id] = record
        if self._db:
            conn = self._db._get_connection()
            conn.execute(
                "INSERT INTO async_tasks (task_id, user_id, chat_id, status) "
                "VALUES (?, ?, ?, 'running')",
                (task_id, user_id, chat_id),
            )
            conn.commit()
        return record

    def complete(self, task_id: str, reply: str,
                  audio: bytes = b"", audio_b64: str = "",
                  error: str = "") -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return False
            record["status"] = "done" if not error else "failed"
            record["reply"] = reply
            record["audio"] = audio
            record["audio_b64"] = audio_b64
            record["completed_at"] = datetime.now().isoformat()
            record["error"] = error
        if self._db:
            conn = self._db._get_connection()
            conn.execute(
                "UPDATE async_tasks SET status=?, reply=?, error=?, "
                "completed_at=CURRENT_TIMESTAMP WHERE task_id=?",
                (record["status"], reply, error, task_id),
            )
            conn.commit()
        return True

    def lookup(self, task_id: str) -> Optional[dict]:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            # 返回摘要（不含音频 bytes），前端只需 audio_b64
            return {
                "task_id": record["task_id"],
                "status": record["status"],
                "reply": record.get("reply", ""),
                "audio_b64": record.get("audio_b64", ""),
                "error": record.get("error", ""),
            }
```

### 4.2 检测慢工具

在 Pipeline 中插入检查点：当模型返回的 tool_calls 包含标记为 `async: true` 的工具调用时，切换为异步模式。

```yaml
# skills/builtin/document/skill.yaml 示例

tools:
  - name: process_scan
    display_name: "处理扫描"
    description: "处理扫描结果：分类→OCR→2md→打包"
    async: true                  # ← 标记为慢工具
    estimated_duration: "30-300s"
    module: "tools.doc_tools"
    class: "DocTools"
    methods:
      - name: process_scan
        ...
```

```python
# Pipeline 切换逻辑

async def _check_async_mode(self, ctx, tool_calls: list) -> Optional[str]:
    """
    检查 tool_calls 是否包含慢工具。
    如果包含，创建 AsyncTask，后台执行，返回 task_id。
    如果不包含，返回 None，继续同步流程。
    """
    for tc in tool_calls:
        func_name = tc.get("function", {}).get("name", "")
        # 查询该工具是否标记为 async
        parts = func_name.split("-", 2)
        if len(parts) < 3:
            continue
        skill_name = parts[1]
        tool_name = parts[2]
        spec = self._skill_registry.get_tool_spec(skill_name, tool_name)
        if spec and spec.get("async"):
            return await self._start_async_execution(ctx, tool_calls)
    return None
```

### 4.3 异步任务创建接口

```python
# api/task.py — 异步任务蓝图的简化实现

import uuid
from flask import Blueprint, request, jsonify, current_app

task_bp = Blueprint("async_tasks", __name__)


@task_bp.route("/api/chat/async_send", methods=["POST"])
def async_send():
    """异步发送消息"""
    data = request.get_json()
    message = data.get("message", "")
    chat_id = data.get("chat_id", 0)
    user_id = current_app.config.get("USER_ID", 0)

    # 1. 运行 Pipeline（允许异步切换）
    engine = current_app.config.get("ENGINE")
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    task_id = f"async_{uuid.uuid4().hex[:12]}"
    store = engine.async_task_store

    # 2. 创建异步任务记录
    store.create(task_id, user_id, chat_id)

    # 3. 后台执行管线
    def _run():
        loop = asyncio.new_event_loop()
        try:
            ctx = PluginContext(user_id=user_id, message=message, chat_id=chat_id)
            # ... 简化：直接执行 pipeline
            result = engine.process_async(ctx, task_id)
            # 通过 SSE 或回调通知
        finally:
            loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({
        "task_id": task_id,
        "status": "running",
        "message": "任务已创建，稍后将通知你",
    }), 202


@task_bp.route("/api/task/status/<task_id>", methods=["GET"])
def task_status(task_id):
    """前端轮询心跳接口"""
    engine = current_app.config.get("ENGINE")
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    record = engine.async_task_store.lookup(task_id)
    if not record:
        return jsonify({"error": "Task not found"}), 404

    if record["status"] == "running":
        return jsonify({"status": "running"})

    # done / failed: 返回完整结果
    return jsonify(record)
```

### 4.4 Engine 集成

```python
# engine.py 新增

class DSNEngine:
    def __init__(self):
        ...
        self.async_task_store = AsyncTaskStore(db=self.db)

    def process_async(self, ctx: PluginContext,
                      task_id: str) -> Optional[str]:
        """
        异步执行管线：正常执行 Pipeline，但将结果写入 AsyncTaskStore。
        """
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ctx = loop.run_until_complete(self.pipeline.process(ctx))
        finally:
            loop.close()

        if not ctx.reply:
            self.async_task_store.complete(
                task_id, error="Pipeline returned empty reply"
            )
            return None

        audio_b64 = ctx.audio_b64 or ""
        audio = ctx.audio or b""
        self.async_task_store.complete(
            task_id, reply=ctx.reply,
            audio=audio, audio_b64=audio_b64,
        )
        return ctx.reply
```

---

## 5. 前端设计

### 5.1 轮询状态机

```
IDLE → POST /async_send → WAITING → 每 30s GET /task/status
                                        ↓
                                   status=running → 继续 WAITING
                                        ↓
                                   status=done → DISPLAY → IDLE
                                        ↓
                                   status=failed → SHOW_ERROR → IDLE
```

### 5.2 前端示例实现

```python
# minimal.py — 异步任务轮询

import time
import requests
import threading

_BASE_URL = "http://localhost:5000"
_HEADERS = {"Authorization": "Session ..."}


def send_async_message(text: str, chat_id: int = 0) -> str:
    """发送异步消息，返回 task_id"""
    resp = requests.post(
        f"{_BASE_URL}/api/chat/async_send",
        headers=_HEADERS,
        json={"message": text, "chat_id": chat_id},
    )
    data = resp.json()
    if resp.status_code == 202:
        return data["task_id"]
    raise RuntimeError(f"Async send failed: {data}")


def poll_task(task_id: str, interval: int = 30, timeout: int = 600):
    """轮询任务状态，返回结果"""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(
            f"{_BASE_URL}/api/task/status/{task_id}",
            headers=_HEADERS,
        )
        data = resp.json()
        if data.get("status") == "done":
            return data  # {reply, audio_b64, ...}
        if data.get("status") in ("failed",):
            raise RuntimeError(f"Task failed: {data.get('error')}")
        time.sleep(interval)
    raise TimeoutError("Task polling timeout")
```

### 5.3 关键设计点

| 点 | 说明 |
|----|------|
| 轮询间隔 | 30 秒，降低服务端压力 |
| 超时 | 600 秒（10 分钟），超时视为失败 |
| 非流式 TTS | 一次性返回 base64 WAV，前端解码播放 |
| 无 Agent 循环 | 异步任务执行完后直接存结果，不再回馈 LLM |
| 对话更新 | 任务完成后后端自动写 DB，前端刷新即可见历史 |

---

## 6. API 定义

### 6.1 发送异步消息

```
POST /api/chat/async_send
```

请求：
```json
{
  "message": "扫描这些文件",
  "chat_id": 1
}
```

响应 (202 Accepted)：
```json
{
  "task_id": "async_a1b2c3d4e5f6",
  "status": "running"
}
```

### 6.2 查询任务状态

```
GET /api/task/status/<task_id>
```

未完成：
```json
{"status": "running"}
```

已完成：
```json
{
  "status": "done",
  "task_id": "async_a1b2c3d4e5f6",
  "reply": "扫描完成...",
  "audio_b64": "...base64-wav...",
  "chat_id": 1,
  "error": ""
}
```

失败：
```json
{
  "status": "failed",
  "task_id": "async_a1b2c3d4e5f6",
  "error": "OCR service timeout",
  "reply": "处理失败：OCR 服务超时"
}
```

---

## 7. 实施计划

### Phase 1 — 基础存储 (1 天)

- [ ] `tasks/async_store.py`: AsyncTaskStore 实现（内存 + SQLite 双后端）
- [ ] 数据库表 `async_tasks`

### Phase 2 — 后端切换逻辑 (2 天)

- [ ] `engine.py`: 新增 `process_async()` 方法和 `async_task_store` 属性
- [ ] Pipeline 插入 `_check_async_mode()` 检测慢工具
- [ ] 慢工具标记机制：skill.yaml 增加 `async: true` 字段

### Phase 3 — API 接口 (1 天)

- [ ] `api/task.py`: `POST /api/chat/async_send` 和 `GET /api/task/status/<task_id>`
- [ ] Flask 蓝图注册

### Phase 4 — 前端适配 (1 天)

- [ ] minimal.py: 异步发送 + 轮询循环
- [ ] Web UI: JavaScript 轮询 + 结果显示

### Phase 5 — 技能适配 (1-2 天)

- [ ] `document/process_scan` → 标记 `async: true`
- [ ] `document/read_hmd` → 标记 `async: true`（大数据量时）
- [ ] `web_search/search` → 标记 `async: true`（多轮搜索）
- [ ] `github/*` → 标记 `async: true`（大仓库操作）

**总工期预估: 6-7 天**
