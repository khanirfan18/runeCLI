"""Gate tests for IDE detection, selection, validation, and launching."""

import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from rune import store, theme
from rune.editor import (
    EditorInfo,
    detect_editors,
    handle_active_quest,
    open_workspace,
    select_editor,
    validate_workspace_path,
)
from rune.flow import run_flow
from rune.models import AcceptanceCriterion, Quest, QuestFraming, QuestIssue
from rune.prompts import prompt_select_editor
from rune.workspace import run_setup_flow


def make_test_quest(
    quest_id: str | None = None,
    status: str = "SETUP_PENDING",
    workspace_path: str | None = None,
    base_repo: str = "pallets/click",
) -> Quest:
    qid = quest_id or str(uuid.uuid4())
    display_id = qid[:8]
    return Quest(
        id=qid,
        display_id=display_id,
        status=status,
        created_at=datetime.now(timezone.utc),
        claimed_at=None,
        expires_at=None,
        completed_at=None,
        expired_at=None,
        failure_reason=None,
        issue=QuestIssue(
            number=42,
            title="CLI parser crashes on unknown option",
            url=f"https://github.com/{base_repo}/issues/42",
        ),
        base_repo=base_repo,
        base_repo_url=f"https://github.com/{base_repo}",
        base_branch="main",
        route="fork",
        head_repo="alice/click",
        head_owner="alice",
        head_branch=f"rune/{display_id}-42-cli-parser",
        difficulty="NORMAL",
        xp=150,
        duration_seconds=180 * 60,
        xp_awarded=False,
        workspace_path=workspace_path,
        pr=None,
        spec=QuestFraming(
            title="Fix CLI parser crash",
            summary="Catch unknown arguments gracefully.",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="AC1",
                    statement="Catch parser error and exit cleanly.",
                    evidence_ids=["E0"],
                )
            ],
            evidence_ids=["E0"],
            unknowns=[],
        ),
        snippets=[],
    )


# ---------------------------------------------------------------------------
# 1. Detection: unavailable editors are hidden; single auto-selected; two prompt
# ---------------------------------------------------------------------------


def test_detect_editors_unavailable_hidden(monkeypatch):
    # Both missing
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert detect_editors() == []

    # Only VS Code found -> Cursor hidden
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    editors = detect_editors()
    assert len(editors) == 1
    assert editors[0].command == "code"
    assert editors[0].name == "VS Code"
    assert editors[0].exe == "/usr/bin/code"

    # Only Cursor found -> VS Code hidden
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/opt/cursor/bin/cursor" if cmd == "cursor" else None,
    )
    editors = detect_editors()
    assert len(editors) == 1
    assert editors[0].command == "cursor"
    assert editors[0].name == "Cursor"
    assert editors[0].exe == "/opt/cursor/bin/cursor"

    # Both found
    def which_both(cmd: str) -> str | None:
        if cmd == "code":
            return "/usr/bin/code"
        if cmd == "cursor":
            return "/opt/cursor/bin/cursor"
        return None

    monkeypatch.setattr(shutil, "which", which_both)
    editors = detect_editors()
    assert len(editors) == 2
    assert [e.command for e in editors] == ["code", "cursor"]


def test_select_editor_single_auto_selected():
    vscode = EditorInfo(command="code", name="VS Code", exe="/usr/bin/code")
    prompt_spy = MagicMock()

    # Exactly one available -> auto-selected without prompt
    selected = select_editor(editors=[vscode], prompt_fn=prompt_spy)
    assert selected == vscode
    prompt_spy.assert_not_called()

    # None available -> returns None
    assert select_editor(editors=[]) is None


def test_select_editor_two_available_prompts():
    vscode = EditorInfo(command="code", name="VS Code", exe="/usr/bin/code")
    cursor = EditorInfo(command="cursor", name="Cursor", exe="/usr/bin/cursor")

    prompt_mock = MagicMock(return_value=cursor)
    selected = select_editor(editors=[vscode, cursor], prompt_fn=prompt_mock)

    assert selected == cursor
    prompt_mock.assert_called_once_with([vscode, cursor])


def test_prompt_select_editor_has_no_skip_option(monkeypatch):
    vscode = EditorInfo(command="code", name="VS Code", exe="/usr/bin/code")
    cursor = EditorInfo(command="cursor", name="Cursor", exe="/usr/bin/cursor")

    captured_choices: list[tuple[str, Any]] = []

    def mock_ask_select(message: str, choices: list[tuple[str, Any]]) -> Any:
        nonlocal captured_choices
        captured_choices = choices
        return choices[0][1]

    monkeypatch.setattr("rune.prompts._check_tty", lambda: None)
    monkeypatch.setattr("rune.prompts.ask_select", mock_ask_select)

    res = prompt_select_editor([vscode, cursor])
    assert res == vscode
    labels = [label for label, _ in captured_choices]
    assert labels == ["VS Code", "Cursor"]
    assert "Skip" not in labels
    assert "Decline" not in labels


# ---------------------------------------------------------------------------
# 2. Early check: no editor -> theme.ide_required and non-zero exit BEFORE search
# ---------------------------------------------------------------------------


def test_no_editor_available_exits_before_search(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    client_mock = MagicMock()
    client_mock.get_authenticated_login.return_value = "player"
    client_mock.search_issues = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        run_flow(client=client_mock)

    assert exc_info.value.code != 0
    client_mock.search_issues.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Launch argv is exactly [exe, <workspace>] with shell=False and detached stdio
# ---------------------------------------------------------------------------


def test_launch_argv_exact_and_detached(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    ws_dir = store.workspaces_dir() / "test-quest-123"
    ws_dir.mkdir(parents=True, exist_ok=True)

    quest = make_test_quest(quest_id="test-quest-123", workspace_path=str(ws_dir))

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    exe = "/custom/bin/code"
    proc = open_workspace(exe, quest)
    assert proc == mock_popen.return_value

    assert mock_popen.call_count == 1
    args, kwargs = mock_popen.call_args

    # Exact argv: [exe, workspace_path]
    assert args[0] == [exe, str(ws_dir.resolve())]

    # shell=False
    assert kwargs.get("shell") is False

    # Detached stdio (all DEVNULL)
    assert kwargs.get("stdin") == subprocess.DEVNULL
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL
    assert kwargs.get("close_fds") is True

    # Detached process flag
    if os.name == "nt":
        expected_flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            expected_flags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            expected_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        assert kwargs.get("creationflags") == expected_flags
    else:
        assert kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# 4. Refuse path outside workspaces_dir() or different from quest workspace
# ---------------------------------------------------------------------------


def test_refuse_path_outside_workspaces_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    outside_dir = tmp_path / "outside_workspaces" / "quest-123"
    outside_dir.mkdir(parents=True, exist_ok=True)

    quest = make_test_quest(workspace_path=str(outside_dir))

    with pytest.raises(ValueError, match="outside workspaces directory"):
        validate_workspace_path(outside_dir, quest)

    with pytest.raises(ValueError, match="outside workspaces directory"):
        open_workspace("code", quest, workspace_path=outside_dir)


def test_refuse_path_different_from_quest_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    ws_q1 = store.workspaces_dir() / "quest-1"
    ws_q1.mkdir(parents=True, exist_ok=True)

    ws_q2 = store.workspaces_dir() / "quest-2"
    ws_q2.mkdir(parents=True, exist_ok=True)

    quest = make_test_quest(quest_id="quest-1", workspace_path=str(ws_q1))

    # Passing ws_q2 when quest is quest-1 must be refused
    with pytest.raises(ValueError, match="does not match quest workspace"):
        validate_workspace_path(ws_q2, quest)

    with pytest.raises(ValueError, match="does not match quest workspace"):
        open_workspace("code", quest, workspace_path=ws_q2)


def test_refuse_nonexistent_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    missing_dir = store.workspaces_dir() / "quest-missing"
    # missing_dir is NOT created

    quest = make_test_quest(workspace_path=str(missing_dir))

    with pytest.raises(FileNotFoundError, match="does not exist"):
        validate_workspace_path(missing_dir, quest)


# ---------------------------------------------------------------------------
# 5. P6 setup step 2 calls open_workspace once folder exists
# ---------------------------------------------------------------------------


def test_run_setup_flow_opens_workspace_in_ide(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    quest = make_test_quest()

    real_popen = subprocess.Popen
    mock_popen = MagicMock()

    def smart_popen(cmd, *args, **kwargs):
        if cmd and cmd[0] == "git":
            return real_popen(cmd, *args, **kwargs)
        return mock_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", smart_popen)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else (shutil.which(cmd) if cmd == "git" else None),
    )

    # Run setup flow with abort 'q' to stop after step 2
    ok = run_setup_flow(quest, login="alice", action_prompt=lambda: "q")
    assert ok is False

    # Verify Popen was called with the created workspace folder
    assert mock_popen.call_count == 1
    args, _ = mock_popen.call_args
    assert args[0] == ["/usr/bin/code", quest.workspace_path]


# ---------------------------------------------------------------------------
# 6. Active quest in bare `rune`: offer to reopen workspace
# ---------------------------------------------------------------------------


def test_active_quest_reopen_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    ws_dir = store.workspaces_dir() / "active-quest-456"
    ws_dir.mkdir(parents=True, exist_ok=True)

    active_quest = make_test_quest(
        quest_id="active-quest-456",
        status="ACTIVE",
        workspace_path=str(ws_dir),
    )
    store.save_quest(active_quest)

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/usr/bin/cursor" if cmd == "cursor" else None,
    )

    client_mock = MagicMock()
    client_mock.get_authenticated_login.return_value = "player"

    # User confirms reopening
    run_flow(client=client_mock, reopen_confirm=lambda: True)

    assert mock_popen.call_count == 1
    args, _ = mock_popen.call_args
    assert args[0] == ["/usr/bin/cursor", str(ws_dir.resolve())]
    client_mock.search_issues.assert_not_called()


def test_active_quest_without_ide_shows_ide_required(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    ws_dir = store.workspaces_dir() / "active-quest-789"
    ws_dir.mkdir(parents=True, exist_ok=True)

    active_quest = make_test_quest(
        quest_id="active-quest-789",
        status="ACTIVE",
        workspace_path=str(ws_dir),
    )
    store.save_quest(active_quest)

    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    client_mock = MagicMock()
    client_mock.get_authenticated_login.return_value = "player"

    with pytest.raises(SystemExit) as exc_info:
        run_flow(client=client_mock)

    assert exc_info.value.code != 0
