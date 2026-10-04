"""IDE detection, selection, validation, and launching for RuneCLI."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from rune import store, theme
from rune.models import Quest
from rune.prompts import prompt_reopen_workspace, prompt_select_editor
from rune.ui import get_console


class EditorInfo(NamedTuple):
    """Metadata for a detected editor."""

    command: str
    name: str
    exe: str


SUPPORTED_EDITORS: list[tuple[str, str]] = [
    ("code", "VS Code"),
    ("cursor", "Cursor"),
]


def detect_editors() -> list[EditorInfo]:
    """Detect available supported editors using shutil.which.

    No subprocesses, no filesystem scanning. Returns only found editors.
    """
    found: list[EditorInfo] = []
    for cmd, name in SUPPORTED_EDITORS:
        exe_path = shutil.which(cmd)
        if exe_path:
            found.append(EditorInfo(command=cmd, name=name, exe=exe_path))
    return found


def select_editor(
    editors: list[EditorInfo] | None = None,
    prompt_fn: Callable[[list[EditorInfo]], EditorInfo | None] = prompt_select_editor,
) -> EditorInfo | None:
    """Select an IDE from available editors.

    Exactly one available -> use it and say which.
    Two available -> questionary select (no skip option).
    None available -> return None.
    """
    if editors is None:
        editors = detect_editors()

    if not editors:
        return None

    if len(editors) == 1:
        console = get_console()
        console.print(f"Using {editors[0].name}")
        return editors[0]

    return prompt_fn(editors)


def validate_workspace_path(path: Path | str, quest: Quest) -> Path:
    """Validate that the workspace path matches quest workspace, exists, and resolves inside workspaces_dir()."""
    if not quest.workspace_path:
        raise ValueError("Quest workspace_path is not set")

    ws_path = Path(path).resolve()
    quest_ws = Path(quest.workspace_path).resolve()

    if ws_path != quest_ws:
        raise ValueError(
            f"Specified path '{ws_path}' does not match quest workspace '{quest_ws}'"
        )

    ws_dir = store.workspaces_dir().resolve()
    try:
        rel = ws_path.relative_to(ws_dir)
        if rel == Path("."):
            raise ValueError(f"Workspace path cannot be the root workspaces directory: {ws_path}")
    except ValueError as exc:
        raise ValueError(f"Workspace path '{ws_path}' is outside workspaces directory '{ws_dir}'") from exc

    if not ws_path.exists() or not ws_path.is_dir():
        raise FileNotFoundError(f"Workspace directory does not exist: {ws_path}")

    return ws_path


def open_workspace(
    exe: str,
    quest: Quest,
    workspace_path: Path | str | None = None,
) -> subprocess.Popen:
    """Launch the IDE on the quest workspace folder in a detached process without waiting.

    Popen([exe, workspace_path], stdin/stdout/stderr=DEVNULL, close_fds=True, shell=False),
    detached (start_new_session=True on POSIX; DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP on Windows).
    """
    target_path = workspace_path if workspace_path is not None else quest.workspace_path
    if target_path is None:
        raise ValueError("No workspace path specified and quest.workspace_path is None")

    validated_path = validate_workspace_path(target_path, quest)

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "shell": False,
    }

    if os.name == "nt":
        creationflags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creationflags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True

    return subprocess.Popen([exe, str(validated_path)], **kwargs)


def handle_active_quest(
    quest: Quest,
    editors: list[EditorInfo] | None = None,
    confirm_prompt: Callable[[], bool] = prompt_reopen_workspace,
    select_prompt: Callable[[list[EditorInfo]], EditorInfo | None] = prompt_select_editor,
) -> bool:
    """Handle an existing ACTIVE quest in bare `rune`, offering to reopen its workspace."""
    console = get_console()
    if editors is None:
        editors = detect_editors()

    if not editors:
        console.print(theme.ide_required)
        sys.exit(1)

    if not confirm_prompt():
        return False

    ed = select_editor(editors, prompt_fn=select_prompt)
    if ed is None:
        return False

    from rune.workspace import render_finish_panel

    open_workspace(ed.exe, quest)
    console.print(f"Opening workspace in {ed.name}...")
    console.print("Open the terminal inside your IDE and run the commands shown below.\n")
    console.print(render_finish_panel(quest))
    return True
