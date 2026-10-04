"""Guided local workspace setup, command generation, read-only verification, and timer activation."""

import os
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from rune import store, theme
from rune.models import Quest
from rune.prompts import prompt_retry_verification, prompt_setup_action
from rune.ui import box, ext, get_console, section

ALLOWED_COMMIT_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:#()_/-"
)


def validate_base_branch(branch: str) -> bool:
    """Validate base branch name against injection or option flag patterns."""
    if not branch or branch.startswith("-"):
        return False
    return bool(re.fullmatch(r"^[A-Za-z0-9._/-]+$", branch))


def generate_slug(title: str) -> str:
    """Convert an issue title into a clean branch slug."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = s[:30]
    s = s.strip("-")
    return s if s else "quest"


def validate_branch_name(name: str) -> bool:
    """Check if a branch name is valid using git check-ref-format --branch."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        res = subprocess.run(
            ["git", "check-ref-format", "--branch", name],
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            env=env,
        )
        return res.returncode == 0 and res.stdout.strip() == name
    except Exception:
        return False


def generate_branch_name(display_id: str, issue_number: int, title: str) -> str:
    """Generate a validated branch name in 'rune/<display_id>-<issue_number>-<slug>' format."""
    slug = generate_slug(title)
    name = f"rune/{display_id}-{issue_number}-{slug}"
    if not validate_branch_name(name):
        raise ValueError(f"Invalid branch name '{name}' failed git check-ref-format")
    return name


def setup_head(quest: Quest, login: str) -> None:
    """Determine and persist head_repo, head_owner, and head_branch for a quest."""
    parts = quest.base_repo.split("/", 1)
    base_owner = parts[0]
    base_repo_name = parts[1] if len(parts) > 1 else ""

    if quest.route == "direct":
        quest.head_repo = quest.base_repo
        quest.head_owner = base_owner
    else:  # "fork"
        quest.head_repo = f"{login}/{base_repo_name}"
        quest.head_owner = login

    quest.head_branch = generate_branch_name(
        quest.display_id, quest.issue.number, quest.issue.title
    )


def create_workspace_folder(quest: Quest) -> Path:
    """Create an empty workspace folder under RUNE_HOME/workspaces/<quest.id>/ and record path.

    Refuses if the directory already exists.
    """
    ws_dir = store.workspaces_dir() / quest.id
    if ws_dir.exists():
        raise FileExistsError(f"Workspace directory already exists: {ws_dir}")
    ws_dir.mkdir(parents=True, exist_ok=False)
    quest.workspace_path = str(ws_dir.resolve())
    return ws_dir


def sanitize_commit_message(title: str, number: int) -> str:
    """Sanitize issue title into a commit message with ' (#<number>)' suffix, max 72 chars."""
    suffix = f" (#{number})"
    max_title_len = 72 - len(suffix)

    cleaned = "".join(c if c in ALLOWED_COMMIT_CHARS else " " for c in title)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "quest"

    if len(cleaned) > max_title_len:
        cleaned = cleaned[:max_title_len].rstrip()
    if not cleaned:
        cleaned = "quest"

    msg = f"{cleaned}{suffix}"
    if len(msg) > 72:
        msg = msg[:72]
    return msg


def setup_commands(quest: Quest) -> list[str]:
    """Generate the exact git setup commands for a quest."""
    if not validate_base_branch(quest.base_branch):
        raise ValueError(f"Invalid base_branch: '{quest.base_branch}'")
    if not quest.head_repo or not quest.head_branch:
        raise ValueError("Quest head_repo and head_branch must be set before generating commands.")

    clone_cmd = f"git clone --depth 50 https://github.com/{quest.head_repo}.git ."

    if quest.route == "fork":
        return [
            clone_cmd,
            f"git remote add upstream https://github.com/{quest.base_repo}.git",
            f"git fetch --depth 50 --no-tags upstream {quest.base_branch}",
            f"git switch -c {quest.head_branch} --no-track upstream/{quest.base_branch}",
        ]
    else:
        return [
            clone_cmd,
            f"git switch -c {quest.head_branch}",
        ]


def finish_commands(quest: Quest) -> list[str]:
    """Generate the git finish commands for a quest."""
    if not quest.head_branch:
        raise ValueError("Quest head_branch must be set before generating finish commands.")

    msg = sanitize_commit_message(quest.issue.title, quest.issue.number)
    return [
        "git add .",
        f'git commit -m "{msg}"',
        f"git push -u origin {quest.head_branch}",
    ]


def fork_step(quest: Quest) -> str:
    """Return the manual fork instruction step for fork route quests."""
    return f"Fork {quest.base_repo} on GitHub: https://github.com/{quest.base_repo}/fork (skip if you already have a fork)"


def pr_reminder(quest: Quest) -> str:
    """Return the reminder for opening a pull request on GitHub."""
    return f"Then open a PR on GitHub: base {quest.base_repo}:{quest.base_branch} <- head {quest.head_owner}:{quest.head_branch}"


def parse_remote_repo(url: str) -> str | None:
    """Parse 'owner/repo' from a git remote URL (tolerates https, git@, ssh, .git, trailing slash)."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4].rstrip("/")

    if "://" not in url and ":" in url:
        path = url.split(":", 1)[1]
    else:
        path = urlparse(url).path

    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def verify_workspace(
    workspace_path: Path | str,
    head_repo: str,
    head_branch: str,
) -> tuple[bool, str]:
    """Perform read-only verification of a workspace folder."""
    ws = Path(workspace_path).resolve()
    git_dir = ws / ".git"
    if not git_dir.exists():
        return False, "Not a git repository (.git directory missing)"

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    # 1. Verify remote 'origin'
    try:
        res_remote = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(ws), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout checking git remote origin"
    except Exception as exc:
        return False, f"Failed checking git remote origin: {exc}"

    if res_remote.returncode != 0:
        err = res_remote.stderr.strip() or "remote 'origin' not found"
        return False, f"Remote 'origin' error: {err}"

    origin_url = res_remote.stdout.strip()
    parsed_repo = parse_remote_repo(origin_url)
    if not parsed_repo or parsed_repo.lower() != head_repo.lower():
        return False, f"Remote 'origin' ({origin_url}) does not match expected '{head_repo}'"

    # 2. Verify current HEAD branch
    try:
        res_branch = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(ws), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout checking HEAD branch"
    except Exception as exc:
        return False, f"Failed checking HEAD branch: {exc}"

    if res_branch.returncode != 0:
        err = res_branch.stderr.strip() or "HEAD is detached or invalid"
        return False, f"Branch error: {err}"

    current_branch = res_branch.stdout.strip()
    if current_branch != head_branch:
        return False, f"Active branch '{current_branch}' does not match expected '{head_branch}'"

    return True, ""


def format_time_remaining(seconds: int) -> str:
    """Format duration in seconds into a human-readable string (e.g. '1h', '1h 30m', '45m', '30s')."""
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if m > 0:
            return f"{h}h {m}m"
        return f"{h}h"
    elif seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        if s > 0:
            return f"{m}m {s}s"
        return f"{m}m"
    return f"{seconds}s"


def render_setup_panel(quest: Quest) -> Panel:
    """Render the guided setup panel for the player."""
    renderables: list[Any] = []
    if quest.workspace_path:
        renderables.append(ext(f"Workspace: {quest.workspace_path}"))
        renderables.append(Text(""))

    if quest.route == "fork":
        renderables.append(ext(fork_step(quest)))
        renderables.append(ext("(This assumes the fork keeps its default name)"))
        renderables.append(Text(""))

    renderables.append(section("Run these commands in your workspace terminal:"))
    for cmd in setup_commands(quest):
        renderables.append(ext(f"  {cmd}"))

    return box(Group(*renderables), title=theme.setup_header)


def render_finish_panel(quest: Quest) -> Panel:
    """Render the finish commands panel so the player knows the path to victory."""
    renderables: list[Any] = []
    renderables.append(section("When ready, run these commands:"))
    for cmd in finish_commands(quest):
        renderables.append(ext(f"  {cmd}"))
    renderables.append(Text(""))
    renderables.append(ext(pr_reminder(quest)))

    return box(Group(*renderables), title=theme.finish_header)


def activate_quest(quest: Quest, now: datetime | None = None) -> bool:
    """Activate the quest timer and mark the quest ACTIVE.

    Refuses if another quest has status ACTIVE, in which case the current quest
    is marked SETUP_FAILED with a failure_reason.
    """
    console = get_console()

    # Check for another active quest
    active_quests = store.get_quests_by_status("ACTIVE")
    other_active = [q for q in active_quests if q.id != quest.id]
    if other_active:
        active_q = other_active[0]
        quest.status = "SETUP_FAILED"
        quest.failure_reason = (
            f"another quest is already active: {active_q.spec.title} ({active_q.display_id})"
        )
        store.save_quest(quest)
        console.print(
            theme.active_exists.format(
                title=active_q.spec.title, id=active_q.display_id
            )
        )
        return False

    # Check duration override
    override = os.environ.get("RUNE_DURATION_OVERRIDE_SECONDS")
    if override:
        try:
            val = int(override)
            if val > 0:
                quest.duration_seconds = val
        except ValueError:
            pass

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    quest.status = "ACTIVE"
    quest.claimed_at = now
    quest.expires_at = now + timedelta(seconds=quest.duration_seconds)
    store.save_quest(quest)

    console.print(theme.setup_ok)
    time_str = format_time_remaining(quest.duration_seconds)
    console.print(theme.timer.format(time=time_str))
    console.print(render_finish_panel(quest))
    return True


def run_setup_flow(
    quest: Quest,
    login: str,
    action_prompt: Callable[[], str | None] = prompt_setup_action,
    retry_prompt: Callable[[], bool] = prompt_retry_verification,
    editor: Any = None,
) -> bool:
    """Guide the player through local setup, verification, and timer activation."""
    console = get_console()

    # 1. Determine head and create workspace directory
    setup_head(quest, login)
    create_workspace_folder(quest)
    store.save_quest(quest)

    # 2. Launch IDE once the empty workspace folder exists
    from rune.editor import open_workspace, select_editor

    ed = editor if editor is not None else select_editor()
    if ed is not None:
        exe = ed.exe if hasattr(ed, "exe") else str(ed)
        open_workspace(exe, quest)
        editor_name = getattr(ed, "name", exe)
        console.print(f"Opening workspace in {editor_name}...")
        console.print("Open the terminal inside your IDE and run the commands shown below.\n")

    # Show setup and finish commands
    console.print(render_setup_panel(quest))
    console.print(render_finish_panel(quest))

    # 3. Verification loop
    while True:
        action = action_prompt()
        if action is None or action.strip().lower() == "q":
            console.print(theme.setup_aborted)
            return False

        if action.strip().lower() == "s":
            console.print(render_finish_panel(quest))
            return False

        ok, err = verify_workspace(
            quest.workspace_path or "",
            quest.head_repo or "",
            quest.head_branch or "",
        )
        if ok:
            return activate_quest(quest)

        # Verification failed
        console.print(theme.verify_failed.format(check=err))
        if not retry_prompt():
            console.print(theme.setup_failed)
            return False
