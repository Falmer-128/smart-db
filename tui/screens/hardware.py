"""
Hardware Scanning Screen — async GPU detection with VRAM regression alerts.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Header, Footer, LoadingIndicator
from textual.containers import Vertical, Horizontal
from textual import work

from tui.utils.hardware_scanner import get_hardware_specs, HardwareSpecs
from tui.widgets.vram_warning_modal import VRAMWarningModal


class HardwareScanningScreen(Screen):
    """Scans hardware and displays the results with model compatibility."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="scan-panel"):
            yield Static("🔍 Hardware Scanner", classes="title")
            yield LoadingIndicator(id="loading")
            yield Static(
                "Scanning system for GPU capabilities...", id="status-text"
            )

            with Vertical(id="results-container"):
                yield Static("", id="results-text")
                yield Static("", id="models-text")

            with Horizontal(id="action-buttons"):
                yield Button("Retry Scan", id="retry_btn")
                yield Button(
                    "Continue to Model Selection",
                    variant="primary",
                    id="continue_btn",
                    disabled=True,
                )
        yield Footer()

    def on_mount(self) -> None:
        """Starts the hardware scan automatically when the screen mounts."""
        self.query_one("#results-container").display = False
        self.query_one("#action-buttons").display = False
        self.run_scan()

    @work
    async def run_scan(self) -> None:
        """Runs the hardware scan asynchronously."""
        self._update_status("Querying nvidia-smi...")
        specs = await get_hardware_specs()

        # Update the global app state
        state = self.app.state
        state.os_name = specs.os_name
        state.gpu_present = specs.gpu_present
        state.gpu_name = specs.gpu_name
        state.raw_vram_mb = specs.raw_vram_mb
        state.usable_vram_mb = specs.usable_vram_mb
        state.assigned_tier = specs.assigned_tier
        state.available_models = [
            {
                "name": m.name,
                "vram_required_mb": m.vram_required_mb,
                "param_label": m.param_label,
                "fits": m.fits,
                "is_recommended": m.is_recommended,
            }
            for m in specs.available_models
        ]

        # Check for VRAM regression warning
        if specs.vram_warning and specs.vram_delta_pct is not None:
            from tui.utils.hardware_scanner import _load_registry

            registry = _load_registry()
            old_vram = registry.get("last_raw_vram_mb", 0)

            result = await self.app.push_screen_wait(
                VRAMWarningModal(
                    old_vram_mb=old_vram,
                    new_vram_mb=specs.raw_vram_mb,
                    delta_pct=specs.vram_delta_pct,
                )
            )

            if not result:
                # User chose to abort
                self.app.exit(message="Setup aborted due to VRAM regression.")
                return

        # Show results
        self._show_results(specs)

    def _update_status(self, message: str) -> None:
        """Updates the status text label."""
        self.query_one("#status-text", Static).update(message)

    def _show_results(self, specs: HardwareSpecs) -> None:
        """Reveals the results container and populates the text."""
        self.query_one("#loading").display = False
        self.query_one("#status-text").display = False

        # Format GPU results
        if specs.gpu_present:
            gpu_status = f"[bold green]✅ {specs.gpu_name}[/bold green]"
            vram_info = (
                f"Raw VRAM: [bold]{specs.raw_vram_mb:,}[/bold] MB\n"
                f"Usable VRAM: [bold cyan]{specs.usable_vram_mb:,}[/bold cyan] MB "
                f"[dim](after 1.5 GB OS overhead)[/dim]"
            )
        else:
            gpu_status = (
                "[bold yellow]⚠ No NVIDIA GPU Detected[/bold yellow]\n"
                "[dim]Drivers may be missing, or this is a CPU-only system.[/dim]"
            )
            vram_info = "Using CPU fallback mode."

        delta_info = ""
        if specs.vram_delta_pct is not None:
            color = "green" if specs.vram_delta_pct >= 0 else "red"
            delta_info = (
                f"\nVRAM vs. last session: "
                f"[bold {color}]{specs.vram_delta_pct:+.1f}%[/bold {color}]"
            )

        results = (
            f"[bold]OS:[/bold] {specs.os_name}\n\n"
            f"[bold]GPU:[/bold] {gpu_status}\n"
            f"{vram_info}{delta_info}\n\n"
            f"[bold cyan]Assigned Tier: {specs.assigned_tier}[/bold cyan]"
        )

        self.query_one("#results-text", Static).update(results)

        # Format model compatibility table
        fitting = [m for m in specs.available_models if m.fits]
        too_large = [m for m in specs.available_models if not m.fits]

        lines: list[str] = ["[bold]Model Compatibility:[/bold]\n"]

        for m in fitting:
            badge = " [bold green]⭐ RECOMMENDED[/bold green]" if m.is_recommended else ""
            lines.append(
                f"  [green]✅[/green] {m.name:20s} "
                f"[dim]({m.vram_required_mb:>6,} MB)[/dim]{badge}"
            )

        if too_large:
            lines.append("")
            for m in too_large:
                lines.append(
                    f"  [red]❌[/red] {m.name:20s} "
                    f"[dim]({m.vram_required_mb:>6,} MB) — exceeds VRAM[/dim]"
                )

        if not fitting:
            lines.append(
                "  [yellow]No models fit in VRAM. CPU fallback will be used.[/yellow]"
            )

        self.query_one("#models-text", Static).update("\n".join(lines))

        self.query_one("#results-container").display = True
        self.query_one("#action-buttons").display = True
        self.query_one("#continue_btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry_btn":
            # Reset UI state and retry the scan
            self.query_one("#results-container").display = False
            self.query_one("#action-buttons").display = False
            self.query_one("#continue_btn", Button).disabled = True

            self.query_one("#loading").display = True
            self.query_one("#status-text").display = True
            self._update_status("Retrying scan...")

            self.run_scan()

        elif event.button.id == "continue_btn":
            self.app.push_screen("model_select")
