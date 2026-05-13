"""Modal widget for entering command parameters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class CommandInputModal(ModalScreen[str | None]):
    """A simple single-field modal that asks for one text value."""

    DEFAULT_CSS = """
    CommandInputModal {
        align: center middle;
    }
    CommandInputModal > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 50;
        height: auto;
    }
    CommandInputModal Label {
        margin-bottom: 1;
    }
    CommandInputModal Input {
        margin-bottom: 1;
    }
    CommandInputModal Horizontal {
        height: auto;
        align-horizontal: right;
    }
    CommandInputModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._prompt)
            yield Input(placeholder=self._placeholder, id="value_input")
            with Horizontal():
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            value = self.query_one("#value_input", Input).value.strip()
            self.dismiss(value if value else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        value = self.query_one("#value_input", Input).value.strip()
        self.dismiss(value if value else None)
