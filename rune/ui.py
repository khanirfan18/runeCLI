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
    r"|\x1b\[[0-?]*[ -/]*[@-~]"  # CSI sequences
    r"|\x1b[@-Z\\-_]"  # 2-character ESC sequences
    r"|\x1b[()#%][0-9a-zA-Z]"  # Other ESC sequences
)

BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff\u2060]")

_TONE_MAP = {
    "gold": theme.GOLD,
    "cyan": theme.CYAN,
    "green": theme.GREEN,
    "red": theme.RED,
    "ash": theme.ASH,
    "bone": theme.BONE,
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
    return "".join(
        ch for ch in text if ch == "\n" or (ord(ch) >= 32 and ord(ch) != 127)
    )


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
    return line[: width - 1] + "…"


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
        if i < len(paragraphs) - 1 and any(p.strip() for p in paragraphs[i + 1 :]):
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
    """Return a gold section divider with visual breathing room."""
    return Rule(f" {title.strip()} ", characters="-", style=theme.GOLD)


def box(body: Any, title: str | None = None, tone: str = "gold") -> Panel:
    """Return a padded Rune panel with ASCII borders and a colored border."""
    color = _TONE_MAP.get(tone, theme.GOLD)
    formatted_title = None
    if title:
        t = title.strip()
        if t.startswith("[") and t.endswith("]"):
            formatted_title = t
        else:
            formatted_title = f"[ {t} ]"

    if isinstance(body, str):
        # Wrap long lines to fit strictly inside panel borders
        inner_width = terminal_width() - 8
        wrapped_lines: list[str] = []
        for raw_line in body.splitlines():
            if len(raw_line) > inner_width:
                wrapped_lines.extend(
                    textwrap.wrap(
                        raw_line,
                        width=inner_width,
                        break_long_words=True,
                    )
                )
            else:
                wrapped_lines.append(raw_line)
        body = "\n".join(wrapped_lines)

    return Panel(
        body,
        title=formatted_title,
        box=rich_box.ASCII,
        width=terminal_width(),
        padding=(1, 2),
        border_style=color,
    )


@contextmanager
def working(message: str) -> Generator[None, None, None]:
    """Context manager displaying a single rich spinner ONLY if stdout is a TTY and NO_COLOR is unset."""
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        console = get_console()
        with console.status(message):
            yield
    else:
        yield


def compute_xp_progress(level: int, xp: int) -> tuple[int, int, int]:
    """Compute (current_threshold, next_threshold, percentage) for RuneScape level."""
    points = 0
    thresh = [0] * 101
    for lvl in range(1, 100):
        points += int(lvl + 300 * (2 ** (lvl / 7.0)))
        thresh[lvl + 1] = int(points / 4)
    t_cur = thresh[min(99, max(1, level))]
    t_next = thresh[min(99, max(1, level + 1))]
    if level >= 99:
        pct = 100
    else:
        diff = max(1, t_next - t_cur)
        pct = int(((xp - t_cur) / diff) * 100)
    pct = max(0, min(100, pct))
    return t_cur, t_next, pct


def make_xp_bar(pct: int, bar_len: int = 16) -> str:
    """Format an ASCII progress bar from real percentage: [====>     ] 45%."""
    filled = int((pct / 100) * bar_len)
    if filled >= bar_len:
        return f"[{'=' * bar_len}] 100%"
    arrow = ">"
    spaces = bar_len - filled - 1
    return f"[{'=' * filled}{arrow}{' ' * spaces}] {pct:>2}%"


def format_status_table(level: int = 1, xp: int = 0) -> str:
    """Render a compact ASCII table showing player level, XP progress, and active quest info."""
    t_cur, t_next, pct = compute_xp_progress(level, xp)
    bar = make_xp_bar(pct, bar_len=16)

    # Inspect store for quest info without crashing
    quest_title = "None"
    repo = "-"
    state = "IDLE"
    time_left = "-"

    try:
        from datetime import datetime, timezone

        from rune import store
        from rune.workspace import format_time_remaining

        now = datetime.now(timezone.utc)
        active_quests = store.get_quests_by_status("ACTIVE")
        if active_quests:
            q = active_quests[0]
            quest_title = q.spec.title if hasattr(q, "spec") and q.spec else "Quest"
            repo = q.base_repo
            state = q.status
            if q.expires_at:
                tl = max(0, int((q.expires_at - now).total_seconds()))
                time_left = format_time_remaining(tl)
        else:
            all_q = store.list_quests()
            if all_q:
                all_q.sort(key=lambda x: x.created_at, reverse=True)
                q = all_q[0]
                quest_title = q.spec.title if hasattr(q, "spec") and q.spec else "Quest"
                repo = q.base_repo
                state = q.status
    except Exception:
        pass

    width = min(terminal_width(), 78)
    inner = width - 4

    def row(content: str) -> str:
        c = content[:inner] if len(content) > inner else content
        return f"|  {c:<{inner - 2}}  |"

    border = "+" + "-" * (width - 2) + "+"
    lines = [
        border,
        row("RUNE STATUS"),
        row(f"Rune Level {level:<3} | XP {xp:<7} | Next {t_next:<7}"),
        row(f"Progress  {bar}"),
        border,
        row(f"QUEST     {quest_title}"),
        row(f"REPOSITORY {repo}"),
    ]
    if state == "ACTIVE":
        lines.append(row(f"STATE     {state:<15} | TIME LEFT {time_left}"))
    else:
        lines.append(row(f"STATE     {state}"))
    lines.append(border)
    return "\n".join(lines)
