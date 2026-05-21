from dataclasses import dataclass
from textual.app import App
from tui.screens.welcome import WelcomeScreen
from tui.screens.hardware import HardwareScanningScreen
from tui.screens.model_select import ModelSelectionScreen
from tui.screens.deployment import DeploymentScreen

@dataclass
class SetupState:
    """Holds the global state of the setup wizard."""
    os_name: str = ""
    gpu_present: bool = False
    raw_vram_mb: int = 0
    usable_vram_mb: int = 0
    assigned_tier: int = 3
    model_name: str = ""
    backend: str = "ollama"

class SetupWizardApp(App):
    """Zero-Touch, Hardware-Aware Setup Wizard."""
    
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
        height: auto;
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
        margin: 1 2;
    }
    
    Button.-primary {
        background: #00ffcc;
        color: #111111;
        text-style: bold;
    }
    
    Button.-primary:hover {
        background: #ffffff;
    }
    
    #welcome-text, #model-explanation, #deploy-summary {
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
    
    #action-buttons, #deploy-action-buttons {
        height: auto;
        align: center middle;
    }
    
    #docker-log {
        height: 1fr;
        min-height: 15;
        border: solid #00ffcc;
        margin: 1 0;
        background: #000000;
        padding: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self.state = SetupState()

    def on_mount(self) -> None:
        """Set up the application on startup."""
        # Install screens
        self.install_screen(WelcomeScreen(), name="welcome")
        self.install_screen(HardwareScanningScreen(), name="hardware")
        self.install_screen(ModelSelectionScreen(), name="model_select")
        self.install_screen(DeploymentScreen(), name="deployment")
        
        # Push the initial screen
        self.push_screen("welcome")

if __name__ == "__main__":
    app = SetupWizardApp()
    app.run()
