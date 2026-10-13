"""Tests for friendly error handling and secret redaction across RuneCLI."""

import io
import os
import sys
from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner

from rune.cli import app
from rune.difficulty import Difficulty
from rune.gemma import GemmaError
from rune.github import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from rune.models import AcceptanceCriterion, GemmaOutput, IssueRef, QuestFraming, RepoMeta
from rune.store import StoreError


@pytest.fixture
def sample_issue():
    return IssueRef(
        number=42,
        title="Fix CLI argument parsing crash",
        body="Passing unexpected flags causes unhandled ValueError in cli.py.",
        url="https://github.com/owner/repo/issues/42",
        base_repo="owner/repo",
        state="open",
    )


@pytest.fixture
def sample_repo_meta():
    return RepoMeta(
        base_repo="owner/repo",
        base_repo_url="https://github.com/owner/repo",
        default_branch="main",
        allow_forking=True,
        archived=False,
        push=True,
        route="direct",
    )


@pytest.fixture
def sample_gemma_output():
    return GemmaOutput(
        status="OK",
        quests=[
            QuestFraming(
                title="Fix Argument Parsing",
                summary="Handle invalid command line arguments gracefully.",
                acceptance_criteria=[
                    AcceptanceCriterion(
                        id="AC1",
                        statement="Catch ValueError when parsing unknown flags.",
                        evidence_ids=["E0"],
                    )
                ],
                evidence_ids=["E0"],
                unknowns=[],
            )
        ],
        reason=None,
    )


def invoke_flow_with_step_error(
    error_step: str,
    exc: Exception,
    sample_issue: IssueRef,
    sample_repo_meta: RepoMeta,
    sample_gemma_output: GemmaOutput,
    env: dict[str, str] | None = None,
):
    """Helper to run CLI flow with a specified step raising an exception."""
    runner = CliRunner()

    mock_sys = MagicMock()
    mock_sys.stdin.isatty.return_value = True
    mock_sys.exit = sys.exit

    mock_client = MagicMock()
    if error_step == "auth":
        mock_client.get_authenticated_login.side_effect = exc
    else:
        mock_client.get_authenticated_login.return_value = "player"

    if error_step == "search":
        mock_client.search_issues.side_effect = exc
    else:
        mock_client.search_issues.return_value = [sample_issue]

    if error_step == "repo":
        mock_client.get_repo.side_effect = exc
    else:
        mock_client.get_repo.return_value = sample_repo_meta

    gemma_side_effect = exc if error_step == "gemma" else sample_gemma_output
    store_side_effect = exc if error_step == "store" else None

    patches = [
        patch("rune.flow.sys", mock_sys),
        patch("rune.flow.ensure_credentials", return_value=True),
        patch("rune.flow.GitHubClient", return_value=mock_client),
        patch("rune.flow.detect_editors", return_value=["cursor"]),
        patch("rune.flow.process_active_quest", return_value=MagicMock(quest=None)),
        patch("rune.flow.ask_text", side_effect=["fix bug", ""]),
        patch("rune.flow.ask_select", side_effect=[True, Difficulty.NORMAL, sample_issue]),
        patch("rune.flow.select_single_issue", return_value=sample_issue),
        patch("rune.flow.run_analysis", return_value=[]),
    ]

    if error_step == "gemma":
        patches.append(patch("rune.flow.run_gemini", side_effect=gemma_side_effect))
    else:
        patches.append(patch("rune.flow.run_gemini", return_value=sample_gemma_output))

    if error_step == "store":
        patches.append(patch("rune.flow.choose_quest_option", return_value=sample_gemma_output.quests[0]))
        patches.append(patch("rune.flow.accept_quest", side_effect=store_side_effect))
    else:
        patches.append(patch("rune.flow.choose_quest_option", return_value=sample_gemma_output.quests[0]))
        patches.append(patch("rune.flow.accept_quest", return_value=MagicMock()))
        patches.append(patch("rune.flow.run_setup_flow", return_value=None))

    if error_step == "keyboard_interrupt":
        mock_client.get_authenticated_login.side_effect = KeyboardInterrupt()

    if error_step == "unexpected":
        mock_client.get_authenticated_login.side_effect = exc

    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(app, [], env=env)


# ---------------------------------------------------------------------------
# 1. Reproduce: Known errors raised at their respective steps in run_flow
# ---------------------------------------------------------------------------


def test_gemma_step_raising_gemma_error(sample_issue, sample_repo_meta, sample_gemma_output):
    """When Gemma step raises GemmaError, assert no traceback, friendly message, exit code 1."""
    err = GemmaError("The oracle is unreachable. All generation attempts failed: 500 INTERNAL")
    res = invoke_flow_with_step_error("gemma", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "The oracle is unreachable." in res.output
    assert "Google's API had a problem. This is usually temporary, so please run rune again in a few minutes." in res.output


def test_github_auth_step_raising_auth_error(sample_issue, sample_repo_meta, sample_gemma_output):
    """When GitHub auth raises GitHubAuthError, assert no traceback, friendly message, exit code 1."""
    err = GitHubAuthError("The seal is broken. GitHub rejected your token.")
    res = invoke_flow_with_step_error("auth", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "The seal is broken. GitHub rejected your token." in res.output


def test_github_search_step_raising_ratelimit_error(sample_issue, sample_repo_meta, sample_gemma_output):
    """When GitHub search raises GitHubRateLimitError, assert no traceback, friendly message, exit code 1."""
    err = GitHubRateLimitError("The gods are not listening. Try again at 12:00.")
    res = invoke_flow_with_step_error("search", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "The gods are not listening. Try again at 12:00." in res.output


def test_github_repo_step_raising_notfound_error(sample_issue, sample_repo_meta, sample_gemma_output):
    """When GitHub repo check raises GitHubNotFoundError, assert no traceback, friendly message, exit code 1."""
    err = GitHubNotFoundError("Resource not found (404): https://api.github.com/repos/owner/repo")
    res = invoke_flow_with_step_error("repo", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "Resource not found (404): https://api.github.com/repos/owner/repo" in res.output


def test_store_step_raising_store_error(sample_issue, sample_repo_meta, sample_gemma_output):
    """When store step raises StoreError, assert no traceback, friendly message, exit code 1."""
    err = StoreError("Failed to persist quest data.")
    res = invoke_flow_with_step_error("store", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "Failed to persist quest data." in res.output


def test_keyboard_interrupt_handled_gracefully(sample_issue, sample_repo_meta, sample_gemma_output):
    """Ctrl-C prints 'Quest board closed.' and exits 130 with no traceback."""
    res = invoke_flow_with_step_error("keyboard_interrupt", KeyboardInterrupt(), sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 130
    assert "Traceback" not in res.output
    assert "Quest board closed." in res.output


# ---------------------------------------------------------------------------
# 2. Status and Refresh views handle known errors
# ---------------------------------------------------------------------------


def test_status_command_handles_known_error():
    runner = CliRunner()
    with patch("rune.cli.render_status_view", side_effect=StoreError("Store corrupted")):
        res = runner.invoke(app, ["status"])
    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "Store corrupted" in res.output


def test_refresh_command_handles_known_error():
    runner = CliRunner()
    with patch("rune.cli.render_refresh_view", side_effect=GitHubAuthError("Token expired")):
        res = runner.invoke(app, ["refresh"])
    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "Token expired" in res.output


# ---------------------------------------------------------------------------
# 3. Truly unexpected errors and RUNE_DEBUG switch
# ---------------------------------------------------------------------------


def test_unexpected_error_prints_issue_link_and_exits_1(sample_issue, sample_repo_meta, sample_gemma_output):
    """Unexpected errors print GitHub issues link + exception type and message, no traceback."""
    err = ValueError("unexpected math issue")
    res = invoke_flow_with_step_error("unexpected", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert res.exit_code == 1
    assert "Traceback" not in res.output
    assert "Something unexpected went wrong. Please open an issue at https://github.com/khanirfan18/runeCLI/issues" in res.output
    assert "ValueError: unexpected math issue" in res.output


def test_rune_debug_reraises_unexpected_error(sample_issue, sample_repo_meta, sample_gemma_output, monkeypatch):
    """RUNE_DEBUG=1 re-raises unexpected error so traceback is shown."""
    err = ValueError("unexpected math issue")
    monkeypatch.setenv("RUNE_DEBUG", "1")
    res = invoke_flow_with_step_error(
        "unexpected",
        err,
        sample_issue,
        sample_repo_meta,
        sample_gemma_output,
        env={"RUNE_DEBUG": "1"},
    )

    assert res.exit_code != 0
    assert res.exception is not None
    assert isinstance(res.exception, ValueError)


# ---------------------------------------------------------------------------
# 4. Never leak secrets in tracebacks or output
# ---------------------------------------------------------------------------


def test_secrets_never_leak_in_exception_output(sample_issue, sample_repo_meta, sample_gemma_output, monkeypatch):
    """Assert GEMINI_API_KEY and GITHUB_TOKEN values never appear in output."""
    fake_gemini = "AIzaSy_SECRET_GEMINI_KEY_XYZ123"
    fake_github = "ghp_SECRET_GITHUB_TOKEN_ABC789"
    monkeypatch.setenv("GEMINI_API_KEY", fake_gemini)
    monkeypatch.setenv("GITHUB_TOKEN", fake_github)

    err = RuntimeError(f"Connection failed using key {fake_gemini} and token {fake_github}")
    res = invoke_flow_with_step_error("unexpected", err, sample_issue, sample_repo_meta, sample_gemma_output)

    assert fake_gemini not in res.output
    assert fake_github not in res.output
    assert "***" in res.output
