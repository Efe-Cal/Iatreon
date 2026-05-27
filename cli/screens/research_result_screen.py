import re
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Markdown, MarkdownViewer, Static, TabPane, TabbedContent

from db.db import SessionLocal
from db.repositories import ResearchRepo

from cli.utils.source_markdown import (
    build_source_documents,
    build_missing_source_markdown,
    sanitize_markdown,
)

REPORT_TAB_ID = "report_tab"
VIEWER_TAB_ID = "viewer_tab"

def normalize_citations(citations: dict[int | str, dict] | None) -> dict[str, dict]:
    if not citations:
        return {}
    return {str(key): value for key, value in citations.items()}


def build_citation_markdown(citations: dict[str, dict], research_report: str) -> str:
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

        # reference_match = re.match(r"^(\s*)\[(\d+)\](.*)", line)
        # if in_references and reference_match:
        #     indentation, citation_number, _ = reference_match.groups()
        #     rendered_lines.append(f"{indentation}###### ref-{citation_number}")
        #     rendered_lines.append(line)
        #     continue

        if not in_references:
            line = re.sub(r"\[(\d+)\]", replace_inline, line)

        rendered_lines.append(line)

    return "\n".join(rendered_lines)


def create_source_links(research_report: str) -> str:
    section_heading_pattern = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:references?|citations?|sources?)\s*:??\s*$",
        re.IGNORECASE,
    )
    rendered_lines: list[str] = []
    reference_lines = []
    in_references = False
    lines = research_report.splitlines()
    for line in lines:
        if section_heading_pattern.match(line):
            in_references = True
            rendered_lines.append(line)
            continue

        if not in_references:
            rendered_lines.append(line)
            continue

        source_match = re.match(r"^(\s*)\[(\d+)\](.*)", line)
        if source_match:
            indentation, citation_number, rest = source_match.groups()
            reference_lines.append(
                (citation_number,
                 f"{indentation}- [View source {citation_number}](source://{citation_number}){rest}")
            )
            continue

        rendered_lines.append(line)

    return "\n".join(rendered_lines), reference_lines


class SourceMarkdownViewer(MarkdownViewer):
    def __init__(self) -> None:
        super().__init__(
            "Select a source from the References section to load it here.\n\nUse `b` and `f` to move through source history.",
            show_table_of_contents=False,
            open_links=False,
            id="source_viewer",
        )
        self.source_documents: dict[str, str] = {}
        self.source_history: list[str] = []
        self.source_history_index = -1

    def set_documents(self, documents: dict[str, str]) -> None:
        self.source_documents = documents

    async def open_source(self, citation_number: str, *, push_history: bool = True) -> None:
        document = self.source_documents.get(
            citation_number,
            build_missing_source_markdown(citation_number, None),
        )

        if push_history:
            if self.source_history_index >= 0:
                current = self.source_history[self.source_history_index]
                if current == citation_number:
                    await self.document.update(document)
                    return
                self.source_history = self.source_history[: self.source_history_index + 1]
            self.source_history.append(citation_number)
            self.source_history_index = len(self.source_history) - 1

        await self.document.update(document)
        self.post_message(self.NavigatorUpdated())

    async def go(self, location: str) -> None:
        location = str(location)
        if location.startswith("#"):
            self.document.goto_anchor(location[1:])
            return

        if location.startswith("source://"):
            await self.open_source(location.removeprefix("source://"), push_history=True)
            return

        self.app.open_url(location)

    async def back(self) -> None:
        if self.source_history_index <= 0:
            return

        self.source_history_index -= 1
        await self.open_source(self.source_history[self.source_history_index], push_history=False)

    async def forward(self) -> None:
        if self.source_history_index + 1 >= len(self.source_history):
            return

        self.source_history_index += 1
        await self.open_source(self.source_history[self.source_history_index], push_history=False)

class Reference(Markdown):
    def __init__(self, citation_number: str, text: str):
        super().__init__(text)
        self.citation_number = citation_number
        self.id = f"ref-{citation_number}"
        self.open_links = False
        
    async def show_source(self, citation_number: str, *, push_history: bool) -> None:
        viewer = self.screen.query_one(SourceMarkdownViewer)
        await viewer.open_source(citation_number, push_history=push_history)
        self.screen.query_one("#research_tabs", TabbedContent).active = VIEWER_TAB_ID

    @on(Markdown.LinkClicked)
    async def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        href = event.href
        event.stop()
        event.prevent_default()
        if href.startswith("source://"):
            event.stop()
            await self.show_source(href.removeprefix("source://"), push_history=True)
            return
    
    def on_click(self) -> None:
        self.post_message(Markdown.LinkClicked(self, f"source://{self.citation_number}"))

class ReferenceSection(Container):
    def __init__(self):
        super().__init__()
        self.styles.height = "auto"
        
    async def update_references(self, references: list[tuple]) -> None:
        await self.query(Reference).remove()
        for ref in references:
            await self.mount(Reference(*ref))


class ResearchResultScreen(Screen):
    """A Textual screen that shows the report and cited sources."""

    CSS_PATH = "../styles/research_result_screen.tcss"

    BINDINGS = [
        ("b", "source_back", "Back"),
        ("f", "source_forward", "Forward"),
    ]

    def __init__(self, research_session_id: UUID):
        super().__init__()
        self.research_session_id = research_session_id
        self.citations: dict[str, dict] = {}
        self.source_documents: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Button("Back to chat", id="back_to_chat")
        with TabbedContent(initial=REPORT_TAB_ID, id="research_tabs"):
            with TabPane("Research Report", id=REPORT_TAB_ID):
                yield VerticalScroll(
                    Markdown("Loading research report...", open_links=False, id="research_markdown"),
                    ReferenceSection(),
                    id="research_report_container", 
                )
            with TabPane("Markdown Viewer", id=VIEWER_TAB_ID):
                yield SourceMarkdownViewer()
        yield Footer()

    async def on_mount(self) -> None:
        report_markdown = self.query_one("#research_markdown", Markdown)

        async with SessionLocal() as session:
            research_repo = ResearchRepo(session)
            research_session = await research_repo.get_research_session(self.research_session_id)

            if research_session is None:
                report_markdown.update("Research report not found.")
                return

            self.citations = normalize_citations(research_session.citations or {})
            session_sources = await research_repo.get_all_session_sources(self.research_session_id)

        report = research_session.research_report or "Research report is not available yet."
        if self.citations:
            report = build_citation_markdown(self.citations, report)
            report, references = create_source_links(report)

        self.source_documents = build_source_documents(session_sources, self.citations)
        self.query_one(SourceMarkdownViewer).set_documents(self.source_documents)
        report_markdown.update(sanitize_markdown(report))
        
        await self.query_one(ReferenceSection).update_references(references)

    async def action_source_back(self) -> None:
        viewer = self.query_one(SourceMarkdownViewer)
        await viewer.back()
        if viewer.source_history:
            self.query_one("#research_tabs", TabbedContent).active = VIEWER_TAB_ID

    async def action_source_forward(self) -> None:
        viewer = self.query_one(SourceMarkdownViewer)
        await viewer.forward()
        if viewer.source_history:
            self.query_one("#research_tabs", TabbedContent).active = VIEWER_TAB_ID

    @on(Markdown.LinkClicked)
    async def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        if event.markdown.id != "research_markdown":
            return

        href = event.href
        if href.startswith("source://"):
            event.stop()
            await self.show_source(href.removeprefix("source://"), push_history=True)
            return

        if href.startswith("#"):
            event.stop()
            self.scroll_to_widget(self.query_one(f"#{href[1:]}", Reference))
            
            # event.markdown.goto_anchor(href[1:])
            return

        self.app.open_url(href)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back_to_chat":
            self.app.pop_screen()
