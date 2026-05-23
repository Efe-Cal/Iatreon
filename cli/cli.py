import uuid
from textual.screen import Screen
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, Footer, Header, Input, Markdown, Static
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import reactive
from rich.spinner import Spinner

from agents.intake import run_intake_cli
from db.schemas import IntakeProfile
from db.repositories import IntakeRepo, ResearchRepo
from db.db import SessionLocal
from agents.research import ResearchAgent

class SpinnerWidget(Static):
    def on_mount(self):
        self.spinner = Spinner("dots")
        self.set_interval(1 / 12, self.refresh_spinner)

    def refresh_spinner(self):
        self.update(self.spinner)

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


class ChatScreen(Screen):
    """A Textual App to interact with the Iatreon agents."""

    CSS_PATH = "cli.tcss"
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            id="message_container"
        )
        yield Input(
            placeholder="Type message...",
            id="input"
        )
        yield Horizontal(
            SpinnerWidget(id="spinner"),
            Static("Processing...", id="processing_text"),
            id="processes")

        yield Footer()
    
    
    async def on_mount(self):
        self.chat = self.query_one("#message_container", VerticalScroll)
        self.chat.mount(Message("**Assistant:** Hey, I am Iatreon! What brings you in today?", type_="assistant"))
         

    async def on_input_submitted(self, event: Input.Submitted):
        self.chat.mount(Message(event.value))
        event.input.value = ""

        # auto-scroll to bottom
        self.chat.scroll_end()
        
        async for chunk in run_intake_cli(event.value):
            if not chunk:
                continue

            if isinstance(chunk, str):
                if chunk == "END":
                    self.chat.mount(Message("**Assistant:** Thank you for your time. The intake is now complete."))
                else:
                    last = self.query("#message_container Message").last()
                    if last and last.type == "assistant":
                        last.text += chunk
                        self.chat.scroll_end()
                    else:
                        self.chat.mount(Message(chunk, type_="assistant"))

            elif isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
                async with SessionLocal() as session:
                    intake_repo = IntakeRepo(session)
                    intake_session = await intake_repo.create_session(user_id=uuid.uuid4())
                    await intake_repo.update_session(intake_session.id, profile=chunk[0], transcript=chunk[1])
                    await intake_repo.complete_session(intake_session.id)
        
        
                # self.app.switch_screen(ResearchScreen(intake_session.id)) 
        research_agent = ResearchAgent()
        research_agent.run(intake_session.id)

class ResearchScreen(Screen):
    """A Textual Screen to interact with the Iatreon agents."""
    def __init__(self, intake_session_id: int):
        super().__init__()
        self.intake_session_id = intake_session_id
        self.research_repo = ResearchRepo(SessionLocal())
        
    def compose(self) -> ComposeResult:
        yield Header()
        yield Markdown("**Research Screen** - This is where the research agent will operate.")
        yield Footer()


class IatreonApp(App):

    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Button("Start Intake", id="start_intake")
    
    @on(Button.Pressed, "#start_intake")
    def start_intake(self):
        self.push_screen(ChatScreen())
    
if __name__ == "__main__":
    app = IatreonApp()
    app.run()
