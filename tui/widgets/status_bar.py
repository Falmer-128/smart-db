"""
StatusBar — bottom status strip showing pipeline state, file counts,
and the last operation result.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static
from textual.widget import Widget


class StatusBar(Widget):
    """
    Three-segment status bar:
      [pipeline state]  [file counts]  [last operation]
    """

    pipeline_status: reactive[str] = reactive("● Idle")
    file_counts: reactive[str] = reactive("INPUT: — | PROCESSED: —")
    last_operation: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Static(self.pipeline_status, id="status-pipeline")
        yield Static(self.file_counts, id="status-counts")
        yield Static(self.last_operation, id="status-last-op")

    # ── Reactive watchers ────────────────────────────────────

    def watch_pipeline_status(self, value: str) -> None:
        try:
            self.query_one("#status-pipeline", Static).update(value)
        except Exception:
            pass

    def watch_file_counts(self, value: str) -> None:
        try:
            self.query_one("#status-counts", Static).update(value)
        except Exception:
            pass

    def watch_last_operation(self, value: str) -> None:
        try:
            self.query_one("#status-last-op", Static).update(value)
        except Exception:
            pass

    # ── Public helpers ───────────────────────────────────────

    def set_idle(self) -> None:
        self.pipeline_status = "[#7ee787]● Idle[/]"

    def set_processing(self, detail: str = "") -> None:
        msg = "[#58a6ff]◉ Processing[/]"
        if detail:
            msg += f" [#8b949e]{detail}[/]"
        self.pipeline_status = msg

    def set_error(self, detail: str = "") -> None:
        msg = "[#f85149]● Error[/]"
        if detail:
            msg += f" [#8b949e]{detail}[/]"
        self.pipeline_status = msg

    def update_counts(self, input_count: int, processed_count: int) -> None:
        self.file_counts = (
            f"[#8b949e]INPUT:[/] [bold]{input_count}[/]"
            f"  [#30363d]│[/]  "
            f"[#8b949e]PROCESSED:[/] [bold]{processed_count}[/]"
        )

    def set_last_op(self, message: str) -> None:
        self.last_operation = f"[#d2a8ff]{message}[/]"
