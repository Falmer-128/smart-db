"""
smart-db Setup Wizard — Textual TUI entry point.

Orchestrates the zero-touch setup flow:
  Welcome → Hardware Scan → Model Selection → API Settings → Deployment
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import App
from tui.screens.welcome import WelcomeScreen
from tui.screens.hardware import HardwareScanningScreen
from tui.screens.model_select import ModelSelectionScreen
from tui.screens.api_settings import APISettingsScreen
from tui.screens.deployment import DeploymentScreen


@dataclass
class SetupState:
    """Holds the global state of the setup wizard across all screens."""

    # ── Hardware scan results ────────────────────────────────
    os_name: str = ""
    gpu_present: bool = False
    gpu_name: str = ""
    raw_vram_mb: int = 0
    usable_vram_mb: int = 0
    assigned_tier: int = 3

    # ── Model catalog & downloads ────────────────────────────
    model_name: str = ""
    available_models: list[dict[str, Any]] = field(default_factory=list)
    downloaded_models: list[str] = field(default_factory=list)

    # ── LLM provider / routing ───────────────────────────────
    backend: str = "ollama"
    llm_provider: str = "ollama"
    api_key: str = ""
    external_model: str = ""


class SetupWizardApp(App):
    """Zero-Touch, Hardware-Aware LLM Orchestrator Setup Wizard."""

    TITLE = "smart-db Setup Wizard"

    # Base CSS for a premium dark-mode feel
    CSS = """
    Screen {
        background: #111111;
        color: #eeeeee;
    }

    .panel {
        background: #1e1e1e;
        border: tall #00ffcc;
        border-title-background: #00ffcc;
        border-title-color: #111111;
        padding: 1 2;
        margin: 2 4;
        height: 1fr;
    }

    .title {
        text-align: center;
        text-style: bold;
        color: #00ffcc;
        padding: 1;
        margin-bottom: 1;
    }

    Button {
        width: 1fr;
        margin: 0 1;
    }

    Button.-primary {
        background: #00ffcc;
        color: #111111;
        text-style: bold;
    }

    Button.-primary:hover {
        background: #ffffff;
    }

    #welcome-text, #model-explanation, #deploy-summary, #api-explanation {
        text-align: center;
        margin: 1 0;
    }

    #model-recommendation {
        text-align: center;
        margin-top: 1;
    }

    #status-text {
        text-align: center;
        margin: 1 0;
        color: #00ffcc;
    }

    #results-container {
        padding: 1 2;
        border: solid #00ffcc;
        background: #222222;
        margin: 1 0;
        height: auto;
    }

    #results-text {
        text-align: center;
    }

    #models-text {
        margin-top: 1;
    }

    #action-buttons, #deploy-action-buttons {
        height: auto;
        align: center middle;
    }

    #docker-log {
        height: 1fr;
        max-height: 10;
        border: solid #00ffcc;
        margin: 1 0;
        background: #000000;
        padding: 1;
    }

    /* ── Model Selection Screen ──────────────────────────── */

    #model-list {
        height: 1fr;
        max-height: 10;
        margin: 1 0;
        border: solid #333333;
        background: #1a1a2e;
    }

    #action-panel {
        height: auto;
        min-height: 3;
        align: center middle;
    }

    #action-panel Button {
        min-width: 20;
    }

    #progress-area {
        margin: 1 0;
        padding: 1 2;
        border: solid #333333;
        background: #1a1a2e;
        height: 1fr;
        max-height: 12;
    }

    #dl-status-label {
        text-align: center;
        margin-bottom: 1;
        color: #00ffcc;
    }

    #dl-progress {
        margin: 0 2;
    }

    #dl-detail-label {
        text-align: center;
        margin-top: 1;
        color: #8b949e;
    }

    #control-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    #control-buttons Button {
        min-width: 20;
    }

    /* ── API Settings Screen ─────────────────────────────── */

    #provider-label {
        margin: 1 0 0 0;
        text-style: bold;
        color: #00ffcc;
    }

    #provider-radio {
        margin: 0 2 1 2;
        height: auto;
        background: #1a1a2e;
        border: solid #333333;
        padding: 1;
    }

    #api-key-section, #model-override-section {
        height: auto;
        margin: 0 0 1 0;
    }

    #api-key-label, #model-override-label {
        margin: 0 0 0 0;
        color: #00ffcc;
    }

    #api-key-input, #model-override-input {
        margin: 0 2;
        background: #1a1a2e;
        border: solid #333333;
    }

    #test-section {
        height: auto;
        margin: 1 0;
    }

    #test-status-label {
        text-align: center;
        margin: 1 0;
    }

    #api-action-buttons {
        height: auto;
        align: center middle;
    }

    #api-action-buttons Button {
        min-width: 22;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.state = SetupState()

    def on_mount(self) -> None:
        """Set up the application on startup."""
        # Install screens in wizard flow order
        self.install_screen(WelcomeScreen(), name="welcome")
        self.install_screen(HardwareScanningScreen(), name="hardware")
        self.install_screen(ModelSelectionScreen(), name="model_select")
        self.install_screen(APISettingsScreen(), name="api_settings")
        self.install_screen(DeploymentScreen(), name="deployment")

        # Push the initial screen
        self.push_screen("welcome")


if __name__ == "__main__":
    app = SetupWizardApp()
    app.run()
