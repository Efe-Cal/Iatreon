import re
from uuid import UUID
from textual import on
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Header, Markdown
from textual.containers import VerticalScroll

from db.repositories import ResearchRepo
from db.db import SessionLocal

def sanitize_markdown(content: str) -> str:
    """Remove custom XML-style wrappers that Textual markdown won't display."""
    return re.sub(r"</?source>", "", content)

def build_citation_markdown(citations: dict[str, str], research_report: str) -> str:
    lines = research_report.splitlines()
    rendered_lines: list[str] = []
    in_references = False
    section_heading_pattern = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:references?|citations?|sources?)\s*:??\s*$",
        re.IGNORECASE,
    )

    def replace_inline(match: re.Match[str]) -> str:
        citation_number = match.group(1)
        if citation_number not in citations:
            return match.group(0)

        return f"[\\[{citation_number}\\]](#ref-{citation_number})"

    for line in lines:
        if section_heading_pattern.match(line):
            in_references = True
            rendered_lines.append(line)
            continue

        reference_match = re.match(r"^(\s*)\[(\d+)\](.*)", line)
        if in_references and reference_match:
            indentation, citation_number, _ = reference_match.groups()
            rendered_lines.append(f"{indentation}###### ref-{citation_number}")
            rendered_lines.append(line)
            continue

        if not in_references:
            line = re.sub(r"\[(\d+)\]", replace_inline, line)

        rendered_lines.append(line)

    return "\n".join(rendered_lines)

#TODO: Have the References section items link to source items in the database. Somehow need to have a link here then intercept it.
def create_source_link(citations: dict[str, str], research_report: str) -> str:
    section_heading_pattern = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:references?|citations?|sources?)\s*:??\s*$",
        re.IGNORECASE,
    )
    lines = research_report.splitlines()
    for line in lines:
        if section_heading_pattern.match(line):
            pass
    
    
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
            Markdown("Loading research report...", open_links=False, id="research_markdown"),
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
        citations = research_session.citations or {}
        if citations:
            report = build_citation_markdown(citations, report)
            
        markdown.update(sanitize_markdown(report))

    @on(Markdown.LinkClicked)
    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        href = event.href
        if href.startswith("#"):
            event.markdown.goto_anchor(href[1:])
            return

        self.app.open_url(href)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back_to_chat":
            self.app.pop_screen()