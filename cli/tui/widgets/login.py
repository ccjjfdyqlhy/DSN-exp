# cli/tui/widgets/login.py
"""Login screen — OAuth flow initiation and progress."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static, Button, Label, Header
from textual.containers import Container, Vertical
from textual.binding import Binding


class LoginScreen(Screen):
    """Full-screen OAuth login interface."""

    BINDINGS = [
        Binding("enter", "login", "Start Login", show=True),
        Binding("ctrl+q", "quit_app", "Quit", show=True),
    ]

    CSS = """
    LoginScreen {
        align: center middle;
    }
    #login-container {
        width: 50;
        height: auto;
        border: thick $accent;
        padding: 2;
        align: center middle;
    }
    #login-title {
        content-align: center middle;
        text-style: bold;
        padding-bottom: 1;
    }
    #login-status {
        content-align: center middle;
        height: 4;
        margin-top: 2;
    }
    #login-btn {
        width: 100%;
        margin-top: 2;
    }
    """

    def __init__(self, auth_manager, api_client):
        super().__init__()
        self.auth = auth_manager
        self.api = api_client

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="login-container"):
            yield Static("DSN-exp TUI Client", id="login-title")
            yield Static("Press Enter to log in via LittleSkin.", id="login-info")
            yield Button("Login (Enter)", id="login-btn", variant="primary")
            yield Label("", id="login-status")

    def on_mount(self):
        self.query_one("#login-btn").focus()

    async def action_login(self):
        """Start OAuth login flow."""
        status = self.query_one("#login-status", Label)
        btn = self.query_one("#login-btn", Button)
        btn.disabled = True

        try:
            status.update("Opening browser for login...")
            await self.auth.login(timeout=120)
            status.update("[green]Login successful![/]")
            self.dismiss(True)

        except TimeoutError:
            status.update("[red]Login timed out. Press Enter to retry.[/]")
            btn.disabled = False
        except Exception as e:
            status.update(f"[red]Login failed: {e}[/]")
            btn.disabled = False

    def action_quit_app(self):
        self.app.exit()
