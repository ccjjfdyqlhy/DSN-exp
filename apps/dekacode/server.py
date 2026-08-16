# server.py — DSN-exp harness 复刻的 Dekacode WebUI 服务端。
#
# 协议与 ~/dekacode/webui/server.py 对齐，并扩展：
#   - /api/config、/api/providers、/api/skills、/api/stats
#   - /api/diff/preview、/api/diff/apply
#   - /api/sessions 的删除/更新
# 后端由 apps.dekacode.engine 中的 harness 引擎驱动。

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.staticfiles import StaticFiles
import uvicorn

from apps.dekacode.engine import DekacodeEngine, DekacodeSession
from harness.models.base import ChatMessage

COMMANDS = [
    {"cmd": "/mode", "desc": "Switch agent / oneshot mode"},
    {"cmd": "/help", "desc": "Show available commands"},
    {"cmd": "/clear", "desc": "Clear current conversation"},
    {"cmd": "/stats", "desc": "Show context stats"},
    {"cmd": "/cost", "desc": "Show session token cost"},
    {"cmd": "/retry", "desc": "Retry last input"},
    {"cmd": "/undo", "desc": "Undo last turn"},
]


def _safe_project_path(engine: DekacodeEngine, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(engine.project_root) / p
    p = p.resolve()
    root = Path(engine.project_root).resolve()
    if not str(p).startswith(str(root)):
        raise HTTPException(status_code=403, detail="越权访问：路径超出工作区")
    return p


def create_app(engine: DekacodeEngine) -> FastAPI:
    app = FastAPI(title="DSN Dekacode WebUI")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        session: DekacodeSession = engine.new_session()

        async def send(**data) -> bool:
            try:
                await websocket.send_json(data)
                return True
            except Exception:
                return False

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await send(type="error", content="Invalid JSON")
                    continue

                # 每条消息独立 try/except：任何未预期异常都只回一个错误，
                # 不会把整个 WebSocket 连接打掉（避免“发完消息就断连”）。
                try:
                    await _dispatch_ws_message(msg, session, send, engine)
                except Exception:
                    traceback.print_exc()
                    await send(type="error", content="处理失败: Internal server error")

        except WebSocketDisconnect:
            pass
        except Exception:
            traceback.print_exc()
            try:
                await send(type="error", content="Internal server error")
            except Exception:
                pass


    # ── 基础信息 ──

    @app.get("/api/status")
    async def status():
        return {
            "model": engine.model_display,
            "project": engine.project_root,
            "symbols": engine.graph.total_symbols() if engine.graph else 0,
            "files": len(engine.graph.files) if engine.graph else 0,
        }

    @app.get("/api/commands")
    async def list_commands():
        return COMMANDS

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

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        workspace_id = request.query_params.get("workspace_id")
        return engine.store.list_sessions(limit=200, workspace_id=workspace_id)

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        msgs = engine.store.load_messages(session_id)
        result = []
        for m in msgs:
            item = {"role": m.role, "content": m.content}
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
    async def export_session(session_id: str):
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
        sid = engine.store.create_session(workspace_id=workspace_id)
        chat_msgs = []
        for m in messages:
            chat_msgs.append(ChatMessage(
                role=str(m.get("role", "user")),
                content=str(m.get("content", "")),
                tool_calls=m.get("tool_calls") or [],
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            ))
        engine.store.set_session(sid)
        engine.store.save_messages(chat_msgs, session_id=sid)
        if data.get("summary"):
            engine.store.update_summary(str(data["summary"]), sid)
        return {"success": True, "session_id": sid}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        engine.store.delete_session(session_id)
        return {"success": True}

    @app.patch("/api/sessions/{session_id}")
    async def update_session(session_id: str, request: Request):
        data = await request.json()
        if "summary" in data:
            engine.store.update_summary(str(data["summary"]), session_id)
        return {"success": True}

    # 静态前端（与 ~/dekacode/webui/static 对齐）
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app


async def _handle_command(cmd: str, session: DekacodeSession, send) -> None:
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

    else:
        await send(type="command_output", content=f"Unknown command: {command}. Type /help for available commands.")


async def _dispatch_ws_message(
    msg: dict,
    session: DekacodeSession,
    send,
    engine,
) -> None:
    msg_type = msg.get("type", "")

    if msg_type == "message":
        text = (msg.get("content") or "").strip()
        if not text:
            return
        if text.startswith("/"):
            await _handle_command(text, session, send)
        else:
            await session.process_message(text, send)
            await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "stop":
        session.stop()

    elif msg_type == "temp_session":
        session = engine.new_session()
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "restore_session":
        session = engine.new_session()
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "new_session":
        workspace_id = msg.get("workspace_id")
        if workspace_id and workspace_id != engine.workspace_id:
            path = engine.store.get_workspace_path(workspace_id)
            if path:
                engine.set_workspace(path)
        session = engine.new_session()
        if workspace_id:
            session.workspace_id = workspace_id
        else:
            # 直接点击“新会话”= 全局会话（不绑定具体项目）
            session.workspace_id = None
        await send(type="session_new", session_id=None,
                   workspace_id=session.workspace_id, path=engine.project_root)
        await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "open_workspace":
        path = msg.get("path", "")
        if path:
            wid = engine.set_workspace(path)
            session = engine.new_session()
            session.workspace_id = wid
            await send(type="workspace_opened", workspace_id=wid, path=engine.project_root)
            await send(type="context_update", context=session.context_snapshot())

    elif msg_type == "load_session":
        sid = msg.get("session_id", "")
        if session.load_session(sid):
            if session.workspace_id and session.workspace_id != engine.workspace_id:
                path = engine.store.get_workspace_path(session.workspace_id)
                if path:
                    engine.set_workspace(path)
                    session.workspace_id = engine.workspace_id
            await send(
                type="session_loaded",
                session_id=sid,
                mode=session.mode.mode.value,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="DSN-exp Dekacode WebUI")
    parser.add_argument("--host", default=os.getenv("DEKACODE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DEKACODE_PORT", "8080")))
    parser.add_argument("--project", default=os.getenv("DEKACODE_PROJECT") or os.getcwd())
    parser.add_argument("--max-steps", type=int, default=int(os.getenv("DEKACODE_MAX_STEPS", "12")))
    args = parser.parse_args()

    print(f"  DSN Dekacode WebUI (harness base)")
    print(f"  Project: {args.project}")
    engine = DekacodeEngine(project_root=args.project, max_steps=args.max_steps)
    app = create_app(engine)
    print(f"  Ready  http://{args.host}:{args.port}  model={engine.model_display}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
