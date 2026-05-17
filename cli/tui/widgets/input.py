# cli/tui/widgets/input.py
"""Message input area with command parsing."""

from __future__ import annotations

from textual.widgets import Input, Static
from textual.containers import Horizontal
from textual.binding import Binding
from textual import events


class ChatInput(Horizontal):
    """Input bar for typing messages and commands."""

    CSS = """
    ChatInput {
        height: 3;
        border-top: solid $primary;
        padding: 0 1;
        align: center middle;
    }
    ChatInput Input {
        width: 1fr;
    }
    #input-prompt {
        width: 4;
        content-align: right middle;
        padding-right: 1;
        text-style: bold;
    }
    """

    def compose(self):
        yield Static(">", id="input-prompt")
        yield Input(placeholder="Type a message... (/help for commands)", id="chat-input")

    def on_mount(self):
        self.query_one("#chat-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        """Handle message submission."""
        text = event.value.strip()
        event.input.clear()

        if not text:
            return

        # Command parsing
        if text.startswith("/"):
            cmd, *args = text[1:].split(maxsplit=1)
            arg = args[0] if args else ""
            self.post_message(self.CommandEntered(cmd.lower(), arg))
        else:
            self.post_message(self.MessageEntered(text))

    class MessageEntered(events.Message):
        """Posted when user submits a chat message."""
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    class CommandEntered(events.Message):
        """Posted when user enters a slash command."""
        def __init__(self, command: str, arg: str):
            super().__init__()
            self.command = command
            self.arg = arg
