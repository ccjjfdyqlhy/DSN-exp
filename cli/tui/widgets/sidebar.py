# cli/tui/widgets/sidebar.py
"""Chat list sidebar — browse, switch, create conversations."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label, Button
from textual.containers import Vertical, Horizontal
from textual import on, events


class ChatListItem(ListItem):
    """A single chat entry in the sidebar list."""
    def __init__(self, chat: dict):
        super().__init__()
        self.chat = chat
        name = chat.get("chat_name", "Unnamed")[:20]
        count = chat.get("message_count", 0)
        self._label = Label(f"  {name}  ({count})")

    def compose(self) -> ComposeResult:
        yield self._label


class ChatSidebar(Vertical):
    """Sidebar showing chat list with new-chat button."""

    CSS = """
    ChatSidebar {
        width: 28;
        height: 100%;
        border: solid $primary;
        padding: 0;
    }
    #sidebar-header {
        height: 3;
        padding: 1;
        background: $surface;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid $primary;
    }
    #chat-list {
        height: 1fr;
    }
    #sidebar-footer {
        height: 3;
        border-top: solid $primary;
    }
    #new-chat-btn {
        width: 100%;
    }
    ChatListItem {
        padding: 0 1;
    }
    ChatListItem > Label {
        padding: 0;
    }
    """

    class ChatSelected(events.Message):
        """Posted when a chat is selected from the list."""
        def __init__(self, chat_id: int):
            super().__init__()
            self.chat_id = chat_id

    def __init__(self):
        super().__init__()
        self.chats: list[dict] = []
        self.selected_chat_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Static("  Chats", id="sidebar-header")
        yield ListView(id="chat-list")
        with Horizontal(id="sidebar-footer"):
            yield Button("+ New", id="new-chat-btn", variant="primary")

    def populate(self, chats: list[dict], active_id: int | None = None):
        """Refresh the chat list."""
        self.chats = chats
        lv = self.query_one("#chat-list", ListView)
        lv.clear()

        if not chats:
            lv.append(ListItem(Label("  (no chats yet)")))
            return

        for chat in chats:
            item = ChatListItem(chat)
            lv.append(item)

        if active_id and chats:
            for i, chat in enumerate(chats):
                if chat.get("chat_id") == active_id:
                    lv.index = i
                    break

    @on(ListView.Selected)
    def _on_selected(self, event: ListView.Selected):
        """Chat selected from list."""
        if event.item and isinstance(event.item, ChatListItem):
            self.selected_chat_id = event.item.chat.get("chat_id")
            self.post_message(self.ChatSelected(self.selected_chat_id))
