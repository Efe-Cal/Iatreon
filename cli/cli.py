from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, Markdown
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from agents.intake import run_intake_cli

class Message(Container):
    """Single chat bubble"""

    text = reactive("")
    
    def __init__(self, content: str, type_: str = "user"):
        super().__init__()
        self.text = content
        self.type = type_

    def compose(self) -> ComposeResult:
        yield Markdown(self.text)
        
    def watch_text(self, text: str) -> None:
        if self.is_mounted:
            self.query_one(Markdown).update(text)


class IatreonCLI(App):
    """A Textual App to interact with the Iatreon agents."""

    CSS_PATH = "cli.tcss"
    BINDINGS = [("q", "quit", "Quit"), ("t", "toggle_table_of_contents", "Toggle Table of Contents")]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            id="message_container"
        )
        yield Input(
            placeholder="Type message...",
            id="input"
        )
        
        yield Footer()
    
    
    def on_mount(self):
        self.chat = self.query_one("#message_container", VerticalScroll)

    async def on_input_submitted(self, event: Input.Submitted):
        self.chat.mount(Message(event.value))
        event.input.value = ""

        # auto-scroll to bottom
        self.chat.scroll_end()
        
        async for chunk in run_intake_cli(event.value):
            if not isinstance(chunk, str) or not chunk:
                continue

            if chunk == "END":
                self.chat.mount(Message("**Assistant:** Thank you for your time. The intake is now complete."))
            elif isinstance(chunk, str):
                last = self.query("#message_container Message").last()
                if last and last.type == "assistant":
                    last.text += chunk
                    self.chat.scroll_end()
                else:
                    self.chat.mount(Message(chunk, type_="assistant"))
            
                

if __name__ == "__main__":
    app = IatreonCLI()
    app.run()
