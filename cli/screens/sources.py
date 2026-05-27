
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Header, Markdown, TabPane, TabbedContent
from textual.containers import Container, VerticalScroll

class SourcesScreen(Container):
    
    def __init__(self, sources):
        super().__init__()
        self.sources = sources
        
    def compose(self) -> ComposeResult:
        with TabbedContent():
            yield TabPane("Go to", Button("Back to chat", id="back_to_chat_sources"), id="navigation_tab") 
    
    def on_mount(self):
        tabbed_content = self.query_one(TabbedContent)
        for source_id, source_info in self.sources.items():
            title = source_info.get("title", f"Source {source_id}")
            content = source_info.get("content", "No content available.")
            tabbed_content.add_pane(TabPane(title, Markdown(content, open_links=False), id=f"source_{source_id}"))