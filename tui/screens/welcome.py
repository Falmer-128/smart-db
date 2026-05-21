from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Header, Footer
from textual.containers import Vertical, Center

class WelcomeScreen(Screen):
    """The initial welcome screen for the Setup Wizard."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel"):
            yield Static("✨ Zero-Touch Setup Wizard ✨", classes="title")
            yield Static(
                "Welcome to the smart-db ETL pipeline setup.\n\n"
                "This wizard will automatically:\n"
                "1. Detect your hardware capabilities.\n"
                "2. Recommend the optimal local LLM (fitting 100% in VRAM).\n"
                "3. Configure and deploy the Docker backend automatically.\n\n"
                "Ensure you have Docker and nvidia-smi available if you are using an NVIDIA GPU.",
                id="welcome-text"
            )
            with Center():
                yield Button("Start Setup", variant="primary", id="start_btn")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start_btn":
            self.app.push_screen("hardware")
