"""
CommandInput — bottom command bar for direct query / command entry.

Supports a set of built-in commands and dispatches them as Textual
messages for the main app to handle.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Input, Static
from textual.widget import Widget


class CommandInput(Widget):
    """
    Command bar with a ``❯`` prompt and text input.

    Posts ``CommandInput.CommandSubmitted`` when the user presses Enter.
    """

    class CommandSubmitted(Message):
        """A command was submitted by the user."""

        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def compose(self) -> ComposeResult:
        yield Static("❯", id="command-prompt")
        yield Input(
            placeholder="Type a command (help for reference)...",
            id="command-input",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Forward the submitted text as a CommandSubmitted message."""
        command = event.value.strip()
        if command:
            self.post_message(self.CommandSubmitted(command))
        # Clear the input field
        event.input.value = ""

    def focus_input(self) -> None:
        """Programmatically focus the command input."""
        self.query_one("#command-input", Input).focus()
