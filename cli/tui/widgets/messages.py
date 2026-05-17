# cli/tui/widgets/messages.py
"""Message display area — RichLog with Markdown rendering and auto-scroll."""

from __future__ import annotations

from textual.widgets import RichLog
from textual.containers import Vertical


class MessageView(Vertical):
    """Scrollable message display area using RichLog."""

    CSS = """
    MessageView {
        height: 1fr;
        border: solid $surface;
    }
    MessageView RichLog {
        height: 1fr;
        padding: 1;
    }
    """

    def compose(self):
        yield RichLog(id="message-log", highlight=True, markup=True, wrap=True)

    def clear_messages(self):
        self.query_one(RichLog).clear()

    def add_user_message(self, text: str):
        """Add a user message."""
        log = self.query_one(RichLog)
        log.write(f"[bold]You:[/] {text}")

    def add_agent_message(self, text: str):
        """Add an agent (AI) reply."""
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]EXA:[/] {text}")

    def add_system_message(self, text: str):
        """Add a system/info message."""
        log = self.query_one(RichLog)
        log.write(f"[dim italic]{text}[/]")

    def add_streaming_message(self, text: str):
        """Show AI reply while streaming (replaces last line)."""
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]EXA:[/] {text}")

    def load_history(self, messages: list[dict]):
        """Load and display chat history."""
        self.clear_messages()
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self.add_user_message(content)
            elif role == "assistant":
                self.add_agent_message(content)
            elif role == "system":
                self.add_system_message(content)
