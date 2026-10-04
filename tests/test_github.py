"""Gate tests for GitHub client, quest board search, repo/route check, and E0."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rune import flow, theme
from rune.difficulty import DIFFICULTY_LOOKUP, Difficulty, get_difficulty
from rune.github import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    build_search_query,
    extract_keywords,
    format_issue_label,
    parse_issue_item,
    parse_reset_time,
    select_issue,
    select_single_issue,
    validate_sage,
)
from rune.models import E0, IssueRef, RepoMeta


# ---------------------------------------------------------------------------
# Difficulty tests
# ---------------------------------------------------------------------------


def test_difficulty_lookup_values():
    assert DIFFICULTY_LOOKUP[Difficulty.EASY].minutes == 60
    assert DIFFICULTY_LOOKUP[Difficulty.EASY].xp == 100

    assert DIFFICULTY_LOOKUP[Difficulty.NORMAL].minutes == 180
    assert DIFFICULTY_LOOKUP[Difficulty.NORMAL].xp == 150

    assert DIFFICULTY_LOOKUP[Difficulty.HARD].minutes == 360
    assert DIFFICULTY_LOOKUP[Difficulty.HARD].xp == 250

    assert DIFFICULTY_LOOKUP[Difficulty.EPIC].minutes == 540
    assert DIFFICULTY_LOOKUP[Difficulty.EPIC].xp == 400

    # String lookup
    assert get_difficulty("easy").minutes == 60
    assert get_difficulty("NORMAL").xp == 150
    with pytest.raises(KeyError):
        get_difficulty("UNKNOWN")


# ---------------------------------------------------------------------------
# q composition tests
# ---------------------------------------------------------------------------


def test_q_composition_base_qualifiers():
    q = build_search_query(["cli", "tool"], unassigned=False, sage=None)
    assert q.startswith("is:issue is:open is:public archived:false in:title,body")
    assert "cli tool" in q


def test_q_composition_unassigned_only_when_yes():
    q_yes = build_search_query(["refactor"], unassigned=True, sage=None)
    assert "no:assignee" in q_yes

    q_no = build_search_query(["refactor"], unassigned=False, sage=None)
    assert "no:assignee" not in q_no


def test_q_composition_sage_only_when_given():
    q_with_sage = build_search_query(["docs"], unassigned=False, sage="pallets")
    assert "user:pallets" in q_with_sage

    q_blank_sage = build_search_query(["docs"], unassigned=False, sage="")
    assert "user:" not in q_blank_sage

    q_whitespace_sage = build_search_query(["docs"], unassigned=False, sage="   ")
    assert "user:" not in q_whitespace_sage

    q_none_sage = build_search_query(["docs"], unassigned=False, sage=None)
    assert "user:" not in q_none_sage


def test_q_composition_rune_search_user_default(monkeypatch):
    monkeypatch.setenv("RUNE_SEARCH_USER", "defaultowner")
    default_val = os.environ.get("RUNE_SEARCH_USER", "")
    assert default_val == "defaultowner"

    # Blank answer overrides default
    user_choice = ""
    sage = user_choice if user_choice else None
    q = build_search_query(["test"], sage=sage)
    assert "user:" not in q


def test_q_composition_hostile_keywords_sanitized():
    # Keywords with colon, quotes, or search qualifiers must not inject qualifiers
    hostile = ['is:closed', 'label:"security"', "user:attacker", "validword"]
    q = build_search_query(hostile, unassigned=True)
    # The colon and quotes must be stripped, leaving alphanumeric words >= 3
    assert "is:closed" not in q
    assert 'label:"security"' not in q
    assert "user:attacker" not in q
    # Valid tokens are preserved
    assert "validword" in q


def test_q_composition_capped_at_256():
    long_keywords = [f"word{i}" * 5 for i in range(20)]
    q = build_search_query(long_keywords, unassigned=True, sage="verylongusername1234567890")
    assert len(q) <= 256


def test_extract_keywords_and_validate_sage():
    # Length >= 3, alphanumeric, max 8
    raw = "to be or not to be 12345 quest refactoring auth bug fix ui display extra"
    kws = extract_keywords(raw)
    assert len(kws) <= 8
    assert "to" not in kws
    assert "be" not in kws
    assert "or" not in kws
    assert "12345" in kws
    assert "quest" in kws

    # Sage validation
    assert validate_sage("pallets") is True
    assert validate_sage("octo-cat") is True
    assert validate_sage("-invalid") is False
    assert validate_sage("") is False
    assert validate_sage("user@invalid") is False
    assert validate_sage("a" * 39) is True
    assert validate_sage("a" * 40) is False


# ---------------------------------------------------------------------------
# Results parsing tests
# ---------------------------------------------------------------------------


def test_results_base_repo_parsed_from_repository_url():
    raw_item = {
        "number": 42,
        "title": "Fix parser edge case",
        "body": "Some description",
        "html_url": "https://github.com/pallets/click/issues/42",
        "repository_url": "https://api.github.com/repos/pallets/click",
        "assignees": [],
    }
    issue = parse_issue_item(raw_item, unassigned=True)
    assert issue is not None
    assert issue.base_repo == "pallets/click"
    assert issue.number == 42
    assert issue.url == "https://github.com/pallets/click/issues/42"


def test_results_skips_missing_fields_and_pull_requests():
    valid = {
        "number": 1,
        "title": "Valid issue",
        "body": None,
        "html_url": "https://github.com/owner/repo/issues/1",
        "repository_url": "https://api.github.com/repos/owner/repo",
    }
    # Missing body becomes ""
    res = parse_issue_item(valid)
    assert res is not None
    assert res.body == ""

    # Pull request item skipped
    pr_item = dict(valid, pull_request={"url": "https://api.github.com/..."})
    assert parse_issue_item(pr_item) is None

    # Missing number
    assert parse_issue_item(dict(valid, number=None)) is None

    # Missing title
    no_title = dict(valid)
    del no_title["title"]
    assert parse_issue_item(no_title) is None

    # Missing html_url
    assert parse_issue_item(dict(valid, html_url=None)) is None

    # Missing repository_url
    assert parse_issue_item(dict(valid, repository_url=None)) is None


def test_results_drops_assigned_when_unassigned_yes():
    item_with_assignees = {
        "number": 10,
        "title": "Assigned issue",
        "body": "Assigned to alice",
        "html_url": "https://github.com/owner/repo/issues/10",
        "repository_url": "https://api.github.com/repos/owner/repo",
        "assignees": [{"login": "alice"}],
    }
    # Dropped when unassigned=True
    assert parse_issue_item(item_with_assignees, unassigned=True) is None

    # Preserved when unassigned=False
    parsed = parse_issue_item(item_with_assignees, unassigned=False)
    assert parsed is not None
    assert parsed.assignee_logins == ["alice"]

    # Single assignee field fallback
    item_single_assignee = {
        "number": 11,
        "title": "Assigned single",
        "body": "",
        "html_url": "https://github.com/owner/repo/issues/11",
        "repository_url": "https://api.github.com/repos/owner/repo",
        "assignees": [],
        "assignee": {"login": "bob"},
    }
    assert parse_issue_item(item_single_assignee, unassigned=True) is None
    parsed_single = parse_issue_item(item_single_assignee, unassigned=False)
    assert parsed_single is not None
    assert parsed_single.assignee_logins == ["bob"]


def test_results_zero_results_handled():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 0, "items": []})

    client = GitHubClient(token="ghp_test_token", transport=httpx.MockTransport(handler))
    results = client.search_issues("query", unassigned=True)
    assert results == []


# ---------------------------------------------------------------------------
# Search reliability: no sleep, polling, or repeated requests
# ---------------------------------------------------------------------------


def test_no_sleep_or_polling_on_search(monkeypatch):
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"total_count": 0, "items": []})

    sleep_mock = MagicMock()
    monkeypatch.setattr(time, "sleep", sleep_mock)

    client = GitHubClient(token="ghp_test_token", transport=httpx.MockTransport(handler))
    results = client.search_issues("test search query", unassigned=True)

    assert results == []
    # Exactly one request made
    assert request_count == 1
    # Never slept
    sleep_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling and retry tests
# ---------------------------------------------------------------------------


def test_auth_error_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = GitHubClient(token="bad_token", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubAuthError) as exc_info:
        client.get_authenticated_login()
    assert theme.AUTH_FAILED in str(exc_info.value)


def test_rate_limit_403_and_429_with_parsed_reset():
    # 403 with X-RateLimit-Reset
    def handler_403(request: httpx.Request) -> httpx.Response:
        headers = {"x-ratelimit-reset": "1700000000"}
        return httpx.Response(403, headers=headers, json={"message": "API rate limit exceeded"})

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler_403))
    with pytest.raises(GitHubRateLimitError) as exc_403:
        client.get("/user")
    assert exc_403.value.reset_time is not None
    assert exc_403.value.reset_time == 1700000000
    assert isinstance(exc_403.value.reset_time, datetime)

    # 429 with Retry-After
    def handler_429(request: httpx.Request) -> httpx.Response:
        headers = {"retry-after": "60"}
        return httpx.Response(429, headers=headers, json={"message": "Too many requests"})

    client_429 = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler_429))
    with pytest.raises(GitHubRateLimitError) as exc_429:
        client_429.get("/user")
    assert exc_429.value.reset_time is not None
    assert isinstance(exc_429.value.reset_time, datetime)

    # 403 with unknown reset
    def handler_no_reset(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "rate limit"})

    client_no_reset = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler_no_reset))
    with pytest.raises(GitHubRateLimitError) as exc_no_reset:
        client_no_reset.get("/user")
    assert exc_no_reset.value.reset_time is None


def test_404_raises_github_not_found_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubNotFoundError):
        client.get("/repos/unknown/unknown")


def test_transient_transport_error_retries_at_most_once():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectTimeout("Connection timed out")
        return httpx.Response(200, json={"login": "octocat"})

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    login = client.get_authenticated_login()
    assert login == "octocat"
    assert call_count == 2


def test_transient_transport_error_fails_after_second_attempt():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("Read timed out")

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError, match="Network error after retry"):
        client.get_authenticated_login()
    assert call_count == 2


def test_http_error_statuses_never_retried():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, json={"message": "Internal Server Error"})

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError):
        client.get_authenticated_login()
    # Exactly one request made, NO retry
    assert call_count == 1


# ---------------------------------------------------------------------------
# Missing GITHUB_TOKEN handling
# ---------------------------------------------------------------------------


def test_missing_github_token_exits_one(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        GitHubClient(token=None)
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Repo checks, permissions, and routing
# ---------------------------------------------------------------------------


def test_route_direct_when_push_true_and_fork_otherwise():
    # Direct route when push permission is True
    def direct_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/myorg/myrepo",
                "default_branch": "main",
                "archived": False,
                "allow_forking": True,
                "permissions": {"push": True},
            },
        )

    client_direct = GitHubClient(token="ghp_test", transport=httpx.MockTransport(direct_handler))
    repo_direct = client_direct.get_repo("myorg/myrepo")
    assert repo_direct.push is True
    assert repo_direct.route == "direct"

    # Fork route when push permission is False
    def fork_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/otherorg/otherrepo",
                "default_branch": "main",
                "archived": False,
                "allow_forking": True,
                "permissions": {"push": False},
            },
        )

    client_fork = GitHubClient(token="ghp_test", transport=httpx.MockTransport(fork_handler))
    repo_fork = client_fork.get_repo("otherorg/otherrepo")
    assert repo_fork.push is False
    assert repo_fork.route == "fork"

    # Fork route when permissions dict is missing
    def missing_perms_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/no-perms/repo",
                "default_branch": "master",
                "archived": False,
                "allow_forking": True,
            },
        )

    client_noperms = GitHubClient(token="ghp_test", transport=httpx.MockTransport(missing_perms_handler))
    repo_noperms = client_noperms.get_repo("no-perms/repo")
    assert repo_noperms.push is False
    assert repo_noperms.route == "fork"


def test_archived_repo_stops_flow_before_analysis_or_gemini(monkeypatch):
    archived_repo_meta = RepoMeta(
        base_repo="archived/repo",
        base_repo_url="https://github.com/archived/repo",
        default_branch="main",
        archived=True,
        allow_forking=True,
        push=True,
    )
    issue = IssueRef(
        number=1,
        title="Issue in archived repo",
        body="Body",
        url="https://github.com/archived/repo/issues/1",
        base_repo="archived/repo",
    )

    client_mock = MagicMock()
    client_mock.get_authenticated_login.return_value = "player"
    client_mock.search_issues.return_value = [issue]
    client_mock.get_repo.return_value = archived_repo_meta

    def mock_ask_text(msg: str, default: str = "") -> str:
        if "Sage" in msg:
            return ""
        return "test task keywords"

    monkeypatch.setattr(flow, "ask_text", mock_ask_text)
    monkeypatch.setattr(flow, "ask_select", lambda msg, choices: choices[0][1])

    analysis_spy = MagicMock()
    gemini_spy = MagicMock()
    monkeypatch.setattr(flow, "run_analysis", analysis_spy)
    monkeypatch.setattr(flow, "run_gemini", gemini_spy)

    flow.run_flow(client=client_mock)

    # Neither analysis nor gemini should have been invoked
    analysis_spy.assert_not_called()
    gemini_spy.assert_not_called()


def test_fork_route_allow_forking_false_stops_with_fork_blocked(monkeypatch):
    blocked_repo = RepoMeta(
        base_repo="blocked/repo",
        base_repo_url="https://github.com/blocked/repo",
        default_branch="main",
        archived=False,
        allow_forking=False,
        push=False,  # route = fork
    )
    issue = IssueRef(
        number=5,
        title="Fork blocked issue",
        body="Body",
        url="https://github.com/blocked/repo/issues/5",
        base_repo="blocked/repo",
    )

    client_mock = MagicMock()
    client_mock.get_authenticated_login.return_value = "player"
    client_mock.search_issues.return_value = [issue]
    client_mock.get_repo.return_value = blocked_repo

    def mock_ask_text_fork(msg: str, default: str = "") -> str:
        if "Sage" in msg:
            return ""
        return "test task keywords"

    monkeypatch.setattr(flow, "ask_text", mock_ask_text_fork)
    monkeypatch.setattr(flow, "ask_select", lambda msg, choices: choices[0][1])

    analysis_spy = MagicMock()
    monkeypatch.setattr(flow, "run_analysis", analysis_spy)

    flow.run_flow(client=client_mock)
    analysis_spy.assert_not_called()


# ---------------------------------------------------------------------------
# E0 model tests
# ---------------------------------------------------------------------------


def test_e0_bounded_and_sanitized():
    long_title = "Title " * 100  # 600 chars
    long_body = "Paragraph " * 500  # 5000 chars
    dirty_body = f"\x1b[31mRed\x1b[0m\tIndent\u202a{long_body}"

    issue = IssueRef(
        number=99,
        title=long_title,
        body=dirty_body,
        url="https://github.com/owner/repo/issues/99",
        base_repo="owner/repo",
    )

    e0 = E0.from_issue(issue)

    assert e0.number == 99
    assert e0.url == "https://github.com/owner/repo/issues/99"
    assert len(e0.title) <= 300
    assert len(e0.body) <= 4000
    assert e0.truncated is True

    # Sanitization
    assert "\x1b" not in e0.body
    assert "\t" not in e0.body
    assert "\u202a" not in e0.body

    # Original issue is NOT modified
    assert len(issue.title) > 300
    assert len(issue.body) > 4000
    assert "\t" in issue.body


def test_e0_not_truncated_when_small():
    issue = IssueRef(
        number=1,
        title="Small Title",
        body="Small Body",
        url="https://github.com/owner/repo/issues/1",
        base_repo="owner/repo",
    )
    e0 = E0.from_issue(issue)
    assert e0.truncated is False
    assert e0.title == "Small Title"
    assert e0.body == "Small Body"


# ---------------------------------------------------------------------------
# Issue selection helper tests
# ---------------------------------------------------------------------------


def test_selection_helper_rejects_zero_or_more_than_one():
    issue1 = IssueRef(
        number=1,
        title="First",
        url="https://example.com/1",
        base_repo="owner/repo",
    )
    issue2 = IssueRef(
        number=2,
        title="Second",
        url="https://example.com/2",
        base_repo="owner/repo",
    )

    # Exactly one returns the issue
    assert select_single_issue([issue1]) == issue1
    assert select_issue([issue1]) == issue1
    assert select_single_issue(issue1) == issue1

    # Zero selected raises ValueError
    with pytest.raises(ValueError):
        select_single_issue([])

    with pytest.raises(ValueError):
        select_issue([])

    with pytest.raises(ValueError):
        select_single_issue(None)

    # More than one selected raises ValueError
    with pytest.raises(ValueError):
        select_single_issue([issue1, issue2])

    with pytest.raises(ValueError):
        select_issue([issue1, issue2])


def test_format_issue_label():
    issue = IssueRef(
        number=123,
        title="Long Issue Title That Needs Formatting",
        url="https://example.com",
        base_repo="pallets/click",
    )
    label = format_issue_label(issue, max_width=30)
    assert label.startswith("pallets/click #123")
    assert len(label) <= 30
    assert label.endswith("…")


# ---------------------------------------------------------------------------
# Secret token security tests
# ---------------------------------------------------------------------------


def test_token_never_appears_in_errors_logs_or_repr(monkeypatch):
    secret_token = "ghp_SUPER_SECRET_TOKEN_XYZ_98765"
    monkeypatch.setenv("GITHUB_TOKEN", secret_token)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"Error with auth Bearer {secret_token}")

    client = GitHubClient(token=secret_token, transport=httpx.MockTransport(failing_handler))

    # Repr / str never contains secret
    assert secret_token not in repr(client)
    assert secret_token not in str(client)

    # Exceptions never leak secret
    with pytest.raises(GitHubError) as exc_info:
        client.get("/test")
    err_str = str(exc_info.value)
    assert secret_token not in err_str
    assert "***" in err_str


# ---------------------------------------------------------------------------
# Pagination helper tests
# ---------------------------------------------------------------------------


def test_pagination_helper_follows_links_next():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "page=2" in url:
            return httpx.Response(200, json=[{"id": 3}, {"id": 4}])
        # Page 1
        headers = {"Link": '<https://api.github.com/items?page=2>; rel="next"'}
        return httpx.Response(200, headers=headers, json=[{"id": 1}, {"id": 2}])

    client = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
    items = client.paginate("/items", max_pages=2)
    assert len(items) == 4
    assert items == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
