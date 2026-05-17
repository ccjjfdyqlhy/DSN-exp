# cli/tui/app.py
"""DSN-exp TUI — Textual App entry point."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from textual import on

from cli.tui.auth import AuthManager
from cli.tui.api import APIClient
from cli.tui.config import ClientConfig
from cli.tui.audio import play_wav_base64, stop_audio
from cli.tui.widgets.sidebar import ChatSidebar
from cli.tui.widgets.messages import MessageView
from cli.tui.widgets.input import ChatInput
from cli.tui.widgets.status import StatusBar
from cli.tui.widgets.login import LoginScreen

logger = logging.getLogger("tui.app")


class MainScreen(Screen):
    """Main chat interface."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+n", "new_chat", "New Chat", show=True),
        Binding("ctrl+t", "toggle_tts", "Toggle TTS", show=True),
        Binding("ctrl+m", "toggle_model", "Toggle Model", show=True),
        Binding("escape", "focus_input", "Focus Input", show=True),
    ]

    CSS = """
    MainScreen {
        layout: horizontal;
    }
    #main-area {
        width: 1fr;
        height: 100%;
    }
    #main-area > MessageView {
        height: 1fr;
    }
    #main-area > ChatInput {
        height: 3;
    }
    """

    def __init__(self, config: ClientConfig, auth: AuthManager, api: APIClient):
        super().__init__()
        self.config = config
        self.auth = auth
        self.api = api
        self.current_chat_id: int | None = None
        self.current_chat_name: str = "New Chat"
        self._streaming = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatSidebar()
        with Container(id="main-area"):
            yield MessageView()
            yield ChatInput()
        yield StatusBar()
        yield Footer()

    # ── Lifecycle ──

    async def on_mount(self):
        status = self.query_one(StatusBar)
        status.model_type = self.config.model_type
        status.tts_enabled = self.config.tts_enabled
        await self._refresh_chat_list()
        self.query_one("#chat-input", Input).focus()

    # ── Chat list ──

    async def _refresh_chat_list(self):
        sidebar = self.query_one(ChatSidebar)
        try:
            chats = await self.api.get_chats()
            sidebar.populate(chats, self.current_chat_id)
        except Exception as e:
            logger.error("Failed to load chats: %s", e)
            self.query_one(StatusBar).error_text = f"Chat list: {e}"

    async def _load_chat(self, chat_id: int):
        try:
            messages = await self.api.get_history(chat_id)
            self.query_one(MessageView).load_history(messages)
            sidebar = self.query_one(ChatSidebar)
            for chat in sidebar.chats:
                if chat.get("chat_id") == chat_id:
                    self.current_chat_name = chat.get("chat_name", "Chat")
                    break
            self.current_chat_id = chat_id
            sidebar.selected_chat_id = chat_id
            self.query_one(StatusBar).error_text = ""
        except Exception as e:
            self.query_one(StatusBar).error_text = f"Load error: {e}"

    # ── ChatInput → MessageEntered / CommandEntered ──

    @on(ChatInput.MessageEntered)
    async def _handle_message(self, event: ChatInput.MessageEntered):
        if self._streaming:
            self.query_one(StatusBar).error_text = "Already streaming..."
            return
        await self._send_message(event.text)

    @on(ChatInput.CommandEntered)
    async def _handle_command(self, event: ChatInput.CommandEntered):
        cmd = event.command
        arg = event.arg
        mv = self.query_one(MessageView)

        if cmd == "tts":
            self.config.tts_enabled = not self.config.tts_enabled
            self.query_one(StatusBar).tts_enabled = self.config.tts_enabled
            mv.add_system_message(f"TTS {'[green]ON[/]' if self.config.tts_enabled else '[dim]OFF[/]'}")

        elif cmd == "model":
            if arg in ("deep", "deepseek"):
                self.config.model_type = "deepseek"
            elif arg in ("fast", "lmstudio"):
                self.config.model_type = "lmstudio"
            else:
                self.config.model_type = "lmstudio" if self.config.model_type == "deepseek" else "deepseek"
            self.query_one(StatusBar).model_type = self.config.model_type
            mv.add_system_message(f"Model: [bold]{self.config.model_type}[/]")

        elif cmd == "new":
            self.current_chat_id = None
            self.current_chat_name = arg or "New Chat"
            mv.clear_messages()
            mv.add_system_message(f"New chat: {self.current_chat_name}")
            self.query_one(ChatSidebar).selected_chat_id = None

        elif cmd == "switch":
            sidebar = self.query_one(ChatSidebar)
            try:
                idx = int(arg) - 1
                if 0 <= idx < len(sidebar.chats):
                    await self._load_chat(sidebar.chats[idx]["chat_id"])
            except (ValueError, IndexError):
                self.query_one(StatusBar).error_text = f"Invalid chat index: {arg}"

        elif cmd == "quit":
            self.app.exit()

        elif cmd == "help":
            mv.add_system_message(
                "[bold]Commands:[/]\n"
                "  /tts           — toggle TTS\n"
                "  /model [deep|fast] — switch model\n"
                "  /new [name]    — new chat\n"
                "  /switch <n>    — switch to chat N\n"
                "  /quit          — exit\n"
                "[bold]Keys:[/]\n"
                "  Ctrl+Q  quit | Ctrl+N  new chat | Ctrl+T  toggle TTS\n"
                "  Ctrl+M  toggle model | Esc  focus input"
            )

    # ── Sidebar: ChatSelected ──

    @on(ChatSidebar.ChatSelected)
    async def _handle_chat_selected(self, event: ChatSidebar.ChatSelected):
        await self._load_chat(event.chat_id)
        self.query_one("#chat-input", Input).focus()

    # ── Button: New Chat ──

    @on(Button.Pressed, "#new-chat-btn")
    async def _handle_new_chat_btn(self):
        self.current_chat_id = None
        self.current_chat_name = "New Chat"
        self.query_one(MessageView).clear_messages()
        self.query_one(MessageView).add_system_message("New chat — type a message to begin.")
        self.query_one(ChatSidebar).selected_chat_id = None
        self.query_one("#chat-input", Input).focus()

    # ── SSE streaming ──

    async def _send_message(self, text: str):
        mv = self.query_one(MessageView)
        status = self.query_one(StatusBar)
        inp = self.query_one("#chat-input", Input)

        mv.add_user_message(text)
        status.sse_stage = "◉ sending..."
        status.error_text = ""
        self._streaming = True
        inp.disabled = True
        stop_audio()

        chat_name = None if self.current_chat_id else (self.current_chat_name or "New Chat")

        try:
            async for evt in self.api.stream_send(
                message=text,
                chat_id=self.current_chat_id,
                chat_name=chat_name,
                model_type=self.config.model_type,
                tts_enabled=self.config.tts_enabled,
            ):
                stage = evt.get("status", "")
                status.sse_stage = f"◉ {stage}"

                if stage == "text_ready":
                    reply = evt.get("reply", "")
                    if reply:
                        mv.add_agent_message(reply)
                    cid = evt.get("chat_id")
                    if cid and not self.current_chat_id:
                        self.current_chat_id = cid
                        await self._refresh_chat_list()

                elif stage == "completed":
                    audio = evt.get("audio")
                    if audio and self.config.tts_enabled:
                        play_wav_base64(audio)
                    cid = evt.get("chat_id")
                    if cid and not self.current_chat_id:
                        self.current_chat_id = cid
                        await self._refresh_chat_list()
                    if evt.get("filtered"):
                        mv.add_system_message("(ASR filtered)")

        except Exception as e:
            logger.error("Stream error: %s", e)
            status.error_text = f"Stream: {e}"
            mv.add_system_message(f"[red]Error: {e}[/]")
        finally:
            self._streaming = False
            inp.disabled = False
            inp.focus()
            status.sse_stage = ""

    # ── Key bindings ──

    def action_focus_input(self):
        self.query_one("#chat-input", Input).focus()

    def action_quit(self):
        self.app.exit()

    async def action_new_chat(self):
        self.current_chat_id = None
        self.current_chat_name = "New Chat"
        mv = self.query_one(MessageView)
        mv.clear_messages()
        mv.add_system_message("New chat — type a message to begin.")
        self.query_one("#chat-input", Input).focus()

    def action_toggle_tts(self):
        self.config.tts_enabled = not self.config.tts_enabled
        self.query_one(StatusBar).tts_enabled = self.config.tts_enabled

    def action_toggle_model(self):
        self.config.model_type = "lmstudio" if self.config.model_type == "deepseek" else "deepseek"
        self.query_one(StatusBar).model_type = self.config.model_type


# ═══════════════════════════════════════════════════════════════

class DSNTuiApp(App):
    """DSN-exp Terminal UI Application."""

    TITLE = "DSN-exp TUI"
    SUB_TITLE = "Terminal Chat Client"

    def __init__(self, config: ClientConfig):
        super().__init__()
        self.config = config
        self.auth = AuthManager(config.server_url)
        self.api = APIClient(config.server_url, self.auth)

    async def on_mount(self):
        token = self.auth.load_token()
        if token:
            await self.push_screen(MainScreen(self.config, self.auth, self.api))
        else:
            await self.push_screen(LoginScreen(self.auth, self.api))
            await self.push_screen(MainScreen(self.config, self.auth, self.api))
