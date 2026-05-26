"""
Model Selection Screen — interactive model download with progress tracking.

Uses a SelectionList for multi-select, httpx for async streaming downloads
from the Ollama API, and a ProgressBar for real-time feedback. Supports
play/pause via httpx task cancellation (Ollama retains partial layers).
"""

from __future__ import annotations

import json
import asyncio
import logging
from typing import Any

import httpx
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ProgressBar,
    SelectionList,
    Static,
)
from textual.containers import Horizontal, Vertical
from textual import work

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


class ModelSelectionScreen(Screen):
    """Interactive model selection with async Ollama pull and progress."""

    def __init__(self) -> None:
        super().__init__()
        self._download_task: asyncio.Task[None] | None = None
        self._download_cancelled = False
        self._download_queue: list[str] = []
        self._current_model: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="model-panel"):
            yield Static("🤖 Model Selection", classes="title")
            yield Static(
                "Select models to download. Only models that fit in your "
                "VRAM are listed.\nThe recommended model is pre-selected.",
                id="model-explanation",
            )

            # SelectionList — populated on mount
            yield SelectionList[str](id="model-list")

            with Horizontal(id="download-buttons"):
                yield Button(
                    "⭐ Download Recommended",
                    id="dl-recommended-btn",
                    variant="primary",
                )
                yield Button(
                    "📥 Download Selected",
                    id="dl-selected-btn",
                )
                yield Button(
                    "📦 Download All Suitable",
                    id="dl-all-btn",
                )

            # Download progress area
            with Vertical(id="progress-area"):
                yield Label("", id="dl-status-label")
                yield ProgressBar(id="dl-progress", total=100, show_eta=False)
                yield Label("", id="dl-detail-label")

            with Horizontal(id="control-buttons"):
                yield Button(
                    "⏸ Pause",
                    id="pause-btn",
                    disabled=True,
                )
                yield Button(
                    "▶ Resume",
                    id="resume-btn",
                    disabled=True,
                )
                yield Button(
                    "Continue to API Settings →",
                    id="continue-btn",
                    variant="primary",
                    disabled=True,
                )

        yield Footer()

    def on_mount(self) -> None:
        """Populate the selection list from the hardware scan results."""
        self.query_one("#progress-area").display = False

        selection_list = self.query_one("#model-list", SelectionList)
        models = self.app.state.available_models

        for model in models:
            if not model.get("fits", False):
                continue

            vram = model["vram_required_mb"]
            label = f"{model['name']:20s}  ({vram:,} MB)"

            if model.get("is_recommended", False):
                label += "  ⭐ RECOMMENDED"

            selection_list.add_option((label, model["name"]))

        # Pre-select the recommended model using the UI-local index
        ui_index = 0
        for model in models:
            if model.get("fits"):
                if model.get("is_recommended"):
                    selection_list.select(
                        selection_list.get_option_at_index(ui_index)
                    )
                    break
                ui_index += 1


        # If no models fit, disable download buttons
        fitting = [m for m in models if m.get("fits", False)]
        if not fitting:
            self.query_one("#dl-recommended-btn", Button).disabled = True
            self.query_one("#dl-selected-btn", Button).disabled = True
            self.query_one("#dl-all-btn", Button).disabled = True
            self.query_one("#continue-btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "dl-recommended-btn":
            self._start_download_recommended()
        elif btn_id == "dl-selected-btn":
            self._start_download_selected()
        elif btn_id == "dl-all-btn":
            self._start_download_all()
        elif btn_id == "pause-btn":
            self._pause_download()
        elif btn_id == "resume-btn":
            self._resume_download()
        elif btn_id == "continue-btn":
            self.app.push_screen("api_settings")

    # ── Download Triggers ────────────────────────────────────

    def _start_download_recommended(self) -> None:
        """Download only the recommended model."""
        models = self.app.state.available_models
        recommended = [
            m["name"]
            for m in models
            if m.get("is_recommended") and m.get("fits")
        ]
        if recommended:
            self._begin_download_queue(recommended)

    def _start_download_selected(self) -> None:
        """Download all currently selected models."""
        selection_list = self.query_one("#model-list", SelectionList)
        selected = list(selection_list.selected)
        if selected:
            self._begin_download_queue(selected)

    def _start_download_all(self) -> None:
        """Download all models that fit in VRAM."""
        models = self.app.state.available_models
        fitting = [m["name"] for m in models if m.get("fits")]
        if fitting:
            self._begin_download_queue(fitting)

    @work
    async def _begin_download_queue(self, model_names: list[str]) -> None:
        """
        Ensure Ollama is running (lazy start), then process the queue.

        On-demand approach: the Ollama container is only started when the
        user actually initiates a download, saving GPU resources if they
        only intend to use a cloud API provider.
        """
        self._download_queue = list(model_names)
        self._download_cancelled = False

        # Disable download buttons while we spin up
        self.query_one("#dl-recommended-btn", Button).disabled = True
        self.query_one("#dl-selected-btn", Button).disabled = True
        self.query_one("#dl-all-btn", Button).disabled = True
        self.query_one("#pause-btn", Button).disabled = True
        self.query_one("#resume-btn", Button).disabled = True
        self.query_one("#progress-area").display = True

        # ── Lazy-start Ollama ────────────────────────────────
        status_label = self.query_one("#dl-status-label", Label)
        detail_label = self.query_one("#dl-detail-label", Label)
        status_label.update(
            "[bold cyan]🔄 Starting Ollama Engine...[/bold cyan]"
        )
        detail_label.update(
            "[dim]Launching container and waiting for API readiness...[/dim]"
        )

        from tui.utils.docker_manager import ensure_ollama_running

        success, message = await ensure_ollama_running()

        if not success:
            status_label.update(
                "[bold red]❌ Failed to start Ollama[/bold red]"
            )
            detail_label.update(f"[bold red]{message}[/bold red]")
            # Re-enable buttons so user can retry
            self.query_one("#dl-recommended-btn", Button).disabled = False
            self.query_one("#dl-selected-btn", Button).disabled = False
            self.query_one("#dl-all-btn", Button).disabled = False
            return

        status_label.update(
            "[bold green]✅ Ollama is ready![/bold green]"
        )
        detail_label.update("")

        # ── Proceed with downloads ───────────────────────────
        self.query_one("#pause-btn", Button).disabled = False
        await self._process_download_queue()

    async def _process_download_queue(self) -> None:
        """Process the download queue one model at a time."""
        while self._download_queue and not self._download_cancelled:
            model_name = self._download_queue.pop(0)
            self._current_model = model_name

            status_label = self.query_one("#dl-status-label", Label)
            remaining = len(self._download_queue)
            status_label.update(
                f"[bold cyan]Downloading:[/bold cyan] {model_name}"
                + (f"  [dim]({remaining} more in queue)[/dim]" if remaining else "")
            )

            progress = self.query_one("#dl-progress", ProgressBar)
            progress.update(total=100, progress=0)

            success = await self._download_model(model_name)

            if success:
                if model_name not in self.app.state.downloaded_models:
                    self.app.state.downloaded_models.append(model_name)
                self.query_one("#dl-detail-label", Label).update(
                    f"[bold green]✅ {model_name} downloaded successfully![/bold green]"
                )
            elif self._download_cancelled:
                self.query_one("#dl-detail-label", Label).update(
                    f"[bold yellow]⏸ {model_name} paused[/bold yellow]"
                )
                # Re-insert at front for resume
                self._download_queue.insert(0, model_name)
                break
            else:
                self.query_one("#dl-detail-label", Label).update(
                    f"[bold red]❌ {model_name} download failed[/bold red]"
                )

        # Queue finished or paused
        if not self._download_queue or not self._download_cancelled:
            self._download_finished()
        else:
            # Paused state
            self.query_one("#pause-btn", Button).disabled = True
            self.query_one("#resume-btn", Button).disabled = False

    async def _download_model(self, model_name: str) -> bool:
        """
        Download a single model via Ollama API with streaming progress.

        Returns True on success, False on failure or cancellation.
        """
        progress = self.query_one("#dl-progress", ProgressBar)
        detail_label = self.query_one("#dl-detail-label", Label)

        try:
            async with httpx.AsyncClient(
                base_url=OLLAMA_BASE_URL,
                timeout=httpx.Timeout(600.0, connect=30.0),
            ) as client:
                async with client.stream(
                    "POST",
                    "/api/pull",
                    json={"name": model_name, "stream": True},
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if self._download_cancelled:
                            return False

                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        status = data.get("status", "")
                        total = data.get("total", 0)
                        completed = data.get("completed", 0)

                        # Update progress bar
                        if total > 0:
                            pct = int((completed / total) * 100)
                            progress.update(total=100, progress=pct)

                            # Human-readable sizes
                            total_gb = total / (1024 ** 3)
                            done_gb = completed / (1024 ** 3)
                            detail_label.update(
                                f"[dim]{status}[/dim]  "
                                f"{done_gb:.2f} GB / {total_gb:.2f} GB"
                            )
                        else:
                            detail_label.update(f"[dim]{status}[/dim]")

            # If we get here without cancellation, it's a success
            progress.update(total=100, progress=100)
            return True

        except httpx.ConnectError:
            detail_label.update(
                "[bold red]Cannot connect to Ollama at "
                f"{OLLAMA_BASE_URL}[/bold red]\n"
                "[dim]Make sure Ollama is running: docker compose up ollama[/dim]"
            )
            return False
        except httpx.HTTPStatusError as exc:
            detail_label.update(
                f"[bold red]HTTP {exc.response.status_code}[/bold red]: "
                f"{exc.response.text[:200]}"
            )
            return False
        except Exception as exc:
            logger.exception("Unexpected error downloading %s", model_name)
            detail_label.update(f"[bold red]Error:[/bold red] {exc}")
            return False

    # ── Play / Pause ─────────────────────────────────────────

    def _pause_download(self) -> None:
        """Pause the current download by signalling cancellation."""
        self._download_cancelled = True
        self.query_one("#pause-btn", Button).disabled = True
        self.query_one("#dl-status-label", Label).update(
            f"[bold yellow]Pausing {self._current_model}...[/bold yellow]"
        )

    def _resume_download(self) -> None:
        """Resume downloading from where we left off."""
        self._download_cancelled = False
        self.query_one("#resume-btn", Button).disabled = True
        self.query_one("#pause-btn", Button).disabled = False
        self._resume_with_ollama()

    @work
    async def _resume_with_ollama(self) -> None:
        """Worker wrapper for resuming downloads (Ollama already running)."""
        await self._process_download_queue()

    def _download_finished(self) -> None:
        """Clean up UI state after all downloads complete."""
        self.query_one("#pause-btn", Button).disabled = True
        self.query_one("#resume-btn", Button).disabled = True

        # Re-enable download buttons
        self.query_one("#dl-recommended-btn", Button).disabled = False
        self.query_one("#dl-selected-btn", Button).disabled = False
        self.query_one("#dl-all-btn", Button).disabled = False

        # Enable continue
        downloaded = self.app.state.downloaded_models
        if downloaded:
            self.query_one("#continue-btn", Button).disabled = False
            self.query_one("#dl-status-label", Label).update(
                f"[bold green]✅ {len(downloaded)} model(s) ready![/bold green]"
            )
        else:
            # Allow continue even without downloads (user may use external LLM)
            self.query_one("#continue-btn", Button).disabled = False
            self.query_one("#dl-status-label", Label).update(
                "[bold yellow]No models downloaded. "
                "You can configure an external LLM provider next.[/bold yellow]"
            )
