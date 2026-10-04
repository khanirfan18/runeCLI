"""Interactive terminal prompts wrapping questionary."""

import sys
from collections.abc import Sequence
from typing import Any

import questionary
from questionary import Choice, Style

from rune import theme

PROMPT_STYLE = Style([
    ("qmark", f"fg:{theme.GOLD} bold"),
    ("question", "bold"),
    ("answer", f"fg:{theme.GOLD} bold"),
    ("pointer", f"fg:{theme.GOLD} bold"),
    ("highlighted", f"fg:{theme.GOLD} bold"),
    ("selected", f"fg:{theme.GOLD}"),
])


def _check_tty() -> None:
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive prompt requires a TTY stdin.")


def ask_text(message: str, default: str = "") -> str | None:
    """Prompt for text input. Return None on Ctrl-C / abort."""
    _check_tty()
    try:
        return questionary.text(
            message,
            default=default,
            qmark="ᚱ",
            style=PROMPT_STYLE,
        ).ask()
    except KeyboardInterrupt:
        return None


def ask_select(message: str, choices: Sequence[tuple[str, Any]]) -> Any | None:
    """Prompt to select from (label, value) choices. Return None on Ctrl-C / abort."""
    _check_tty()
    q_choices = [Choice(title=label, value=val) for label, val in choices]
    try:
        return questionary.select(
            message,
            choices=q_choices,
            qmark="ᚱ",
            style=PROMPT_STYLE,
        ).ask()
    except KeyboardInterrupt:
        return None
