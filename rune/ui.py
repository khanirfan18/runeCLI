"""Terminal UI rendering, text sanitization, and rich components for RuneCLI."""

import os
import re
import shutil
import sys
import textwrap
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from rich import box as rich_box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from rune import theme

# Regexes for sanitization
ANSI_ESCAPE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|\x1b\[[0-?]*[ -/]*[@-~]"          # CSI sequences
    r"|\x1b[@-Z\\-_]"                    # 2-character ESC sequences
    r"|\x1b[()#%][0-9a-zA-Z]"            # Other ESC sequences
)

BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff\u2060]")

_TONE_MAP = {
    "gold": theme.GOLD,
    "ash": theme.ASH,
    "ember": theme.EMBER,
}


def terminal_width() -> int:
    """Return bounded terminal width: min(80, columns), minimum 40."""
    cols = shutil.get_terminal_size((80, 24)).columns
    return max(40, min(80, cols))


def sanitize(text: str) -> str:
    """Sanitize external untrusted text.

    Strips ANSI escape sequences (CSI, OSC, and generic ESC),
    converts tabs to 4 spaces, strips Unicode bidi controls and zero-width chars,
    and removes control characters except newline.
    """
    if not text:
        return ""

    # 1. Tabs become 4 spaces
    text = text.replace("\t", "    ")

    # 2. Strip ANSI escape sequences
    text = ANSI_ESCAPE.sub("", text)

    # 3. Strip bidi controls
    text = BIDI_RE.sub("", text)

    # 4. Strip zero-width characters
    text = ZERO_WIDTH_RE.sub("", text)

    # 5. Remove control characters except newline (\n)
    return "".join(ch for ch in text if ch == "\n" or (ord(ch) >= 32 and ord(ch) != 127))


def redact(text: str) -> str:
    """Replace occurrences of active secret tokens (GITHUB_TOKEN, GEMINI_API_KEY) with '***'."""
    if not text:
        return ""
    for env_var in ("GITHUB_TOKEN", "GEMINI_API_KEY"):
        token = os.environ.get(env_var)
        if token:
            text = text.replace(token, "***")
    return text


def truncate(text: str, width: int) -> str:
    """Truncate text to a single line of maximum `width`, ending with '…' when clipped."""
    line = " ".join(text.splitlines()) if text else ""
    if len(line) <= width:
        return line
    if width <= 0:
        return ""
    if width == 1:
        return "…"
    return line[:width - 1] + "…"


def wrap(text: str, width: int) -> list[str]:
    """Wrap text to `width` columns, preserving paragraph breaks and breaking long unbroken tokens."""
    if not text:
        return []
    paragraphs = re.split(r"\n\s*\n", text)
    lines: list[str] = []
    for i, para in enumerate(paragraphs):
        para_clean = " ".join(para.split())
        if para_clean:
            wrapped = textwrap.wrap(
                para_clean,
                width=width,
                break_long_words=True,
                break_on_hyphens=True,
            )
            lines.extend(wrapped)
        if i < len(paragraphs) - 1 and any(p.strip() for p in paragraphs[i + 1:]):
            lines.append("")
    return lines


def get_console() -> Console:
    """Return a rich Console instance configured with Rune constraints."""
    return Console(
        width=terminal_width(),
        markup=False,
        emoji=False,
        highlight=False,
    )


def ext(text: str) -> Text:
    """Convert external text to a rich Text renderable after sanitizing it."""
    return Text(sanitize(text))


def section(title: str) -> Rule:
    """Return a single gold rule line with the section title."""
    return Rule(title, style=theme.GOLD)


def box(body: Any, title: str | None = None, tone: str = "gold") -> Panel:
    """Return a rich Panel with box.SQUARE, terminal width, and border colored by tone."""
    color = _TONE_MAP.get(tone, theme.GOLD)
    return Panel(
        body,
        title=title,
        box=rich_box.SQUARE,
        width=terminal_width(),
        border_style=color,
    )


@contextmanager
def working(message: str) -> Generator[None, None, None]:
    """Context manager displaying a single rich spinner ONLY if stdout is a TTY."""
    if sys.stdout.isatty():
        console = get_console()
        with console.status(message):
            yield
    else:
        yield
