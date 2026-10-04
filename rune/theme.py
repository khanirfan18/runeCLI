"""Visual theme and flavor strings for RuneCLI.

All user-facing strings and atmospheric text are centralized here.
Logic modules must never contain flavor text directly.
"""

from typing import Final

# Palette
GOLD: Final[str] = "#c9a227"
BONE: Final[str] = "#e8dcc0"
ASH: Final[str] = "#8a8a8a"
EMBER: Final[str] = "#b3261e"

# Difficulty names
DIFFICULTY_NAMES: Final[dict[str, str]] = {
    "EASY": "Novice",
    "NORMAL": "Intermediate",
    "HARD": "Experienced",
    "EPIC": "Master",
}

# Labels
LABEL_QUEST_OFFERED: Final[str] = "Quest offered"
quest_offered = LABEL_QUEST_OFFERED

LABEL_OBJECTIVES: Final[str] = "Objectives"
objectives = LABEL_OBJECTIVES

LABEL_INSCRIPTIONS: Final[str] = "Inscriptions"
inscriptions = LABEL_INSCRIPTIONS

LABEL_UNKNOWNS: Final[str] = "Unknown lore"
unknowns = LABEL_UNKNOWNS

# Messages
BANNER: Final[str] = "ᚱ RUNE  Turn a real issue into a quest."
banner = BANNER

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

COMPLETED: Final[str] = "Congratulations! Quest complete!"
completed = COMPLETED

REWARD: Final[str] = "+{xp} XP"
reward = REWARD

LEVEL_UP: Final[str] = "You've advanced a Rune level! (Level {level})"
level_up = LEVEL_UP

STATUS_HEADER: Final[str] = "Rune Level {level} · {xp} XP"
status_header = STATUS_HEADER

IDE_REQUIRED: Final[str] = "A supported IDE (VS Code or Cursor) is required. Install one, then run rune again."
ide_required = IDE_REQUIRED

FORK_BLOCKED: Final[str] = "This repository does not allow forks and you cannot push to it. Pick another quest."
fork_blocked = FORK_BLOCKED

SETUP_HEADER: Final[str] = "Prepare your workspace"
setup_header = SETUP_HEADER

FINISH_HEADER: Final[str] = "Finish the quest"
finish_header = FINISH_HEADER

VERIFY_FAILED: Final[str] = "The ritual is incomplete: {check}"
verify_failed = VERIFY_FAILED

# Quest Board labels
QUEST_BOARD: Final[str] = "Quest Board"
quest_board = QUEST_BOARD

SIGNED_IN: Final[str] = "Signed in as {login}"
signed_in = SIGNED_IN

ASK_WORK: Final[str] = "What do you want to work on?"
ask_work = ASK_WORK

ASK_SAGE: Final[str] = "Sage (GitHub user or owner, optional)"
ask_sage = ASK_SAGE

ASK_UNASSIGNED: Final[str] = "Only unassigned quests?"
ask_unassigned = ASK_UNASSIGNED

ASK_DIFFICULTY: Final[str] = "Difficulty"
ask_difficulty = ASK_DIFFICULTY

ASK_SELECT_ISSUE: Final[str] = "Select quest"
ask_select_issue = ASK_SELECT_ISSUE

ZERO_RESULTS: Final[str] = "No quests found matching your criteria. Try broader keywords or another Sage."
zero_results = ZERO_RESULTS

REPO_ARCHIVED: Final[str] = "This repository is archived. Pick another quest."
repo_archived = REPO_ARCHIVED

ANALYSIS_NOT_WIRED: Final[str] = "analysis not wired yet"
analysis_not_wired = ANALYSIS_NOT_WIRED

MISSING_TOKEN: Final[str] = "GITHUB_TOKEN is not set."
missing_token = MISSING_TOKEN

