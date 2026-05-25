from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button
from cli.widgets.question_dialog import QuestionDialog
from cli.screens.intake_screen import IntakeScreen

import logging

logging.basicConfig(
    filename="cli-debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

class IatreonApp(App):

    BINDINGS = [("q", "request_quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Button("Start Intake", id="start_intake")
    
    @on(Button.Pressed, "#start_intake")
    def start_intake(self):
        self.push_screen(IntakeScreen())
        
    def action_request_quit(self):
        def check_answer(accepted):
            if accepted:
                self.exit()

        self.push_screen(QuestionDialog("Do you want to quit?"), check_answer)
    
if __name__ == "__main__":
    app = IatreonApp()
    app.run()
