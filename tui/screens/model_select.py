from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Header, Footer
from textual.containers import Vertical, Horizontal

class ModelSelectionScreen(Screen):
    """Recommends a model based on the hardware scan and asks for confirmation."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="model-panel"):
            yield Static("🤖 Model Selection", classes="title")
            yield Static("", id="model-recommendation")
            yield Static("", id="model-explanation")
            
            with Horizontal(id="action-buttons"):
                yield Button("Confirm & Continue", variant="primary", id="confirm_btn")
        yield Footer()

    def on_mount(self) -> None:
        self.update_recommendation()

    def update_recommendation(self) -> None:
        state = self.app.state
        tier = state.assigned_tier
        
        if tier == 1:
            recommended_model = "qwen2.5:7b"
            explanation = (
                "Based on your hardware (> 8GB Usable VRAM), we recommend [bold cyan]Qwen 2.5 7B[/bold cyan].\n\n"
                "This model offers excellent reasoning capabilities while leaving enough VRAM for the KV cache and OS overhead. "
                "Because we strictly reserve your CPU for Tesseract OCR tasks, this model will fit entirely into your GPU."
            )
        elif tier == 2:
            recommended_model = "qwen2.5:3b"
            explanation = (
                "Based on your hardware (4-8GB Usable VRAM), we recommend [bold cyan]Qwen 2.5 3B[/bold cyan].\n\n"
                "This provides a great balance of speed and intelligence while ensuring 100% of the model stays in VRAM. "
                "Because we strictly reserve your CPU for Tesseract OCR tasks, offloading to CPU is disabled."
            )
        else:
            recommended_model = "gemma2:2b"
            explanation = (
                "Based on your hardware (< 4GB VRAM or CPU-only), we recommend [bold cyan]Gemma 2 2B[/bold cyan].\n\n"
                "This lightweight model ensures the system remains responsive. "
                "Since Tesseract OCR requires heavy CPU usage, keeping the LLM footprint small is critical for pipeline performance."
            )
            
        self.app.state.model_name = recommended_model
        
        self.query_one("#model-recommendation", Static).update(
            f"Recommended Model: [bold green]{recommended_model}[/bold green]"
        )
        self.query_one("#model-explanation", Static).update(explanation)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_btn":
            self.app.push_screen("deployment")
