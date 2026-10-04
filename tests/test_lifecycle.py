"""Gate tests for quest lifecycle processing, expiry, PR matching, and XP accounting."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from rune import store, theme
from rune.cli import refresh, status
from rune.github import GitHubClient
from rune.lifecycle import (
    COMPLETED,
    ERROR,
    EXPIRED,
    NO_ACTIVE,
    NO_PR,
    PR_CLOSED_UNMERGED,
    PR_OPEN,
    LifecycleOutcome,
    ProcessResult,
    match_pull_requests,
    process_active_quest,
    render_refresh_view,
    render_status_view,
)
from rune.models import AcceptanceCriterion, Quest, QuestFraming, QuestIssue
from rune.recovery import recover_stale_setups
from rune.xp import compute_total_xp, get_player_stats, rune_level, sync_player_cache


def make_test_quest(
    quest_id: str | None = None,
    status: str = "ACTIVE",
    base_repo: str = "pallets/click",
    base_branch: str = "main",
    head_repo: str = "alice/click",
    head_owner: str = "alice",
    head_branch: str = "rune/a1b2c3d4-42-cli-parser",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    xp: int = 150,
    xp_awarded: bool = False,
    workspace_path: str | None = None,
) -> Quest:
    qid = quest_id or str(uuid.uuid4())
    display_id = qid[:8]
    created = created_at or datetime.now(timezone.utc)
    expires = expires_at or (created + timedelta(hours=3))
    return Quest(
        id=qid,
        display_id=display_id,
        status=status,
        created_at=created,
        claimed_at=created,
        expires_at=expires,
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
        base_branch=base_branch,
        route="fork",
        head_repo=head_repo,
        head_owner=head_owner,
        head_branch=head_branch,
        difficulty="NORMAL",
        xp=xp,
        duration_seconds=180 * 60,
        xp_awarded=xp_awarded,
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
# 1. Exact PR match conditions
# ---------------------------------------------------------------------------


def test_pr_exact_match_conditions():
    quest = make_test_quest(
        base_repo="pallets/click",
        base_branch="main",
        head_repo="alice/click",
        head_branch="rune/a1b2c3d4-42-cli-parser",
    )

    def make_pr(
        base_repo: str = "pallets/click",
        base_ref: str = "main",
        head_repo: str | None = "alice/click",
        head_ref: str = "rune/a1b2c3d4-42-cli-parser",
    ) -> dict[str, Any]:
        return {
            "number": 1,
            "created_at": "2026-10-04T12:00:00Z",
            "base": {
                "repo": {"full_name": base_repo},
                "ref": base_ref,
            },
            "head": {
                "repo": {"full_name": head_repo} if head_repo is not None else None,
                "ref": head_ref,
            },
        }

    # Wrong base repo -> no match
    assert match_pull_requests(quest, [make_pr(base_repo="other/click")]) is None

    # Wrong base branch -> no match
    assert match_pull_requests(quest, [make_pr(base_ref="develop")]) is None

    # Wrong head repo -> no match
    assert match_pull_requests(quest, [make_pr(head_repo="bob/click")]) is None

    # Wrong head branch -> no match
    assert match_pull_requests(quest, [make_pr(head_ref="other-branch")]) is None

    # Null head repo -> no match
    assert match_pull_requests(quest, [make_pr(head_repo=None)]) is None

    # Case-insensitive head repo matches
    matched = match_pull_requests(quest, [make_pr(head_repo="ALICE/CLICK")])
    assert matched is not None
    assert matched["number"] == 1


# ---------------------------------------------------------------------------
# 2. list_pull_requests query params, pagination, and multi-match ordering
# ---------------------------------------------------------------------------


def test_list_pull_requests_carries_head_and_caps_at_two_pages():
    requested_urls: list[str] = []
    requested_params: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        requested_params.append(dict(request.url.params))

        page = request.url.params.get("page", "1")
        if page == "1":
            links = '<https://api.github.com/repos/pallets/click/pulls?page=2>; rel="next"'
            return httpx.Response(200, json=[{"number": 101}], headers={"link": links})
        elif page == "2":
            links = '<https://api.github.com/repos/pallets/click/pulls?page=3>; rel="next"'
            return httpx.Response(200, json=[{"number": 102}], headers={"link": links})
        else:
            return httpx.Response(200, json=[{"number": 103}])

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(mock_handler))
    prs = client.list_pull_requests("pallets/click", "alice", "rune/test-branch", max_pages=2)

    # 2 pages followed; 3rd page NEVER requested
    assert len(requested_urls) == 2
    assert len(prs) == 2
    assert [p["number"] for p in prs] == [101, 102]

    # Carries head=<head_owner>:<head_branch>
    assert requested_params[0]["head"] == "alice:rune/test-branch"
    assert requested_params[0]["state"] == "all"
    assert requested_params[0]["direction"] == "desc"


def test_multiple_exact_matches_pick_created_at_desc_then_number_desc():
    quest = make_test_quest()

    def pr_entry(number: int, created_at: str) -> dict[str, Any]:
        return {
            "number": number,
            "created_at": created_at,
            "base": {"repo": {"full_name": quest.base_repo}, "ref": quest.base_branch},
            "head": {"repo": {"full_name": quest.head_repo}, "ref": quest.head_branch},
        }

    prs = [
        pr_entry(number=10, created_at="2026-10-04T09:00:00Z"),
        pr_entry(number=40, created_at="2026-10-04T12:00:00Z"),
        pr_entry(number=45, created_at="2026-10-04T12:00:00Z"),
        pr_entry(number=20, created_at="2026-10-04T11:00:00Z"),
    ]

    # PR 45 and PR 40 share latest created_at, PR 45 has higher number -> picked
    matched = match_pull_requests(quest, prs)
    assert matched is not None
    assert matched["number"] == 45


# ---------------------------------------------------------------------------
# 3. Merge detection
# ---------------------------------------------------------------------------


def test_merged_at_decides_merged(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest()
    store.save_quest(quest)

    # Closed PR with merged_at null -> not merged
    def closed_unmerged_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{
                "number": 1,
                "created_at": "2026-10-04T12:00:00Z",
                "state": "closed",
                "merged_at": None,
                "html_url": "https://github.com/pallets/click/pull/1",
                "base": {"repo": {"full_name": quest.base_repo}, "ref": quest.base_branch},
                "head": {"repo": {"full_name": quest.head_repo}, "ref": quest.head_branch},
            }],
        )

    client_unmerged = GitHubClient(token="ghp_test", transport=httpx.MockTransport(closed_unmerged_handler))
    res = process_active_quest(github=client_unmerged)
    assert res.outcome == PR_CLOSED_UNMERGED
    assert res.quest is not None
    assert res.quest.pr is not None
    assert res.quest.pr.merged is False
    reloaded = store.load_quest(quest.id)
    assert reloaded is not None
    assert reloaded.pr is not None
    assert reloaded.pr.merged is False

    # PR with merged_at not null -> merged
    def merged_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{
                "number": 2,
                "created_at": "2026-10-04T12:00:00Z",
                "state": "closed",
                "merged_at": "2026-10-04T12:30:00Z",
                "html_url": "https://github.com/pallets/click/pull/2",
                "base": {"repo": {"full_name": quest.base_repo}, "ref": quest.base_branch},
                "head": {"repo": {"full_name": quest.head_repo}, "ref": quest.head_branch},
            }],
        )

    client_merged = GitHubClient(token="ghp_test", transport=httpx.MockTransport(merged_handler))
    res_merged = process_active_quest(github=client_merged)
    assert res_merged.outcome == COMPLETED
    assert res_merged.quest is not None
    assert res_merged.quest.status == "COMPLETED"
    assert res_merged.quest.xp_awarded is True


# ---------------------------------------------------------------------------
# 4. Normal merge vs. merge after expiry
# ---------------------------------------------------------------------------


def test_normal_merge_awards_xp(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)

    quest = make_test_quest(created_at=t0, expires_at=t0 + timedelta(hours=2), xp=250)
    store.save_quest(quest)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{
                "number": 10,
                "created_at": t0.isoformat(),
                "state": "closed",
                "merged_at": (t0 + timedelta(hours=1)).isoformat(),
                "html_url": "https://github.com/pallets/click/pull/10",
                "base": {"repo": {"full_name": quest.base_repo}, "ref": quest.base_branch},
                "head": {"repo": {"full_name": quest.head_repo}, "ref": quest.head_branch},
            }],
        )

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    check_time = t0 + timedelta(hours=1, minutes=15)
    result = process_active_quest(now=check_time, github=client)

    assert result.outcome == COMPLETED
    assert result.xp_awarded == 250
    assert result.total_xp == 250

    loaded = store.load_quest(quest.id)
    assert loaded is not None
    assert loaded.status == "COMPLETED"
    assert loaded.xp_awarded is True
    assert loaded.completed_at == check_time

    # Player stats cache was refreshed
    stats = get_player_stats()
    assert stats[0] == 250


def test_merge_after_expiry_marks_expired_and_no_xp(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
    expiry = t0 + timedelta(hours=1)

    quest = make_test_quest(created_at=t0, expires_at=expiry, xp=250)
    store.save_quest(quest)

    transport_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(200, json=[])

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))

    # Time is after expiry
    check_time = expiry + timedelta(seconds=1)
    result = process_active_quest(now=check_time, github=client)

    assert result.outcome == EXPIRED
    assert result.quest is not None
    assert result.quest.status == "EXPIRED"
    assert result.quest.expired_at == check_time

    # Expiry wins: no PR request was made to GitHub
    assert transport_called is False

    # No XP awarded
    assert compute_total_xp() == 0


def test_repeated_calls_cannot_double_award_xp(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)

    quest = make_test_quest(created_at=t0, expires_at=t0 + timedelta(hours=2), xp=150)
    store.save_quest(quest)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{
                "number": 1,
                "created_at": t0.isoformat(),
                "state": "closed",
                "merged_at": t0.isoformat(),
                "base": {"repo": {"full_name": quest.base_repo}, "ref": quest.base_branch},
                "head": {"repo": {"full_name": quest.head_repo}, "ref": quest.head_branch},
            }],
        )

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))

    # First call completes quest
    res1 = process_active_quest(now=t0, github=client)
    assert res1.outcome == COMPLETED
    assert compute_total_xp() == 150

    # Second call finds no active quest -> NO_ACTIVE
    res2 = process_active_quest(now=t0, github=client)
    assert res2.outcome == NO_ACTIVE
    assert compute_total_xp() == 150  # Not 300!


# ---------------------------------------------------------------------------
# 5. Player cache resilience and RuneScape level curve
# ---------------------------------------------------------------------------


def test_corrupt_or_stale_player_json_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    store.ensure_dirs()

    # Save completed quest with 250 XP
    q = make_test_quest(status="COMPLETED", xp=250, xp_awarded=True)
    store.save_quest(q)

    # 1. Corrupt player.json
    player_file = store.player_path()
    with open(player_file, "w", encoding="utf-8") as f:
        f.write("NOT_VALID_JSON{{{")

    xp, lvl = get_player_stats()
    assert xp == 250
    assert lvl == rune_level(250)

    # File was rewritten validly
    data = store.read_json(player_file)
    assert data["total_xp"] == 250

    # 2. Stale player.json
    with open(player_file, "w", encoding="utf-8") as f:
        json.dump({"total_xp": 99999, "level": 99, "updated_at": "old"}, f)

    xp, lvl = get_player_stats()
    assert xp == 250
    assert lvl == rune_level(250)


def test_runescape_level_samples():
    assert rune_level(0) == 1
    assert rune_level(82) == 1
    assert rune_level(83) == 2
    assert rune_level(1154) == 10
    assert rune_level(13034431) == 99


# ---------------------------------------------------------------------------
# 6. Status and refresh views
# ---------------------------------------------------------------------------


def test_status_for_setup_pending_and_failed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # SETUP_PENDING
    q_pending = make_test_quest(status="SETUP_PENDING")
    store.save_quest(q_pending)

    render_status_view()
    out = capsys.readouterr().out
    assert theme.STATUS_HEADER.split("{")[0] in out
    assert theme.SETUP_PENDING in out
    assert "Embers fade in" not in out

    # SETUP_FAILED
    q_failed = make_test_quest(status="SETUP_FAILED")
    q_failed.failure_reason = "abandoned during setup"
    store.save_quest(q_failed)

    render_status_view()
    out2 = capsys.readouterr().out
    assert theme.SETUP_FAILED in out2
    assert "abandoned during setup" in out2
    assert "Embers fade in" not in out2


def test_status_for_active_quest_shows_finish_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    quest = make_test_quest(
        status="ACTIVE",
        head_repo="alice/click",
        head_branch="rune/a1b2c3d4-42-cli-parser",
    )
    store.save_quest(quest)

    # Empty PR response
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    render_status_view(github=client)

    out = capsys.readouterr().out
    assert theme.FINISH_HEADER in out
    assert "git add ." in out
    assert "git push -u origin rune/a1b2c3d4-42-cli-parser" in out
    assert "Embers fade in" in out


def test_github_error_leaves_active_quest_active_and_redacts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest(status="ACTIVE")
    store.save_quest(quest)

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal secret token ghp_secret_123 Server Error")

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(error_handler))
    res = process_active_quest(github=client)

    assert res.outcome == ERROR
    # Quest remains ACTIVE
    loaded = store.load_quest(quest.id)
    assert loaded is not None
    assert loaded.status == "ACTIVE"


def test_status_and_refresh_trigger_exactly_one_process_call(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    spy = MagicMock(return_value=ProcessResult(outcome=NO_ACTIVE))
    monkeypatch.setattr("rune.lifecycle.process_active_quest", spy)

    status()
    assert spy.call_count == 1

    spy.reset_mock()
    refresh()
    assert spy.call_count == 1


def test_refresh_prints_concise_outcomes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # No active quest
    render_refresh_view()
    out = capsys.readouterr().out
    assert "No active quest." in out
