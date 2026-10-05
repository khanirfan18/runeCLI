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


def ask_password(message: str) -> str | None:
    """Prompt for a secret without echoing it to the terminal."""
    _check_tty()
    try:
        return questionary.password(
            message,
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


def prompt_choose_quest(quests: Sequence[Any]) -> Any | None:
    """Prompt user to choose a quest to accept, or decline all."""
    from rune.ui import truncate

    choices: list[tuple[str, Any]] = [
        (f"Accept: {truncate(q.title, 60)}", q) for q in quests
    ]
    choices.append(("Decline all", None))
    return ask_select(theme.choose_quest, choices)


def prompt_setup_action() -> str | None:
    """Prompt user after showing setup commands.

    Returns the action character string (e.g. '', 's', 'q') or None on abort.
    """
    _check_tty()
    return ask_text(
        "Press Enter after you've run the setup commands in your terminal (or 's' to skip to finish commands, 'q' to abort)",
        default="",
    )


def prompt_retry_verification() -> bool:
    """Prompt user whether to retry verification after failure."""
    _check_tty()
    res = ask_select("Try again?", [("Yes", True), ("No", False)])
    return bool(res)


def prompt_select_editor(editors: Sequence[Any]) -> Any | None:
    """Prompt user to select an IDE from available choices. No skip option."""
    _check_tty()
    choices = [(getattr(ed, "name", str(ed)), ed) for ed in editors]
    return ask_select("Select IDE", choices)


def prompt_reopen_workspace() -> bool:
    """Prompt user to reopen active quest workspace in IDE."""
    _check_tty()
    res = ask_select("Reopen workspace in IDE?", [("Yes", True), ("No", False)])
    return bool(res)
