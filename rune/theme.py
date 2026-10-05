"""Visual theme and flavor strings for RuneCLI.

All user-facing strings and atmospheric text are centralized here.
Logic modules must never contain flavor text directly.
"""

import os
import sys
from typing import Any, Final

# Rune-inspired palette: treasure gold, wizard teal, forest green, and ember red.
GOLD: Final[str] = "#d4af37"
CYAN: Final[str] = "#56c6c6"
GREEN: Final[str] = "#72b347"
RED: Final[str] = "#d95757"
ASH: Final[str] = "#9099a3"
BONE: Final[str] = "#f2e6c9"
EMBER: Final[str] = "#e07a3f"

# Difficulty names
DIFFICULTY_NAMES: Final[dict[str, str]] = {
    "EASY": "Novice",
    "NORMAL": "Intermediate",
    "HARD": "Experienced",
    "EPIC": "Master",
}

# Frame titles with square brackets
LABEL_QUEST_OFFERED: Final[str] = "[ QUEST OFFERED ]"
quest_offered = LABEL_QUEST_OFFERED

LABEL_OBJECTIVES: Final[str] = "[ OBJECTIVES ]"
objectives = LABEL_OBJECTIVES

LABEL_INSCRIPTIONS: Final[str] = "[ INSCRIPTIONS ]"
inscriptions = LABEL_INSCRIPTIONS

LABEL_UNKNOWNS: Final[str] = "[ UNKNOWN LORE ]"
unknowns = LABEL_UNKNOWNS

SETUP_HEADER: Final[str] = "[ PREPARE YOUR WORKSPACE ]"
setup_header = SETUP_HEADER

FINISH_HEADER: Final[str] = "[ FINISH THE QUEST ]"
finish_header = FINISH_HEADER

QUEST_BOARD: Final[str] = "[ QUEST BOARD ]"
quest_board = QUEST_BOARD

THE_ORACLE: Final[str] = "[ THE ORACLE ]"
the_oracle = THE_ORACLE

QUEST_ACCEPTED: Final[str] = "[ QUEST ACCEPTED ]"
quest_accepted = QUEST_ACCEPTED

ACTIVE_QUEST: Final[str] = "[ ACTIVE QUEST ]"
active_quest = ACTIVE_QUEST

# Messages
SETUP_OK: Final[str] = "The bonfire is lit."
setup_ok = SETUP_OK

TIMER: Final[str] = "Embers fade in {time}"
timer = TIMER

EXPIRED: Final[str] = "The embers have gone cold."
expired = EXPIRED

SETUP_FAILED: Final[str] = "The ritual failed."
setup_failed = SETUP_FAILED

SETUP_PENDING: Final[str] = "The ritual is underway."
setup_pending = SETUP_PENDING

INSUFFICIENT: Final[str] = "The runes are silent."
insufficient = INSUFFICIENT

RATE_LIMIT: Final[str] = "The gods are not listening. Try again at {time}."
rate_limit = RATE_LIMIT

AUTH_FAILED: Final[str] = "The seal is broken. GitHub rejected your token."
auth_failed = AUTH_FAILED

GEMINI_FAILED: Final[str] = "The oracle is unreachable."
gemini_failed = GEMINI_FAILED

ABANDONED: Final[str] = "The ritual is abandoned."
abandoned = ABANDONED

SETUP_ABORTED: Final[str] = "The ritual is abandoned."
setup_aborted = SETUP_ABORTED

COMPLETED: Final[str] = "Congratulations! Quest complete!"
completed = COMPLETED

REWARD: Final[str] = "+{xp} XP"
reward = REWARD

LEVEL_UP: Final[str] = "You've advanced a Rune level! (Level {level})"
level_up = LEVEL_UP

IDE_REQUIRED: Final[str] = (
    "A supported IDE (VS Code or Cursor) is required. Install one, then run rune again."
)
ide_required = IDE_REQUIRED

FORK_BLOCKED: Final[str] = (
    "This repository does not allow forks and you cannot push to it. Pick another quest."
)
fork_blocked = FORK_BLOCKED

VERIFY_FAILED: Final[str] = "The ritual is incomplete: {check}"
verify_failed = VERIFY_FAILED

SIGNED_IN: Final[str] = "Signed in as {login}"
signed_in = SIGNED_IN

ASK_WORK: Final[str] = "What do you want to work on?"
ask_work = ASK_WORK

ASK_GITHUB_TOKEN: Final[str] = "Paste your GitHub API token"
ask_github_token = ASK_GITHUB_TOKEN

ASK_GEMINI_KEY: Final[str] = "Paste your Gemini API key"
ask_gemini_key = ASK_GEMINI_KEY

CREDENTIALS_HEADER: Final[str] = "[ FIRST-RUN ATTUNEMENT ]"
credentials_header = CREDENTIALS_HEADER

CREDENTIALS_SAVED: Final[str] = "Your keys are sealed in ~/.rune and will be reused next time."
credentials_saved = CREDENTIALS_SAVED

CREDENTIALS_CANCELLED: Final[str] = "Credential setup cancelled. Rune remains dormant."
credentials_cancelled = CREDENTIALS_CANCELLED

ASK_SAGE: Final[str] = "Sage (GitHub user or owner, optional)"
ask_sage = ASK_SAGE

ASK_UNASSIGNED: Final[str] = "Only unassigned quests?"
ask_unassigned = ASK_UNASSIGNED

ASK_DIFFICULTY: Final[str] = "Difficulty"
ask_difficulty = ASK_DIFFICULTY

ASK_SELECT_ISSUE: Final[str] = "Select quest"
ask_select_issue = ASK_SELECT_ISSUE

ZERO_RESULTS: Final[str] = (
    "No quests found matching your criteria. Try broader keywords or another Sage."
)
zero_results = ZERO_RESULTS

REPO_ARCHIVED: Final[str] = "This repository is archived. Pick another quest."
repo_archived = REPO_ARCHIVED

ANALYSIS_NOT_WIRED: Final[str] = "analysis not wired yet"
analysis_not_wired = ANALYSIS_NOT_WIRED

MISSING_TOKEN: Final[str] = "GITHUB_TOKEN is not set."
missing_token = MISSING_TOKEN

SETUP_NOT_WIRED: Final[str] = "setup not wired yet"
setup_not_wired = SETUP_NOT_WIRED

ACTIVE_EXISTS: Final[str] = (
    "A quest is already active: {title} ({id}). Finish or abandon it first."
)
active_exists = ACTIVE_EXISTS

CHOOSE_QUEST: Final[str] = "Choose a quest"
choose_quest = CHOOSE_QUEST


# Large, bounded terminal-art banner. Every line stays below 80 columns.
BANNER_ART: Final[str] = (
    r"  ██████╗ ██╗   ██╗███╗   ██╗███████╗" + "\n"
    r"  ██╔══██╗██║   ██║████╗  ██║██╔════╝" + "\n"
    r"  ██████╔╝██║   ██║██╔██╗ ██║█████╗  " + "\n"
    r"  ██╔══██╗██║   ██║██║╚██╗██║██╔══╝  " + "\n"
    r"  ██║  ██║╚██████╔╝██║ ╚████║███████╗" + "\n"
    r"  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝" + "\n"
    r"       A G R I M O N Y   A W A I T S" + "\n"
    r"  Turn a real issue into a quest. | Grounded coding awaits." + "\n"
    + ("=" * 72)
)
PLAIN_BANNER: Final[str] = "RUNE | A grounded coding quest awaits."


class Banner:
    """ASCII-art logo or plain line depending on TTY and NO_COLOR."""

    def __rich_console__(self, console: Any, options: Any) -> Any:
        if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
            yield BANNER_ART
        else:
            yield PLAIN_BANNER

    def __str__(self) -> str:
        if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
            return BANNER_ART
        return PLAIN_BANNER

    def __repr__(self) -> str:
        return str(self)

    def __eq__(self, other: Any) -> bool:
        return str(self) == other or PLAIN_BANNER == other or BANNER_ART == other


BANNER = Banner()
banner = BANNER


class StatusHeader:
    """Format the compact ASCII status table with real RuneScape XP progress."""

    def format(self, level: int = 1, xp: int = 0, **kwargs: Any) -> str:
        from rune.ui import format_status_table

        return format_status_table(level=level, xp=xp)

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:
        return "Rune Level {level} - {xp} XP".split(sep, maxsplit)

    def __str__(self) -> str:
        return "Rune Level {level} - {xp} XP"

    def __repr__(self) -> str:
        return str(self)


STATUS_HEADER = StatusHeader()
status_header = STATUS_HEADER
