
import uuid
from textual.screen import Screen
from textual import work
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Header, Input, Static
from textual.containers import Horizontal, VerticalScroll
from cli.widgets.spinner import SpinnerWidget
from cli.widgets.message import Message
from cli.screens.research_screen import ResearchScreen

from agents.intake import run_intake_cli
from db.schemas import IntakeProfile
from db.repositories import IntakeRepo, ResearchRepo
from db.db import SessionLocal
from agents.research import ResearchAgent
from textual.worker import WorkerState
import logging
from pathlib import Path

logging.basicConfig(
    filename=Path(__file__).parent.parent / "cli-debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

class IntakeScreen(Screen):
    """A Textual App to interact with the Iatreon agents."""

    CSS_PATH = "../styles/intake_screen.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.intake_session = None
        self.research_session_id = None
        self.intake_running = False
        self.research_running = False

    def on_worker_state_changed(self, event) -> None:
        if event.state == WorkerState.ERROR:
            logging.error("Worker failed: %s", event.worker.error)
            self.finish_research_ui(f"Worker failed: {event.worker.error}")
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            id="message_container"
        )
        yield Button("Start Research", id="start_research")
        yield Horizontal(
            Horizontal(
                SpinnerWidget(id="spinner"),
                Static("Researching...", id="processing_text"),
                id="processes"
            ),
            Button("See Research Report", id="see_research_report"),
            id="research_status_row"
        )
        yield Input(
            placeholder="Type message...",
            id="input"
        )
        yield Footer()
    
    
    async def on_mount(self):
        self.chat = self.query_one("#message_container", VerticalScroll)
        await self.chat.mount(Message("**Assistant:** Hey, I am Iatreon! What brings you in today?", type_="assistant"))
        
        self.start_research = self.query_one("#start_research", Button)
        self.start_research.display = False
        self.see_research_report = self.query_one("#see_research_report", Button)
        self.see_research_report.display = False
        self.input = self.query_one("#input", Input)
        self.processing_spinner = self.query_one("#spinner", SpinnerWidget)
        self.processing_text = self.query_one("#processing_text", Static)
        self.research_status_row = self.query_one("#research_status_row", Horizontal)
        self.research_status_row.display = False

    def begin_research_ui(self, message: str) -> None:
        self.research_running = True
        self.input.disabled = True
        self.start_research.disabled = True
        self.start_research.display = False
        self.research_status_row.display = True
        self.see_research_report.display = False
        self.processing_spinner.set_active(True)
        self.processing_text.update(message)

    def finish_research_ui(self, message: str, *, show_report: bool = False) -> None:
        self.research_running = False
        self.input.disabled = False
        self.start_research.disabled = False
        self.processing_spinner.set_active(False)
        self.processing_text.update(message)
        self.see_research_report.display = show_report

    def begin_intake_ui(self) -> None:
        self.intake_running = True
        self.input.disabled = True

    def finish_intake_ui(self) -> None:
        self.intake_running = False
        self.input.disabled = False
        self.input.focus()


    async def on_input_submitted(self, event: Input.Submitted):
        if self.research_running or self.intake_running:
            return

        if not event.value.strip():
            return

        user_message = event.value
        await self.chat.mount(Message(user_message))
        event.input.value = ""

        # auto-scroll to bottom
        self.chat.scroll_end()
        self.begin_intake_ui()
        self.run_intake_message(user_message)

    @work(exclusive=True)
    async def run_intake_message(self, user_message: str) -> None:
        assistant_message: Message | None = None

        try:
            async for chunk in run_intake_cli(user_message):
                if not chunk:
                    continue

                if isinstance(chunk, str):
                    if chunk == "END":
                        continue

                    if assistant_message is None:
                        assistant_message = Message(chunk, type_="assistant")
                        await self.chat.mount(assistant_message)
                    else:
                        assistant_message.text += chunk

                    self.chat.scroll_end()
                    continue

                if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
                    async with SessionLocal() as session:
                        intake_repo = IntakeRepo(session)
                        self.intake_session = await intake_repo.create_session(user_id=uuid.uuid4())
                        await intake_repo.update_session(self.intake_session.id, profile=chunk[0], transcript=chunk[1])
                        await intake_repo.complete_session(self.intake_session.id)
                    self.start_research.display = True

        except Exception:
            logging.exception("Error while running intake")
            await self.chat.mount(Message("I hit an error while generating the intake response.", type_="assistant"))
            self.chat.scroll_end()
        finally:
            self.finish_intake_ui()
        
    @work
    async def run_research(self) -> None:
        if self.intake_session is None:
            self.research_status_row.display = True
            self.finish_research_ui("Complete intake before starting research.")
            return

        if self.research_running:
            return

        self.begin_research_ui("Starting research...")
        try:
            async with SessionLocal() as session:
                research_repo = ResearchRepo(session)
                intake_session = self.intake_session # await IntakeRepo(session).get_session(self.intake_session.id)
                if intake_session is None:
                    self.finish_research_ui("Unable to find the completed intake session.")
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
                        self.finish_research_ui("Research complete.", show_report=True)
        except Exception as e:
            logging.error("Error in run_research: %s", str(e))
            self.finish_research_ui(f"Error: {str(e)}")

    async def on_button_pressed(self, event: Button.Pressed):
        logging.debug("Button pressed: %s", event.button.id)
        if event.button.id == "start_research":
            self.run_research()
        elif event.button.id == "see_research_report" and self.research_session_id is not None:
            self.app.push_screen(ResearchScreen(self.research_session_id))
