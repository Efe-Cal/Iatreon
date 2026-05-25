import re
from uuid import UUID
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Header, Markdown
from textual.containers import VerticalScroll

from db.repositories import ResearchRepo
from db.db import SessionLocal

def sanitize_markdown(content: str) -> str:
    """Remove custom XML-style wrappers that Textual markdown won't display."""
    return re.sub(r"</?source>", "", content)

class ResearchScreen(Screen):
    """A Textual Screen to interact with the Iatreon agents."""
    
    CSS_PATH = "../styles/research_screen.tcss"
    
    def __init__(self, research_session_id: UUID):
        super().__init__()
        self.research_session_id = research_session_id
        
    def compose(self) -> ComposeResult:
        yield Header(name="Research Report")
        yield Button("Back to chat", id="back_to_chat")
        yield VerticalScroll(
            Markdown("Loading research report...", id="research_markdown"),
            id="research_report_container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        markdown = self.query_one("#research_markdown", Markdown)
        async with SessionLocal() as session:
            research_session = await ResearchRepo(session).get_research_session(self.research_session_id)

        if research_session is None:
            markdown.update("Research report not found.")
            return

        report = research_session.research_report or "Research report is not available yet."
        markdown.update(sanitize_markdown(report))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back_to_chat":
            self.app.pop_screen()