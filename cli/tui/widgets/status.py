# cli/tui/widgets/status.py
"""Status bar — model, TTS state, SSE stage, clock."""

from __future__ import annotations

from textual.widgets import Static
from textual.containers import Horizontal
from textual.reactive import reactive


class StatusBar(Horizontal):
    """Bottom status bar showing system state."""

    CSS = """
    StatusBar {
        height: 1;
        padding: 0 2;
        background: $surface;
        border-top: solid $primary;
        align: center middle;
    }
    StatusBar Static {
        width: auto;
        padding: 0 1;
    }
    #status-model {
        color: $accent;
    }
    #status-tts {
        color: $success;
    }
    #status-stage {
        color: $warning;
    }
    #status-clock {
        color: $text-muted;
    }
    """

    model_type: reactive[str] = reactive("deepseek")
    tts_enabled: reactive[bool] = reactive(True)
    sse_stage: reactive[str] = reactive("")
    error_text: reactive[str] = reactive("")

    def compose(self):
        yield Static("", id="status-model")
        yield Static("", id="status-tts")
        yield Static("", id="status-stage")
        yield Static("", id="status-error")
        yield Static("", id="status-clock")

    def watch_model_type(self, val: str):
        self.query_one("#status-model", Static).update(f"[{val.upper()}]")

    def watch_tts_enabled(self, val: bool):
        self.query_one("#status-tts", Static).update("TTS:ON" if val else "TTS:OFF")

    def watch_sse_stage(self, val: str):
        self.query_one("#status-stage", Static).update(val)

    def watch_error_text(self, val: str):
        self.query_one("#status-error", Static).update(f"[red]{val}[/]" if val else "")

    def on_mount(self):
        self.set_interval(1, self._update_clock)

    def _update_clock(self):
        from datetime import datetime
        self.query_one("#status-clock", Static).update(datetime.now().strftime("%H:%M:%S"))
