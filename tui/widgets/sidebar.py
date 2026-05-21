"""
Sidebar — directory tree for navigating INPUT/ and PROCESSED/ files.

Provides a two-root tree: one branch for raw documents awaiting
processing, and another for already-extracted text files.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, Tree
from textual.widget import Widget

from services.models import FileInfo, FileStatus


# ── File-type icons ──────────────────────────────────────────
_ICONS: dict[str, str] = {
    ".pdf": "📕",
    ".docx": "📘",
    ".doc": "📘",
    ".xlsx": "📗",
    ".xls": "📗",
    ".txt": "📄",
}


def _icon_for(name: str) -> str:
    """Return an emoji icon based on file extension."""
    ext = Path(name).suffix.lower()
    return _ICONS.get(ext, "📎")


class Sidebar(Widget):
    """
    Two-branch directory tree: INPUT (pending docs) and PROCESSED
    (extracted text files).

    Posts a ``Sidebar.FileSelected`` message when a leaf node is
    clicked.
    """

    class FileSelected(Message):
        """A file was selected in the sidebar tree."""

        def __init__(self, file_info: FileInfo) -> None:
            super().__init__()
            self.file_info = file_info

    def compose(self) -> ComposeResult:
        yield Static("📂 Explorer", id="sidebar-title")
        yield Tree("Smart DB", id="file-tree")

    def on_mount(self) -> None:
        self.refresh_tree()

    def refresh_tree(self) -> None:
        """Rebuild the tree from the current filesystem state."""
        from services.pipeline_service import PipelineService

        tree = self.query_one("#file-tree", Tree)
        tree.clear()
        tree.root.expand()

        # ── INPUT branch ────────────────────────────────────
        input_files = PipelineService.list_input_files()
        input_branch = tree.root.add(
            f"📥 INPUT  ({len(input_files)})", expand=True
        )

        for fi in input_files:
            icon = _icon_for(fi.name)
            status = "✅" if fi.status == FileStatus.PROCESSED else "⏳"
            label = f"{icon} {fi.name}  {status}  ({fi.size_human})"
            node = input_branch.add_leaf(label)
            node.data = fi

        if not input_files:
            input_branch.add_leaf("  (empty — drop files into INPUT/)")

        # ── PROCESSED branch ────────────────────────────────
        processed_files = PipelineService.list_processed_files()
        proc_branch = tree.root.add(
            f"📤 PROCESSED  ({len(processed_files)})", expand=True
        )

        for fi in processed_files:
            label = f"📄 {fi.name}  ({fi.size_human})"
            node = proc_branch.add_leaf(label)
            node.data = fi

        if not processed_files:
            proc_branch.add_leaf("  (empty — process some files first)")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """When a tree leaf is clicked, post a FileSelected message."""
        node = event.node
        if node.data and isinstance(node.data, FileInfo):
            self.post_message(self.FileSelected(node.data))
