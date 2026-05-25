from textual.containers import Container
from textual.widgets import Markdown
from textual.reactive import reactive
from textual.app import ComposeResult


class Message(Container):
    """Single chat bubble"""

    text = reactive("")
    
    def __init__(self, content: str, type_: str = "user"):
        super().__init__()
        self.text = content
        self.type = type_

    def compose(self) -> ComposeResult:
        yield Markdown(self.text)
        self.border_title = "You" if self.type == "user" else "Assistant"
        
    def watch_text(self, text: str) -> None:
        if self.is_mounted:
            self.query_one(Markdown).update(text)