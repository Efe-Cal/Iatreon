import uuid
import re
from uuid import UUID
from textual.screen import Screen
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, Footer, Header, Input, Markdown, Static
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import reactive
from textual import work
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


def sanitize_markdown(content: str) -> str:
    """Remove custom XML-style wrappers that Textual markdown won't display."""
    return re.sub(r"</?source>", "", content)

from textual.worker import WorkerState

import logging

logging.basicConfig(
    filename="cli-debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

class ChatScreen(Screen):
    """A Textual App to interact with the Iatreon agents."""

    CSS_PATH = "cli.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.intake_session = None
        self.research_session_id = None

    def on_worker_state_changed(self, event) -> None:

        if event.state == WorkerState.ERROR:
            logging.error("Worker failed: %s", event.worker.error)
            self.processing_text.update(f"Worker failed: {event.worker.error}")
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
            id="processes"
        )
        yield Button("Start Research", id="start_research")
        yield Button("See Research Report", id="see_research_report")
        yield Footer()
    
    
    async def on_mount(self):
        self.chat = self.query_one("#message_container", VerticalScroll)
        self.chat.mount(Message("**Assistant:** Hey, I am Iatreon! What brings you in today?", type_="assistant"))
        
        self.start_research = self.query_one("#start_research", Button)
        # self.start_research.visible = False
        self.see_research_report = self.query_one("#see_research_report", Button)
        self.see_research_report.visible = False
        
        self.processing_text = self.query_one("#processing_text", Static)


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
                    self.intake_session = await intake_repo.create_session(user_id=uuid.uuid4())
                    await intake_repo.update_session(self.intake_session.id, profile=chunk[0], transcript=chunk[1])
                    await intake_repo.complete_session(self.intake_session.id)
                self.start_research.visible = True
        
    @work
    async def run_research(self) -> None:
        if self.intake_session is None:
            self.processing_text.update("Complete intake before starting research.")
            return

        self.processing_text.update("Starting research...")
        try:
            async with SessionLocal() as session:
                research_repo = ResearchRepo(session)
                intake_session = self.intake_session # await IntakeRepo(session).get_session(self.intake_session.id)
                if intake_session is None:
                    self.processing_text.update("Unable to find the completed intake session.")
                    return

                research_session = await research_repo.create_research_session(intake_session.user_id, intake_session.id)
                self.research_session_id = research_session.id
                research_agent = ResearchAgent(session, research_repo, research_session.id)
                async for research_chunk in research_agent.run(intake_session):
                    if isinstance(research_chunk, str):
                        self.processing_text.update(research_chunk)
                        logging.debug("Research chunk: %s", research_chunk)
                    elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                        research_report, citations = research_chunk
                        await research_repo.update_research_session(
                            session_id=research_session.id,
                            research_report=research_report,
                            citations=citations,
                        )
                        self.processing_text.update("Research complete.")
                        self.see_research_report.visible = True
        except Exception as e:
            logging.error("Error in run_research: %s", str(e))
            self.processing_text.update(f"Error: {str(e)}")

    async def on_button_pressed(self, event: Button.Pressed):
        logging.debug("Button pressed: %s", event.button.id)
        if event.button.id == "start_research":
            self.run_research()
        elif event.button.id == "see_research_report" and self.research_session_id is not None:
            self.app.push_screen(ResearchScreen(self.research_session_id))

class ResearchScreen(Screen):
    """A Textual Screen to interact with the Iatreon agents."""
    def __init__(self, research_session_id: UUID):
        super().__init__()
        self.research_session_id = research_session_id
        
    def compose(self) -> ComposeResult:
        yield Header(name="Research Report")
        yield Markdown("Loading research report...")
        yield Footer()

    async def on_mount(self) -> None:
        markdown = self.query_one(Markdown)
        async with SessionLocal() as session:
            research_session = await ResearchRepo(session).get_research_session(self.research_session_id)

        if research_session is None:
            markdown.update("Research report not found.")
            return

        report = research_session.research_report or "Research report is not available yet."
        markdown.update(sanitize_markdown(report))


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
