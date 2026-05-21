from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Header, Footer, LoadingIndicator
from textual.containers import Vertical, Horizontal
from textual import work

from tui.utils.hardware_scanner import get_hardware_specs

class HardwareScanningScreen(Screen):
    """Scans hardware and displays the results."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="scan-panel"):
            yield Static("🔍 Hardware Scanner", classes="title")
            yield LoadingIndicator(id="loading")
            yield Static("Scanning system for GPU capabilities...", id="status-text")
            
            with Vertical(id="results-container"):
                yield Static("", id="results-text")
            
            with Horizontal(id="action-buttons"):
                yield Button("Retry Scan", id="retry_btn")
                yield Button("Continue to Model Selection", variant="primary", id="continue_btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        """Starts the hardware scan automatically when the screen mounts."""
        self.query_one("#results-container").display = False
        self.query_one("#action-buttons").display = False
        self.run_scan()

    @work(thread=True)
    def run_scan(self) -> None:
        """Runs the hardware scan in a background thread to prevent UI freezing."""
        self.app.call_from_thread(self.update_status, "Executing nvidia-smi...")
        specs = get_hardware_specs()
        
        # Update the global app state
        self.app.state.os_name = specs.os_name
        self.app.state.gpu_present = specs.gpu_present
        self.app.state.raw_vram_mb = specs.raw_vram_mb
        self.app.state.usable_vram_mb = specs.usable_vram_mb
        self.app.state.assigned_tier = specs.assigned_tier
        
        # Safely update the UI from the worker thread
        self.app.call_from_thread(self.show_results)

    def update_status(self, message: str) -> None:
        """Updates the status text label."""
        self.query_one("#status-text", Static).update(message)

    def show_results(self) -> None:
        """Reveals the results container and populates the text."""
        self.query_one("#loading").display = False
        self.query_one("#status-text").display = False
        
        state = self.app.state
        
        # Format results elegantly
        if state.gpu_present:
            gpu_status = "[bold green]NVIDIA GPU Detected[/bold green]"
            vram_info = f"Raw VRAM: {state.raw_vram_mb} MB\nUsable VRAM: {state.usable_vram_mb} MB"
        else:
            gpu_status = "[bold yellow]No GPU Detected (or drivers missing)[/bold yellow]"
            vram_info = "Using CPU fallback mode."
            
        results = (
            f"OS: {state.os_name}\n\n"
            f"GPU Status: {gpu_status}\n"
            f"{vram_info}\n\n"
            f"[bold cyan]Assigned Tier: {state.assigned_tier}[/bold cyan]"
        )
        
        self.query_one("#results-text", Static).update(results)
        self.query_one("#results-container").display = True
        self.query_one("#action-buttons").display = True
        
        # Enable the continue button
        self.query_one("#continue_btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry_btn":
            # Reset UI state and retry the scan
            self.query_one("#results-container").display = False
            self.query_one("#action-buttons").display = False
            self.query_one("#continue_btn", Button).disabled = True
            
            self.query_one("#loading").display = True
            self.query_one("#status-text").display = True
            self.update_status("Retrying scan...")
            
            self.run_scan()
            
        elif event.button.id == "continue_btn":
            self.app.push_screen("model_select")
