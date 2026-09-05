# server.py — DSN-exp harness 复刻的 DenseChat WebUI 服务端。
#
# 协议与 ~/dekacode/webui/server.py 对齐，并扩展：
#   - /api/config、/api/providers、/api/skills、/api/stats
#   - /api/diff/preview、/api/diff/apply
#   - /api/sessions 的删除/更新
# 后端由 apps.densechat.engine 中的 harness 引擎驱动。

from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.staticfiles import StaticFiles
import uvicorn
from dotenv import load_dotenv

from apps.densechat.engine import DenseChatEngine, DenseChatSession
from harness.models.base import ChatMessage

COMMANDS = [
    {"cmd": "/mode", "desc": "Switch agent / oneshot mode"},
    {"cmd": "/help", "desc": "Show available commands"},
    {"cmd": "/clear", "desc": "Clear current conversation"},
    {"cmd": "/stats", "desc": "Show context stats"},
    {"cmd": "/cost", "desc": "Show session token cost"},
    {"cmd": "/retry", "desc": "Retry last input"},
    {"cmd": "/undo", "desc": "Undo last turn"},
    {"cmd": "/export", "desc": "Export current session to JSON format"},
    {"cmd": "/rename", "desc": "Rename current session summary (/rename <new_name>)"},
]


def _safe_project_path(engine: DenseChatEngine, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(engine.project_root) / p
    p = p.resolve()
    root = Path(engine.project_root).resolve()
    if not str(p).startswith(str(root)):
        raise HTTPException(status_code=403, detail="越权访问：路径超出工作区")
    return p


GROUP_CHAT_PROFILE = "random"


def _resolve_identity(engine: DenseChatEngine, token: str) -> "Identity":
    """解析 WebSocket 连接身份：有效 token → 用户；否则匿名。"""
    from harness.auth import Identity
    if token:
        user = engine.users.resolve_token(token)
        if user is not None:
            return Identity(
                uid=user.uid, nickname=user.nickname or user.username,
                source="session",
                extra={"username": user.username},
            )
    return Identity(uid="anon", nickname="匿名", source="anonymous")


def _identity_name(identity) -> str:
    """发言者显示名（Identity 没有username属性，避免 AttributeError）。"""
    nickname = getattr(identity, "nickname", "") or ""
    if nickname:
        return nickname
    extra = getattr(identity, "extra", None) or {}
    return extra.get("username") or "匿名"


def _room_members_payload(room) -> list[dict]:
    return [m.to_dict() for m in room.members.values()]


async def _handle_ws_group(websocket: WebSocket, engine: DenseChatEngine,
                           identity, profile_id: str) -> None:
    """多人群聊：房间 + 成员 + 广播 + AI 回复。

    支持在群聊内发送 new_session(profile != random) 动态切回单人模式。
    返回时 websocket 仍可用（由调用方决定后续走向）。
    """
    import time as _time
    import secrets as _secrets

    # random 模式 = 全服务器共享的公共群聊房间；同一 profile 的所有用户进入同一房间
    room = engine.group_chat.get_or_create(f"group:{profile_id}", profile_id)
    # 服务器重启后从持久化恢复房间历史
    if not room.messages:
        room.messages = engine.load_group_history(profile_id)
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    room.add_subscriber(queue)
    member_id = f"{identity.uid}:{_secrets.token_hex(4)}"
    member = room.join(member_id, identity)
    display_name = _identity_name(identity)

    async def send(**data) -> bool:
        try:
            await asyncio.wait_for(websocket.send_json(data), timeout=15)
            return True
        except Exception:
            return False

    pump_task: asyncio.Task | None = None

    def cleanup() -> None:
        room.leave(member_id)
        room.remove_subscriber(queue)
        if pump_task is not None:
            pump_task.cancel()

    async def announce_left() -> None:
        try:
            await room.publish({
                "type": "member_left", "member_id": member_id,
                "name": display_name,
                "members": _room_members_payload(room),
            })
        except Exception:
            pass

    async def pump() -> None:
        while True:
            ev = await queue.get()
            try:
                await websocket.send_json(ev)
            except Exception:
                return

    pump_task = asyncio.create_task(pump())
    await send(
        type="room_joined", room_id=room.id, profile=profile_id,
        member_id=member_id,
        members=_room_members_payload(room),
        history=[
            {"role": m.role, "name": m.name, "content": m.content}
            for m in room.messages[-50:]
        ],
    )
    await room.publish({
        "type": "member_joined", "member": member.to_dict(),
        "members": _room_members_payload(room),
        "room_id": room.id,
    })

    switch_to_single: dict | None = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type", "")
            if msg_type == "message":
                content = (msg.get("content") or "").strip()
                if not content:
                    continue
                name = _identity_name(identity)
                user_msg = ChatMessage(role="user", content=content, name=name)
                room.add_message(user_msg)
                engine.persist_group_message(room, user_msg)
                await room.publish({
                    "type": "chat_message", "role": "user", "name": name,
                    "uid": identity.uid, "content": content,
                    "ts": _time.time(),
                })
                # 触发 AI 群聊回复（同一房间串行；忙时自动排队）
                await engine.try_group_reply(room)
            elif msg_type == "stop":
                stopped = engine.stop_group_reply(room)
                await send(type="stopped", group=True, cancelled=stopped)
            elif msg_type == "new_session":
                # 群聊内切换到其他任务模式 → 退出房间转单人模式
                if msg.get("profile") != GROUP_CHAT_PROFILE:
                    switch_to_single = msg
                    break
                # 已经在群聊房间：忽略
            elif msg_type == "leave":
                break
    except WebSocketDisconnect:
        pass
    finally:
        cleanup()
        await announce_left()

    if switch_to_single is not None:
        # 交给单人模式处理这条 new_session（同一连接继续使用）
        await _handle_ws_single(websocket, engine, identity, switch_to_single)


async def _handle_ws_single(websocket: WebSocket, engine: DenseChatEngine,
                            identity, first_msg: dict) -> None:
    """单人会话：现有 /ws 消息协议。

    支持发 new_session(profile == random) 动态切入群聊模式。
    """
    session: DenseChatSession = engine.new_session()
    session.user_id = identity.uid if identity.uid != "anon" else None
    # 当前正在运行的消息处理任务：message 放入独立任务，stop 才能即时取消，
    # 否则 process_message（可能跑很久）会把 stop 消息堵在收件队列里。
    process_task: asyncio.Task | None = None
    switch_to_group = False

    async def send(**data) -> bool:
        try:
            # 给 send 加超时：如果前端停止读取导致发送缓冲区满，
            # 不让服务端永久阻塞在 drain() 上。
            await asyncio.wait_for(websocket.send_json(data), timeout=15)
            return True
        except Exception:
            return False

    async def handle(msg: dict) -> None:
        nonlocal session, process_task, switch_to_group
        msg_type = msg.get("type", "")
        # 单人模式下切到群聊任务模式 → 交给群聊 handler
        if msg_type == "new_session" and msg.get("profile") == GROUP_CHAT_PROFILE:
            if process_task is not None and not process_task.done():
                process_task.cancel()
            switch_to_group = True
            return
        # stop：立即中止正在运行的消息处理，而不是等它自然结束
        if msg_type == "stop":
            session.stop()
            if process_task is not None and not process_task.done():
                process_task.cancel()
            await send(type="stopped")
            return
        # message：放进独立任务，主循环继续收消息（否则 stop 永远排不到）
        if msg_type == "message":
            if process_task is not None and not process_task.done():
                await send(type="error", content="正在处理上一条消息，请稍候")
                return
            process_task = asyncio.create_task(
                _dispatch_ws_message(msg, session, send, engine, identity))
            try:
                await process_task
            except asyncio.CancelledError:
                pass  # 被 stop 取消
            except Exception:
                traceback.print_exc()
                await send(type="error", content="处理失败: Internal server error")
            return
        # 每条消息独立 try/except：任何未预期异常都只回一个错误，
        # 不会把整个 WebSocket 连接打掉（避免“发完消息就断连”）。
        try:
            session = await _dispatch_ws_message(msg, session, send, engine, identity)
        except Exception:
            traceback.print_exc()
            await send(type="error", content="处理失败: Internal server error")

    try:
        await handle(first_msg)
        if switch_to_group:
            await _handle_ws_group(websocket, engine, identity, GROUP_CHAT_PROFILE)
            return
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send(type="error", content="Invalid JSON")
                continue
            await handle(msg)
            if switch_to_group:
                await _handle_ws_group(websocket, engine, identity, GROUP_CHAT_PROFILE)
                return
    except WebSocketDisconnect:
        if process_task is not None and not process_task.done():
            process_task.cancel()
    except Exception:
        traceback.print_exc()
        try:
            await send(type="error", content="Internal server error")
        except Exception:
            pass


def create_app(engine: DenseChatEngine) -> FastAPI:
    app = FastAPI(title="DSN DenseChat WebUI")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = ""):
        await websocket.accept()
        identity = _resolve_identity(engine, token)
        # 等待首条消息：决定走单人会话还是多人群聊
        raw = await websocket.receive_text()
        try:
            first = json.loads(raw)
        except json.JSONDecodeError:
            first = {"type": "new_session"}
        if first.get("type") == "new_session" and \
                first.get("profile") == GROUP_CHAT_PROFILE:
            await _handle_ws_group(websocket, engine, identity, GROUP_CHAT_PROFILE)
        else:
            await _handle_ws_single(websocket, engine, identity, first)


    # ── 基础信息 ──

    @app.get("/api/status")
    async def status():
        return {
            "model": engine.model_display,
            "project": engine.project_root,
            "symbols": engine.graph.total_symbols() if engine.graph else 0,
            "files": len(engine.graph.files) if engine.graph else 0,
            "enable_users": engine.config.enable_users,
            "group_chat_profile": GROUP_CHAT_PROFILE,
        }

    @app.get("/api/commands")
    async def list_commands():
        return COMMANDS

    # ── 用户系统（注册 / 登录 / 登出 / 当前用户） ──

    @app.get("/api/auth/me")
    async def auth_me(token: str = ""):
        user = engine.users.resolve_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail="未登录或登录已过期")
        return {"user": user.to_dict()}

    @app.post("/api/auth/register")
    async def auth_register(request: Request):
        data = await request.json()
        try:
            user = engine.users.register(
                str(data.get("username", "")).strip(),
                str(data.get("password", "")),
                str(data.get("nickname", "")).strip(),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        token = engine.users.issue_token(user.uid)
        return {"token": token, "user": user.to_dict()}

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        data = await request.json()
        user = engine.users.authenticate(
            str(data.get("username", "")).strip(),
            str(data.get("password", "")),
        )
        if user is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = engine.users.issue_token(user.uid)
        return {"token": token, "user": user.to_dict()}

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        data = await request.json()
        engine.users.revoke_token(str(data.get("token", "")))
        return {"ok": True}

    @app.get("/api/profiles")
    async def list_task_profiles():
        """返回可用任务模式（欢迎页滑条的数据源）。"""
        return {"profiles": engine.list_profiles()}

    @app.get("/api/balance")
    async def balance():
        return {}

    @app.get("/api/models")
    async def list_models():
        return engine.list_models()

    @app.get("/api/options")
    async def get_options():
        return {"thinking_collapsed_default": engine.config.thinking_collapsed_default}

    @app.post("/api/options")
    async def set_options(request: Request):
        data = await request.json()
        if "thinking_collapsed_default" in data:
            engine.update_config("thinking_collapsed_default", data["thinking_collapsed_default"])
        return {"thinking_collapsed_default": engine.config.thinking_collapsed_default}

    # ── 配置 / Provider / 技能 / 统计 ──

    @app.get("/api/config")
    async def get_config():
        return engine.get_config()

    @app.post("/api/config")
    async def set_config(request: Request):
        data = await request.json()
        key = data.get("key", "")
        value = data.get("value")
        if not key:
            raise HTTPException(status_code=400, detail="缺少 key")
        try:
            result = engine.update_config(key, value)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        if key in ("skills_dir", "enable_skills"):
            engine.reload_skills()
        return result

    @app.get("/api/providers")
    async def get_providers():
        return {"providers": engine.providers()}

    @app.post("/api/providers")
    async def update_provider(request: Request):
        data = await request.json()
        provider = engine.update_provider(data)
        return {"provider": provider}

    @app.delete("/api/providers/{provider_id}")
    async def delete_provider(provider_id: str):
        try:
            engine.delete_provider(provider_id)
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"success": True, "providers": engine.providers()}

    @app.get("/api/skills")
    async def get_skills():
        return {
            "report": engine.skill_report,
            "tools": engine.tools.names(),
        }

    @app.post("/api/skills/reload")
    async def reload_skills():
        report = engine.reload_skills()
        return {"report": report, "tools": engine.tools.names()}

    @app.get("/api/prompts")
    async def get_prompts():
        return {"prompts": engine.list_prompts(), "system_prompt": engine.system_prompt}

    @app.post("/api/prompts")
    async def save_prompt(request: Request):
        data = await request.json()
        name = data.get("name", "")
        content = data.get("content", "")
        if not name:
            raise HTTPException(status_code=400, detail="缺少 name")
        engine.save_prompt(name, content)
        return {"success": True, "prompts": engine.list_prompts(),
                "system_prompt": engine.system_prompt}

    @app.post("/api/prompts/reload")
    async def reload_prompts():
        files = engine.reload_prompts()
        return {"prompts": files, "system_prompt": engine.system_prompt}

    @app.get("/api/stats")
    async def get_stats():
        return engine.compute_stats()

    # ── Diff 可视化编辑器 ──

    @app.post("/api/diff/preview")
    async def diff_preview(request: Request):
        data = await request.json()
        path = data.get("path", "")
        if not path:
            raise HTTPException(status_code=400, detail="缺少 path")
        p = _safe_project_path(engine, path)
        original = p.read_text(encoding="utf-8") if p.is_file() else ""
        new_content = data.get("content", original)
        return {"path": str(p), "original": original, "content": new_content}

    @app.post("/api/diff/apply")
    async def diff_apply(request: Request):
        data = await request.json()
        path = data.get("path", "")
        content = data.get("content", "")
        if not path:
            raise HTTPException(status_code=400, detail="缺少 path")
        p = _safe_project_path(engine, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(p), "bytes": len(content.encode("utf-8"))}

    # ── 工作区 / 会话 ──

    @app.get("/api/workspaces")
    async def list_workspaces():
        return {"workspaces": engine.store.list_workspaces()}

    @app.post("/api/workspaces")
    async def open_workspace(request: Request):
        data = await request.json()
        path = data.get("path", "")
        if not path:
            raise HTTPException(status_code=400, detail="缺少 path")
        wid = engine.set_workspace(path)
        ws = next(w for w in engine.store.list_workspaces() if w["id"] == wid)
        return {"workspace": ws}

    @app.post("/api/workspaces/resolve")
    async def resolve_workspace(request: Request):
        """按文件夹名 + 内部样例文件，在常见根目录下查找候选绝对路径。"""
        data = await request.json()
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 name")
        sample_paths = data.get("samplePaths") or []

        import os
        roots = []
        home = Path.home()
        for r in (home, Path(engine.project_root)):
            if r not in roots:
                roots.append(r)
        for extra in ("/Users", "/home", os.path.expanduser("~")):
            p = Path(extra)
            if p.exists() and p not in roots:
                roots.append(p)

        matches: list[str] = []
        seen: set[str] = set()

        def leaf_exists(base: Path, rel: str) -> bool:
            try:
                return (base / rel).exists()
            except (OSError, ValueError):
                return False

        def walk(base: Path, depth: int):
            if depth > 4 or len(matches) > 50:
                return
            try:
                entries = sorted(base.iterdir(), key=lambda x: x.name.lower())
            except (OSError, PermissionError):
                return
            for entry in entries:
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                if entry.name == name:
                    rp = str(entry.resolve())
                    # 有 sample 时优先只保留能命中样例的候选
                    if not sample_paths or all(leaf_exists(entry, rel) for rel in sample_paths):
                        if rp not in seen:
                            seen.add(rp)
                            matches.append(rp)
                    # 即使样例不命中，也记下同名目录作为兜底候选
                    elif rp not in seen:
                        seen.add(rp)
                        matches.append(rp)
                if depth < 4:
                    walk(entry, depth + 1)

        for root in roots:
            walk(root, 0)

        return {"candidates": matches[:50]}

    @app.get("/api/fs/list")
    async def fs_list(request: Request):
        """服务器端目录浏览（兜底选择工作区用）。"""
        raw = request.query_params.get("path", "/")
        try:
            root = Path(raw).expanduser()
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="非法路径")
        if not root.is_absolute():
            root = Path(engine.project_root) / root
        root = root.resolve()
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="不是目录")
        try:
            dirs = sorted(
                [{"name": e.name, "path": str(e)} for e in root.iterdir()
                 if e.is_dir() and not e.name.startswith(".")],
                key=lambda x: x["name"].lower(),
            )[:500]
        except (OSError, PermissionError):
            dirs = []
        return {"path": str(root), "dirs": dirs}

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        workspace_id = request.query_params.get("workspace_id")
        token = request.query_params.get("token", "")
        user = engine.users.resolve_token(token) if token else None
        user_id = user.uid if user else None
        return engine.store.list_sessions(
            limit=200, workspace_id=workspace_id, user_id=user_id)

    def _session_allowed(session_id: str, request: Request) -> None:
        """会话归属检查：会话有 owner 且请求者不是本人 → 403。"""
        owner = engine.store.get_session_user(session_id)
        if not owner:
            return  # 匿名/旧会话不限制
        token = request.query_params.get("token", "")
        user = engine.users.resolve_token(token) if token else None
        if user is None or user.uid != owner:
            raise HTTPException(status_code=403, detail="无权访问该会话")

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str, request: Request):
        _session_allowed(session_id, request)
        msgs = engine.store.load_messages(session_id)
        result = []
        for m in msgs:
            item = {"role": m.role, "content": m.content}
            if m.reasoning_content:
                item["reasoning_content"] = m.reasoning_content
            if m.tool_calls:
                item["tool_calls"] = [
                    {"name": tc.get("function", {}).get("name", ""),
                     "args": tc.get("function", {}).get("arguments", "")}
                    for tc in m.tool_calls
                ]
            if m.role == "tool":
                item["name"] = m.name
            result.append(item)
        return result

    @app.get("/api/sessions/{session_id}/export")
    async def export_session(session_id: str, request: Request):
        _session_allowed(session_id, request)
        msgs = engine.store.load_messages(session_id)
        if not msgs:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "exported_at": __import__("datetime").datetime.now().isoformat(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                    "reasoning_content": m.reasoning_content,
                }
                for m in msgs
            ],
        }

    @app.post("/api/sessions/import")
    async def import_session(request: Request):
        data = await request.json()
        messages = data.get("messages", [])
        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空")
        workspace_id = data.get("workspace_id") or engine.workspace_id
        token = (data.get("token") or
                 request.query_params.get("token", ""))
        user = engine.users.resolve_token(token) if token else None
        sid = engine.store.create_session(
            workspace_id=workspace_id, profile=data.get("profile") or None,
            user_id=user.uid if user else None)
        chat_msgs = []
        for m in messages:
            chat_msgs.append(ChatMessage(
                role=str(m.get("role", "user")),
                content=str(m.get("content", "")),
                tool_calls=m.get("tool_calls") or [],
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                reasoning_content=m.get("reasoning_content"),
            ))
        engine.store.set_session(sid)
        engine.store.save_messages(chat_msgs, session_id=sid)
        if data.get("summary"):
            engine.store.update_summary(str(data["summary"]), sid)
        return {"success": True, "session_id": sid}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request):
        _session_allowed(session_id, request)
        engine.store.delete_session(session_id)
        return {"success": True}

    @app.patch("/api/sessions/{session_id}")
    async def update_session(session_id: str, request: Request):
        _session_allowed(session_id, request)
        data = await request.json()
        if "summary" in data:
            engine.store.update_summary(str(data["summary"]), session_id)
        return {"success": True}

    # 静态前端（与 ~/dekacode/webui/static 对齐）
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app


async def _handle_command(cmd: str, session: DenseChatSession, send) -> None:
    parts = cmd.split()
    command = parts[0]

    if command == "/help":
        lines = [f"  {c['cmd']}  {c['desc']}" for c in COMMANDS]
        await send(type="command_output", content="Available commands:\n" + "\n".join(lines))

    elif command == "/mode":
        if len(parts) > 1:
            try:
                session.mode.switch(parts[1])
            except ValueError:
                await send(type="command_output",
                           content=f"Invalid mode '{parts[1]}'. Use 'agent' or 'oneshot'.")
                return
        else:
            session.mode.switch("oneshot" if session.mode.is_agent else "agent")
        mode = session.mode.mode.value
        await send(type="mode_changed", mode=mode)
        hint = " Use @req/@sym/@grep/@ls/@tree" if mode == "oneshot" else ""
        await send(type="command_output", content=f"Mode switched to: {mode}.{hint}")

    elif command == "/clear":
        session.messages.clear()
        session._saved_len = 0
        await send(type="command_output", content="Conversation cleared.")
        await send(type="context_update", context=session.context_snapshot())

    elif command == "/stats":
        stats = session.context_stats
        await send(type="command_output",
                   content=f"Context: history={stats['history']} total={stats['total']}")

    elif command == "/cost":
        if not session.session_id:
            await send(type="command_output", content="No usage recorded yet.")
            return
        records = session.engine.store.load_usage(session.session_id)
        if not records:
            await send(type="command_output", content="No usage recorded yet.")
            return
        total_in = sum(r.get("input_tokens", 0) or 0 for r in records)
        total_out = sum(r.get("output_tokens", 0) or 0 for r in records)
        total_cost = sum(float(r.get("cost", 0) or 0) for r in records)
        await send(type="command_output",
                   content=f"Tokens: {total_in} in, {total_out} out  Cost: ¥{total_cost:.4f}")

    elif command == "/retry":
        if session._last_input:
            await session.process_message(session._last_input, send)
        else:
            await send(type="command_output", content="No previous input to retry.")

    elif command == "/undo":
        user_indexes = [i for i, m in enumerate(session.messages) if m.role == "user"]
        if not user_indexes:
            await send(type="command_output", content="Nothing to undo.")
            return
        keep = user_indexes[-1]
        session.messages = session.messages[:keep]
        session._saved_len = min(session._saved_len, len(session.messages))
        if session.session_id:
            store = session.engine.store
            store.store.execute("DELETE FROM messages WHERE session_id = ?", (session.session_id,))
            store.set_session(session.session_id)
            store.save_messages(session.messages, session_id=session.session_id)
            session._saved_len = len(session.messages)
        await send(type="command_output", content="Undone.")
        await send(type="context_update", context=session.context_snapshot())

    elif command == "/export":
        if not session.session_id:
            await send(type="command_output", content="Session is not saved yet.")
            return
        await send(type="command_output", content=f"Export URL: /api/sessions/{session.session_id}/export")

    elif command == "/rename":
        if len(parts) < 2:
            await send(type="command_output", content="Usage: /rename <new_name>")
            return
        new_name = " ".join(parts[1:]).strip()
        if session.session_id:
            session.engine.store.update_summary(new_name, session.session_id)
            await send(type="command_output", content=f"Session renamed to: {new_name}")
            await send(type="context_update", context=session.context_snapshot())
        else:
            await send(type="command_output", content="Session not yet persisted.")

    else:
        await send(type="command_output", content=f"Unknown command: {command}. Type /help for available commands.")


async def _dispatch_ws_message(
    msg: dict,
    session: DenseChatSession,
    send,
    engine,
    identity=None,
) -> DenseChatSession:
    msg_type = msg.get("type", "")

    if msg_type == "message":
        text = (msg.get("content") or "").strip()
        if not text:
            return session
        if text.startswith("/"):
            await _handle_command(text, session, send)
        else:
            await session.process_message(text, send)
            await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "stop":
        session.stop()

    elif msg_type == "temp_session":
        session = engine.new_session()
        if identity is not None:
            session.user_id = identity.uid if identity.uid != "anon" else None
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "restore_session":
        session = engine.new_session()
        if identity is not None:
            session.user_id = identity.uid if identity.uid != "anon" else None
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "new_session":
        workspace_id = msg.get("workspace_id")
        profile_id = msg.get("profile")
        if workspace_id and workspace_id != engine.workspace_id:
            path = engine.store.get_workspace_path(workspace_id)
            if path:
                engine.set_workspace(path)
        session = engine.new_session(profile_id=profile_id)
        if identity is not None:
            session.user_id = identity.uid if identity.uid != "anon" else None
        if workspace_id:
            session.workspace_id = workspace_id
        else:
            # 直接点击“新会话”= 全局会话（不绑定具体项目）
            session.workspace_id = None
        await send(type="session_new", session_id=None,
                   profile=session.profile_id,
                   workspace_id=session.workspace_id, path=engine.project_root)
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "open_workspace":
        path = msg.get("path", "")
        if path:
            wid = engine.set_workspace(path)
            session = engine.new_session()
            if identity is not None:
                session.user_id = identity.uid if identity.uid != "anon" else None
            session.workspace_id = wid
            await send(type="workspace_opened", workspace_id=wid, path=engine.project_root)
            await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "load_session":
        sid = msg.get("session_id", "")
        uid = identity.uid if identity is not None else None
        try:
            loaded = await asyncio.to_thread(session.load_session, sid, uid)
        except PermissionError as e:
            await send(type="error", content=str(e))
            return session
        if loaded:
            if session.workspace_id and session.workspace_id != engine.workspace_id:
                path = engine.store.get_workspace_path(session.workspace_id)
                if path:
                    engine.set_workspace(path)
                    session.workspace_id = engine.workspace_id
            await send(
                type="session_loaded",
                session_id=sid,
                mode=session.mode.mode.value,
                profile=session.profile_id,
                count=len(session.messages),
            )
            await send(type="context_update", context=session.context_snapshot())
        else:
            await send(type="error", content=f"Session not found: {sid}")

    elif msg_type == "mode":
        mode = msg.get("mode", "agent")
        try:
            session.mode.switch(mode)
        except ValueError:
            session.mode.switch("agent" if session.mode.is_agent else "oneshot")
        await send(type="mode_changed", mode=session.mode.mode.value)

    elif msg_type == "switch_model":
        model_id = msg.get("model", "flash")
        try:
            display = engine.switch_model(model_id)
            await send(type="model_switched", model=model_id, display=display)
        except Exception as e:
            await send(type="error", content=f"Failed to switch model: {e}")

    return session


def main() -> None:
    # 必须先加载 .env，否则下面 argparse default 里的 os.getenv 在求值时
    # 读不到 DENSECHAT_MAX_STEPS / DENSECHAT_PORT 等，会退回到内置默认值
    # （比如 max_steps=12），把 .env 里的 99999 直接覆盖掉。
    load_dotenv()

    parser = argparse.ArgumentParser(description="DSN-exp DenseChat WebUI")
    parser.add_argument("--host", default=os.getenv("DENSECHAT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DENSECHAT_PORT", "8080")))
    parser.add_argument("--project", default=os.getenv("DENSECHAT_PROJECT") or os.getcwd())
    # default=None：未显式传 --max-steps 时交给 DenseChatConfig.from_env 读取
    #（已加载 .env），避免默认 12 覆盖 env 配置。0 / 负数 = 不限制执行步数。
    parser.add_argument("--max-steps", type=int, default=None,
                        help="Agent 最大工具调用步数；0 或负数表示不限制"
                             "（默认取 DENSECHAT_MAX_STEPS）")
    args = parser.parse_args()

    print(f"  DSN DenseChat WebUI (harness base)")
    print(f"  Project: {args.project}")
    engine = DenseChatEngine(project_root=args.project, max_steps=args.max_steps)
    app = create_app(engine)
    print(f"  Ready  http://{args.host}:{args.port}  model={engine.model_display}"
          f"  max_steps={engine.max_steps if engine.max_steps > 0 else 'unlimited'}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
