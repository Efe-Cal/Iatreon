from textual.widgets import Static
from rich.spinner import Spinner

class SpinnerWidget(Static):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active = True

    def on_mount(self):
        self.spinner = Spinner("dots")
        self.set_interval(1 / 12, self.refresh_spinner)
        self.refresh_spinner()

    def refresh_spinner(self):
        self.update(self.spinner if self.active else "")

    def set_active(self, active: bool) -> None:
        self.active = active
        if self.is_mounted:
            self.refresh_spinner()