"""
Model Selection Screen — interactive model download with progress tracking.

Uses a SelectionList for multi-select, httpx for async streaming downloads
from the Ollama API, and a ProgressBar for real-time feedback. Supports
cancellation via Docker SIGTERM for graceful daemon cleanup.

UI is composed STATICALLY. State transitions are managed EXCLUSIVELY
by toggling ``button.disabled``.  No ``ContentSwitcher`` or
``display = False`` is used anywhere.
"""

from __future__ import annotations

import json
import asyncio
import logging
from enum import Enum
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
    RichLog,
    SelectionList,
    Static,
)
from textual.containers import Horizontal, Vertical
from textual import work

from tui.utils.docker_manager import DockerManager

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


class DownloadState(Enum):
    IDLE = 1
    DOWNLOADING = 2
    FINISHED = 3


class ModelSelectionScreen(Screen):
    """Interactive model selection with async Ollama pull and progress."""

    def __init__(self) -> None:
        super().__init__()
        self._download_task: asyncio.Task[None] | None = None
        self._download_cancelled = False
        self._download_queue: list[str] = []
        self._current_model: str = ""
        self.docker_manager = DockerManager()
        self.current_state = DownloadState.IDLE

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="model-panel"):
            yield Static("🤖 Model Selection", classes="title")
            yield Static(
                "Select models to download. Only models that fit in your VRAM are listed.\nThe recommended model is pre-selected.",
                id="model-explanation",
            )

            yield SelectionList[str](id="model-list")

            # ── Static action panel: ALL buttons live here permanently ──
            with Horizontal(id="action-panel", classes="button-row"):
                yield Button("⭐ Download Recommended", id="dl-recommended-btn", variant="primary")
                yield Button("📥 Download Selected", id="dl-selected-btn")
                yield Button("📦 Download All Suitable", id="dl-all-btn")
                yield Button("⏭ Skip (Use Cloud API)", id="skip-btn", variant="error", disabled=False)
                yield Button("Continue to API Settings →", id="continue-btn", variant="success", disabled=True)

            # ── Progress area: always present, content updated in-place ──
            with Vertical(id="progress-area"):
                yield Label("", id="dl-status-label")
                yield ProgressBar(id="dl-progress", total=100, show_eta=False)
                yield Label("", id="dl-detail-label")
                yield RichLog(id="docker-log", markup=True)

        yield Footer()

    # ── UI State Machine ─────────────────────────────────────

    def update_ui_state(self, state: DownloadState) -> None:
        """Transition UI by toggling button.disabled — nothing else."""
        self.current_state = state

        dl_rec = self.query_one("#dl-recommended-btn", Button)
        dl_sel = self.query_one("#dl-selected-btn", Button)
        dl_all = self.query_one("#dl-all-btn", Button)
        skip   = self.query_one("#skip-btn", Button)
        cont   = self.query_one("#continue-btn", Button)

        if state == DownloadState.IDLE:
            dl_rec.disabled = False
            dl_sel.disabled = False
            dl_all.disabled = False
            skip.disabled   = False
            self._update_continue_btn()

        elif state == DownloadState.DOWNLOADING:
            dl_rec.disabled = True
            dl_sel.disabled = True
            dl_all.disabled = True
            skip.disabled   = False   # user can always skip during download

            cont.disabled   = True

        elif state == DownloadState.FINISHED:
            dl_rec.disabled = False
            dl_sel.disabled = False
            dl_all.disabled = False
            skip.disabled   = True
            self._update_continue_btn()

    def _update_continue_btn(self) -> None:
        downloaded = getattr(self.app.state, "downloaded_models", [])
        if downloaded:
            self.query_one("#continue-btn", Button).disabled = False

    def on_mount(self) -> None:
        """Populate the selection list from the hardware scan results."""
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
        elif btn_id == "skip-btn":
            self._skip_download()
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
        """
        self._download_queue = list(model_names)
        self._download_cancelled = False

        self.update_ui_state(DownloadState.DOWNLOADING)

        status_label = self.query_one("#dl-status-label", Label)
        detail_label = self.query_one("#dl-detail-label", Label)
        docker_log = self.query_one("#docker-log", RichLog)

        docker_log.clear()
        progress = self.query_one("#dl-progress", ProgressBar)
        progress.update(total=100, progress=0)

        status_label.update(
            "[bold cyan]🔄 Starting Ollama Engine...[/bold cyan]",
        )
        detail_label.update(
            "[dim]Launching container and waiting for API readiness...[/dim]",
        )

        def log_callback(line: str) -> None:
            # Safely schedule log updates in the main thread
            docker_log.write(line.rstrip("\n"))

        docker_status = await self.docker_manager.ensure_ollama_running(
            log_callback=log_callback
        )

        if not docker_status.success:
            if docker_status.message == "Cancelled by user":
                # Skip was clicked — state transition handled in _skip_download
                return
            else:
                status_label.update(
                    "[bold red]❌ Failed to start Ollama[/bold red]",
                )
                detail_label.update(
                    f"[bold red]{docker_status.message}[/bold red]",
                )
                # Brief pause so the user can read the error
                await asyncio.sleep(2)
                self.update_ui_state(DownloadState.IDLE)
                return

        status_label.update(
            "[bold green]✅ Ollama is ready![/bold green]",
        )
        detail_label.update("")

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
                + (f"  [dim]({remaining} more in queue)[/dim]" if remaining else ""),
            )

            progress = self.query_one("#dl-progress", ProgressBar)
            progress.update(total=100, progress=0)

            success = await self._download_model(model_name)

            detail_label = self.query_one("#dl-detail-label", Label)
            if success:
                if model_name not in self.app.state.downloaded_models:
                    self.app.state.downloaded_models.append(model_name)
                detail_label.update(
                    f"[bold green]✅ {model_name} downloaded successfully![/bold green]",
                )
            elif self._download_cancelled:
                break
            else:
                detail_label.update(
                    f"[bold red]❌ {model_name} download failed[/bold red]",
                )

        # Queue finished
        if not self._download_cancelled:
            self._download_finished()

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
                                f"{done_gb:.2f} GB / {total_gb:.2f} GB",
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
                "[dim]Make sure Ollama is running: docker compose up ollama[/dim]",
            )
            return False
        except httpx.HTTPStatusError as exc:
            detail_label.update(
                f"[bold red]HTTP {exc.response.status_code}[/bold red]: "
                f"{exc.response.text[:200]}",
            )
            return False
        except Exception as exc:
            logger.exception("Unexpected error downloading %s", model_name)
            detail_label.update(f"[bold red]Error:[/bold red] {exc}")
            return False

    # ── Skip ─────────────────────────────────────────────────

    def _skip_download(self) -> None:
        """Skip all downloading and proceed to cloud API setup."""
        self._download_cancelled = True
        self.docker_manager.abort_all()
        self._download_queue.clear()

        # Transition: disable skip, enable continue
        self.query_one("#skip-btn", Button).disabled = True
        self.query_one("#continue-btn", Button).disabled = False

        self.app.push_screen("api_settings")

    # ── Completion ───────────────────────────────────────────

    def _download_finished(self) -> None:
        """Clean up UI state after all downloads complete."""
        self.update_ui_state(DownloadState.FINISHED)

        status_label = self.query_one("#dl-status-label", Label)

        downloaded = getattr(self.app.state, "downloaded_models", [])
        if downloaded:
            status_label.update(
                f"[bold green]✅ {len(downloaded)} model(s) ready![/bold green]"
            )
        else:
            status_label.update(
                "[bold yellow]No models downloaded. "
                "You can configure an external LLM provider next.[/bold yellow]"
            )
