"""
VRAMWarningModal — alert displayed when available VRAM has dropped
significantly between sessions, indicating potential OOM risk.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Center
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class VRAMWarningModal(ModalScreen[bool]):
    """
    Modal alert shown when the current VRAM is ≥20% lower than the
    previous session recorded in models_registry.json.

    Returns True if the user acknowledges and continues, False if
    they choose to abort.
    """

    DEFAULT_CSS = """
    VRAMWarningModal {
        align: center middle;
    }

    #vram-warning-dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        background: #1a1020;
        border: heavy #ff6b35;
        padding: 2 3;
    }

    #vram-warning-icon {
        text-align: center;
        color: #ff6b35;
        text-style: bold;
        margin-bottom: 1;
    }

    #vram-warning-title {
        text-align: center;
        color: #ff4444;
        text-style: bold;
        margin-bottom: 1;
    }

    #vram-warning-body {
        text-align: center;
        color: #e6edf3;
        margin: 1 2;
    }

    #vram-warning-stats {
        text-align: center;
        background: #2a1525;
        border: solid #ff6b35;
        padding: 1 2;
        margin: 1 2;
        color: #ffaa66;
    }

    #vram-warning-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    #vram-warning-buttons Button {
        margin: 0 2;
        min-width: 20;
    }

    .btn-acknowledge {
        background: #ff6b35;
        color: #111111;
        text-style: bold;
    }

    .btn-abort {
        background: #ff4444;
        color: #ffffff;
        text-style: bold;
    }
    """

    def __init__(
        self,
        old_vram_mb: int,
        new_vram_mb: int,
        delta_pct: float,
    ) -> None:
        super().__init__()
        self.old_vram_mb = old_vram_mb
        self.new_vram_mb = new_vram_mb
        self.delta_pct = delta_pct

    def compose(self) -> ComposeResult:
        with Vertical(id="vram-warning-dialog"):
            yield Static("⚠️  ⚠️  ⚠️", id="vram-warning-icon")
            yield Static("VRAM Regression Detected", id="vram-warning-title")
            yield Static(
                "The available GPU VRAM is significantly lower than\n"
                "the previous session. Running large models may cause\n"
                "Out-of-Memory (OOM) errors and system instability.",
                id="vram-warning-body",
            )
            yield Static(
                f"Previous session:  {self.old_vram_mb:,} MB\n"
                f"Current session:   {self.new_vram_mb:,} MB\n"
                f"Change:            {self.delta_pct:+.1f}%",
                id="vram-warning-stats",
            )
            with Center():
                with Horizontal(id="vram-warning-buttons"):
                    yield Button(
                        "Acknowledge & Continue",
                        id="vram-ack-btn",
                        classes="btn-acknowledge",
                    )
                    yield Button(
                        "Abort Setup",
                        id="vram-abort-btn",
                        classes="btn-abort",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "vram-ack-btn":
            self.dismiss(True)
        elif event.button.id == "vram-abort-btn":
            self.dismiss(False)
