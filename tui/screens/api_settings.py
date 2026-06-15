"""
API Settings Screen — configure external LLM providers.

Supports Local Ollama, OpenRouter, and NVIDIA NIM backends.
Saves API keys and provider selection to .env for docker-compose
and the LLM router to consume.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    Select,
)
from textual.containers import Horizontal, Vertical
from textual import work


class APISettingsScreen(Screen):
    """Configure LLM backend provider, API keys, and model overrides."""

    DEFAULT_MODELS = {
        "ollama": "gemma-4-31b-it",
        "openrouter": "gemma-4-31b-it",
        "nvidia_nim": "meta/llama-3.1-8b-instruct",
        "google_gemini": "gemma-4-31b-it",
    }

    def __init__(self) -> None:
        super().__init__()
        self._selected_provider: str = "ollama"

    def compose(self) -> ComposeResult:
        load_dotenv(os.path.join(os.getcwd(), ".env"))
        
        backend = os.environ.get("LLM_BACKEND", "ollama")
        api_key = ""
        model_override = ""
        
        if backend == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            model_override = os.environ.get("OPENROUTER_MODEL") or os.environ.get("LLM_MODEL", "")
        elif backend == "nvidia_nim":
            api_key = os.environ.get("NVIDIA_NIM_API_KEY", "")
            model_override = os.environ.get("NVIDIA_NIM_MODEL") or os.environ.get("LLM_MODEL", "")
        elif backend == "google_gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            model_override = os.environ.get("GEMINI_MODEL") or os.environ.get("LLM_MODEL", "")
        else:
            model_override = os.environ.get("LLM_MODEL", "")

        vision_provider = os.environ.get("VISION_PROVIDER", "google")
        vision_api_key = os.environ.get("VISION_API_KEY", "")
        vision_model = os.environ.get("VISION_MODEL", "")

        yield Header()
        with Vertical(classes="panel", id="api-panel"):
            yield Static("⚙️  API Settings", classes="title")
            yield Static(
                "Choose your LLM inference backend. Local Ollama uses\n"
                "the models you just downloaded. External providers require\n"
                "an API key and will route queries to the cloud.",
                id="api-explanation",
            )

            # Provider selection
            yield Label("[bold]LLM Backend:[/bold]", id="provider-label")
            with RadioSet(id="provider-radio"):
                yield RadioButton("Local Ollama", value=(backend == "ollama"), id="radio-ollama")
                yield RadioButton("OpenRouter", value=(backend == "openrouter"), id="radio-openrouter")
                yield RadioButton("NVIDIA NIM", value=(backend == "nvidia_nim"), id="radio-nvidia-nim")
                yield RadioButton("Google (Gemini)", value=(backend == "google_gemini"), id="radio-google-gemini")

            # API Key input (hidden for Ollama)
            with Vertical(id="api-key-section"):
                yield Label("[bold]API Key:[/bold]", id="api-key-label")
                yield Input(
                    value=api_key,
                    placeholder="Enter your API key...",
                    password=True,
                    id="api-key-input",
                )

            # Model override input
            with Vertical(id="model-override-section"):
                yield Label(
                    "[bold]Model Override:[/bold] [dim](leave blank for default)[/dim]",
                    id="model-override-label",
                )
                yield Input(
                    value=model_override,
                    placeholder="e.g. meta-llama/llama-3.1-8b-instruct",
                    id="model-override-input",
                )

            # Vision Provider Section
            yield Static("👁️  Vision Provider (Tier 3 OCR)", classes="subtitle", id="vision-title")
            yield Label("[bold]Vision Provider:[/bold]", id="vision-provider-label")
            yield Select(
                [
                    ("Google Gemini", "google"),
                    ("Anthropic Claude", "anthropic"),
                    ("OpenAI", "openai"),
                    ("OpenRouter", "openrouter"),
                    ("Nvidia NIM", "nvidia")
                ],
                value=vision_provider,
                id="vision-provider-select"
            )
            
            yield Label("[bold]Vision API Key:[/bold]", id="vision-key-label")
            yield Input(
                value=vision_api_key,
                placeholder="Enter vision provider API key...",
                password=True,
                id="vision-key-input",
            )
            
            yield Label("[bold]Vision Model ID:[/bold] [dim](leave blank for default)[/dim]", id="vision-model-label")
            yield Input(
                value=vision_model,
                placeholder="e.g. gemini-3.1-flash-lite",
                id="vision_model_input",
            )

            # Connection test
            with Vertical(id="test-section"):
                yield Label("", id="test-status-label")

            with Horizontal(id="api-action-buttons"):
                yield Button(
                    "🔌 Test Connection",
                    id="test-btn",
                )
                yield Button(
                    "Save & Continue →",
                    id="save-btn",
                    variant="primary",
                )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize UI state based on current app state and existing .env file."""
        backend = os.environ.get("LLM_BACKEND", "ollama")
        if backend == "ollama":
            self.query_one("#api-key-section").display = False
            self._selected_provider = "ollama"
        else:
            self.query_one("#api-key-section").display = True
            self._selected_provider = backend

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """React to provider radio button changes."""
        radio_id = event.pressed.id

        if radio_id == "radio-ollama":
            self._selected_provider = "ollama"
            self.query_one("#api-key-section").display = False
            self.query_one("#model-override-input", Input).placeholder = (
                "e.g. qwen2.5:7b (uses downloaded model)"
            )
            # Set model from downloaded models if available
            if self.app.state.downloaded_models:
                self.query_one("#model-override-input", Input).value = (
                    self.app.state.downloaded_models[0]
                )
            elif self.app.state.model_name:
                self.query_one("#model-override-input", Input).value = (
                    self.app.state.model_name
                )

        elif radio_id == "radio-openrouter":
            self._selected_provider = "openrouter"
            self.query_one("#api-key-section").display = True
            self.query_one("#api-key-input", Input).placeholder = (
                "sk-or-... (OpenRouter API key)"
            )
            self.query_one("#model-override-input", Input).placeholder = (
                "e.g. meta-llama/llama-3.1-8b-instruct"
            )
            self.query_one("#model-override-input", Input).value = (
                self.DEFAULT_MODELS["openrouter"]
            )

        elif radio_id == "radio-nvidia-nim":
            self._selected_provider = "nvidia_nim"
            self.query_one("#api-key-section").display = True
            self.query_one("#api-key-input", Input).placeholder = (
                "nvapi-... (NVIDIA NIM API key)"
            )
            self.query_one("#model-override-input", Input).placeholder = (
                "e.g. meta/llama-3.1-8b-instruct"
            )
            self.query_one("#model-override-input", Input).value = (
                self.DEFAULT_MODELS["nvidia_nim"]
            )

        elif radio_id == "radio-google-gemini":
            self._selected_provider = "google_gemini"
            self.query_one("#api-key-section").display = True
            self.query_one("#api-key-input", Input).placeholder = (
                "AIzaSy... (Gemini API key)"
            )
            self.query_one("#model-override-input", Input).placeholder = (
                "e.g. gemma-4-31b-it"
            )
            self.query_one("#model-override-input", Input).value = (
                self.DEFAULT_MODELS["google_gemini"]
            )

        # Clear test status on provider change
        self.query_one("#test-status-label", Label).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test-btn":
            self._test_connection()
        elif event.button.id == "save-btn":
            self._save_and_continue()

    @work
    async def _test_connection(self) -> None:
        """Test connectivity to the selected LLM provider."""
        status_label = self.query_one("#test-status-label", Label)
        status_label.update("[bold cyan]🔄 Testing connection...[/bold cyan]")

        api_key = self.query_one("#api-key-input", Input).value
        model = self.query_one("#model-override-input", Input).value

        try:
            from core.llm_router import LLMRouter, LLMRouterConfig, LLMProvider

            provider = LLMProvider(self._selected_provider)

            config = LLMRouterConfig(
                provider=provider,
                model_name=model or "",
                api_key=api_key,
            )

            router = LLMRouter(config)
            success, message = await router.test_connection()
            await router.close()

            if success:
                status_label.update(
                    f"[bold green]✅ {message}[/bold green]"
                )
            else:
                status_label.update(
                    f"[bold red]❌ {message}[/bold red]"
                )

        except Exception as exc:
            status_label.update(
                f"[bold red]❌ Error: {exc}[/bold red]"
            )

    def _save_and_continue(self) -> None:
        """Save settings to .env and app state, then advance."""
        state = self.app.state

        api_key = self.query_one("#api-key-input", Input).value.strip()
        model_override = self.query_one("#model-override-input", Input).value.strip()

        state.llm_provider = self._selected_provider
        state.backend = self._selected_provider
        state.api_key = api_key

        if model_override:
            state.model_name = model_override
            if self._selected_provider != "ollama":
                state.external_model = model_override
                
        # Save Vision settings to state
        state.vision_provider = self.query_one("#vision-provider-select", Select).value
        state.vision_api_key = self.query_one("#vision-key-input", Input).value.strip()
        state.vision_model = self.query_one("#vision_model_input", Input).value.strip()

        # Write to .env
        project_root = Path(os.getcwd())
        env_path = project_root / ".env"

        from tui.utils.docker_manager import generate_env_file

        generate_env_file(state, filepath=str(env_path))

        self.app.push_screen("deployment")
