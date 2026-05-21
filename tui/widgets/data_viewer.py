"""
DataViewer — main content viewport for displaying file previews,
processing results, help text, and pipeline output.

Uses a RichLog internally for scrollable, styled output.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich import box


_WELCOME_TEXT = """\
[bold #58a6ff]📄 Smart Document Parser — TUI[/]

[#8b949e]Welcome to the interactive document processing console.

[bold #f0883e]Getting Started:[/]
  • Browse files in the [bold]sidebar[/] (left panel)
  • Click a file to preview its contents
  • Press [bold #7ee787]Enter[/] on a selected INPUT file to process it
  • Type commands in the [bold]command bar[/] below

[bold #f0883e]Quick Commands:[/]
  [bold #58a6ff]process all[/]    — batch-process all pending files
  [bold #58a6ff]config[/]         — show current configuration
  [bold #58a6ff]stats[/]          — show pipeline statistics
  [bold #58a6ff]refresh[/]        — rescan directories
  [bold #58a6ff]clear[/]          — clear this viewport
  [bold #58a6ff]help[/]           — show full command reference

[#484f58]Press [bold]F1[/] for help  •  [bold]Ctrl+Q[/] to quit[/]\
"""


class DataViewer(Widget):
    """
    Main viewport — renders file previews, processing results,
    and system messages into a scrollable rich-text log.
    """

    def compose(self) -> ComposeResult:
        yield Static("📋 Viewer", id="viewer-title")
        yield RichLog(
            id="data-viewer",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

    def on_mount(self) -> None:
        self.show_welcome()

    # ── Public API ───────────────────────────────────────────

    @property
    def log_widget(self) -> RichLog:
        return self.query_one("#data-viewer", RichLog)

    def show_welcome(self) -> None:
        """Display the welcome/splash screen."""
        self.log_widget.clear()
        self.log_widget.write(Text.from_markup(_WELCOME_TEXT))

    def clear(self) -> None:
        """Clear the viewport."""
        self.log_widget.clear()

    def show_file_preview(self, filename: str, content: str) -> None:
        """Display a file's content as a preview."""
        log = self.log_widget
        log.clear()

        # Title
        log.write(Text.from_markup(
            f"\n[bold #58a6ff]── Preview: {filename} ──[/]\n"
        ))

        # Content — if it looks like markdown (from Excel), syntax-highlight
        if content.strip().startswith("|") or content.strip().startswith("## Sheet:"):
            log.write(Syntax(content, "markdown", theme="monokai", word_wrap=True))
        else:
            log.write(Text(content))

        # Update title
        title = self.query_one("#viewer-title", Static)
        title.update(f"📋 {filename}")

    def show_process_result(self, result) -> None:
        """Display the result of processing a single file."""
        from services.models import ProcessResult

        log = self.log_widget

        if result.success:
            log.write(Text.from_markup(
                f"\n[bold #7ee787]✅ Successfully processed:[/] {result.source_file}"
            ))
            if result.output_path:
                log.write(Text.from_markup(
                    f"   [#8b949e]Output:[/] {result.output_path}"
                ))
            log.write(Text.from_markup(
                f"   [#8b949e]Characters extracted:[/] {result.char_count:,}"
            ))
            log.write(Text.from_markup(
                f"   [#8b949e]Duration:[/] {result.duration_seconds:.2f}s"
            ))
            if result.error_message:
                log.write(Text.from_markup(
                    f"   [#d29922]Note:[/] {result.error_message}"
                ))
        else:
            log.write(Text.from_markup(
                f"\n[bold #f85149]❌ Failed to process:[/] {result.source_file}"
            ))
            if result.error_message:
                log.write(Text.from_markup(
                    f"   [#f85149]Error:[/] {result.error_message}"
                ))

    def show_batch_result(self, result) -> None:
        """Display the result of a batch pipeline run."""
        from services.models import BatchResult

        log = self.log_widget
        log.write(Text(""))

        # Summary table
        table = Table(
            title="🏁 Batch Processing Complete",
            box=box.ROUNDED,
            title_style="bold #58a6ff",
            border_style="#30363d",
            show_header=True,
            header_style="bold #f0883e",
        )
        table.add_column("Metric", style="#8b949e")
        table.add_column("Value", style="bold")

        table.add_row("Total files", str(result.total_files))
        table.add_row("Processed", f"[#7ee787]{result.processed}[/]")
        table.add_row("Skipped", f"[#d29922]{result.skipped}[/]")
        table.add_row("Errors", f"[#f85149]{result.errors}[/]")
        table.add_row("Duration", f"{result.duration_seconds:.2f}s")

        log.write(table)

        # Per-file details
        if result.results:
            log.write(Text(""))
            for r in result.results:
                self.show_process_result(r)

    def show_config(self, config: dict[str, str]) -> None:
        """Display the current configuration as a table."""
        log = self.log_widget
        log.clear()

        table = Table(
            title="⚙️  Configuration",
            box=box.ROUNDED,
            title_style="bold #58a6ff",
            border_style="#30363d",
            show_header=True,
            header_style="bold #f0883e",
        )
        table.add_column("Setting", style="#8b949e")
        table.add_column("Value", style="bold #e6edf3")

        for key, value in config.items():
            table.add_row(key, value)

        log.write(table)

        title = self.query_one("#viewer-title", Static)
        title.update("📋 Configuration")

    def show_stats(self, stats) -> None:
        """Display pipeline statistics."""
        from services.models import PipelineStats

        log = self.log_widget
        log.clear()

        table = Table(
            title="📊 Pipeline Statistics",
            box=box.ROUNDED,
            title_style="bold #58a6ff",
            border_style="#30363d",
            show_header=True,
            header_style="bold #f0883e",
        )
        table.add_column("Metric", style="#8b949e")
        table.add_column("Value", style="bold #e6edf3")

        table.add_row("Input files", str(stats.input_file_count))
        table.add_row("Processed files", str(stats.processed_file_count))
        table.add_row("Pending", f"[#d29922]{stats.pending_count}[/]")
        table.add_row("Input total size", stats.input_total_size)
        table.add_row("Processed total size", stats.processed_total_size)

        log.write(table)

        title = self.query_one("#viewer-title", Static)
        title.update("📋 Statistics")

    def show_help(self) -> None:
        """Display the full help reference."""
        log = self.log_widget
        log.clear()

        help_text = """\
[bold #58a6ff]📖 Command Reference[/]

[bold #f0883e]File Operations:[/]
  [bold #7ee787]process <filename>[/]   Process a specific file from INPUT/
  [bold #7ee787]process all[/]          Process all pending files in INPUT/
  [bold #7ee787]preview <filename>[/]   Preview a file's content

[bold #f0883e]Navigation:[/]
  [bold #7ee787]refresh[/]              Rescan INPUT/ and PROCESSED/ directories
  [bold #7ee787]clear[/]               Clear the viewer panel

[bold #f0883e]Information:[/]
  [bold #7ee787]config[/]              Show current configuration
  [bold #7ee787]stats[/]               Show pipeline statistics
  [bold #7ee787]help[/]                Show this help message

[bold #f0883e]Application:[/]
  [bold #7ee787]quit[/] / [bold #7ee787]exit[/]         Exit the application

[bold #f0883e]Keyboard Shortcuts:[/]
  [bold #58a6ff]F1[/]                  Show help
  [bold #58a6ff]F5[/]                  Refresh file tree
  [bold #58a6ff]Ctrl+P[/]              Process all pending files
  [bold #58a6ff]Ctrl+Q[/]              Quit
  [bold #58a6ff]Ctrl+L[/]              Clear viewer

[bold #f0883e]Sidebar:[/]
  Click or navigate to a file, then press [bold #58a6ff]Enter[/] to preview.
  For INPUT files, you can also process them from the viewer.\
"""
        log.write(Text.from_markup(help_text))

        title = self.query_one("#viewer-title", Static)
        title.update("📋 Help")

    def show_error(self, message: str) -> None:
        """Display an error message."""
        self.log_widget.write(Text.from_markup(
            f"\n[bold #f85149]❌ Error:[/] {message}"
        ))

    def show_info(self, message: str) -> None:
        """Display an informational message."""
        self.log_widget.write(Text.from_markup(
            f"\n[bold #58a6ff]ℹ️  {message}[/]"
        ))

    def show_success(self, message: str) -> None:
        """Display a success message."""
        self.log_widget.write(Text.from_markup(
            f"\n[bold #7ee787]✅ {message}[/]"
        ))
