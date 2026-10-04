"""Gate tests for workspace setup, command generation, read-only verification, timer activation, and recovery."""

import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rune import store, theme
from rune.models import AcceptanceCriterion, Quest, QuestFraming, QuestIssue, QuestSnippet
from rune.recovery import recover_stale_setups
from rune.workspace import (
    activate_quest,
    create_workspace_folder,
    finish_commands,
    format_time_remaining,
    generate_branch_name,
    generate_slug,
    parse_remote_repo,
    run_setup_flow,
    sanitize_commit_message,
    setup_commands,
    setup_head,
    validate_base_branch,
    validate_branch_name,
    verify_workspace,
)


def make_test_quest(
    quest_id: str | None = None,
    status: str = "SETUP_PENDING",
    route: str = "fork",
    base_repo: str = "pallets/click",
    base_branch: str = "main",
    issue_number: int = 42,
    issue_title: str = "CLI parser crashes on unknown option",
    created_at: datetime | None = None,
    duration_seconds: int = 180 * 60,
    head_repo: str | None = None,
    head_owner: str | None = None,
    head_branch: str | None = None,
    workspace_path: str | None = None,
) -> Quest:
    qid = quest_id or str(uuid.uuid4())
    display_id = qid[:8]
    created = created_at or datetime.now(timezone.utc)
    return Quest(
        id=qid,
        display_id=display_id,
        status=status,
        created_at=created,
        claimed_at=None,
        expires_at=None,
        completed_at=None,
        expired_at=None,
        failure_reason=None,
        issue=QuestIssue(
            number=issue_number,
            title=issue_title,
            url=f"https://github.com/{base_repo}/issues/{issue_number}",
        ),
        base_repo=base_repo,
        base_repo_url=f"https://github.com/{base_repo}",
        base_branch=base_branch,
        route=route,
        head_repo=head_repo,
        head_owner=head_owner,
        head_branch=head_branch,
        difficulty="NORMAL",
        xp=150,
        duration_seconds=duration_seconds,
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
# 1. Command generation for direct and fork routes
# ---------------------------------------------------------------------------


def test_command_generation_direct():
    quest = make_test_quest(
        route="direct",
        base_repo="pallets/click",
        base_branch="main",
        head_repo="pallets/click",
        head_owner="pallets",
        head_branch="rune/a1b2c3d4-42-cli-parser-crashes",
    )
    cmds = setup_commands(quest)
    assert cmds == [
        "git clone --depth 50 https://github.com/pallets/click.git .",
        "git switch -c rune/a1b2c3d4-42-cli-parser-crashes",
    ]


def test_command_generation_fork():
    quest = make_test_quest(
        route="fork",
        base_repo="pallets/click",
        base_branch="develop",
        head_repo="alice/click",
        head_owner="alice",
        head_branch="rune/a1b2c3d4-42-cli-parser-crashes",
    )
    cmds = setup_commands(quest)
    assert cmds == [
        "git clone --depth 50 https://github.com/alice/click.git .",
        "git remote add upstream https://github.com/pallets/click.git",
        "git fetch --depth 50 --no-tags upstream develop",
        "git switch -c rune/a1b2c3d4-42-cli-parser-crashes --no-track upstream/develop",
    ]


def test_finish_commands():
    quest = make_test_quest(
        issue_title="Handle unknown flag cleanly",
        issue_number=99,
        head_branch="rune/fedcba98-99-handle-unknown-flag",
    )
    cmds = finish_commands(quest)
    assert cmds == [
        "git add .",
        'git commit -m "Handle unknown flag cleanly (#99)"',
        "git push -u origin rune/fedcba98-99-handle-unknown-flag",
    ]


def test_setup_commands_rejects_invalid_base_branch():
    assert not validate_base_branch("-main")
    assert not validate_base_branch("--evil")
    assert not validate_base_branch("main;rm -rf /")
    assert not validate_base_branch("")
    assert validate_base_branch("main")
    assert validate_base_branch("feat/my-branch_1.0")

    quest = make_test_quest(
        base_branch="-invalid-flag",
        head_repo="pallets/click",
        head_branch="rune/a1b2c3d4-42-fix",
    )
    with pytest.raises(ValueError, match="Invalid base_branch"):
        setup_commands(quest)


# ---------------------------------------------------------------------------
# 2. Commit message sanitization
# ---------------------------------------------------------------------------


def test_commit_message_sanitization_rules():
    # Standard format
    msg = sanitize_commit_message("Fix CLI argument parsing crash", 42)
    assert msg == "Fix CLI argument parsing crash (#42)"
    assert len(msg) <= 72

    # Character set filtering: disallow quotes, brackets, ampersands, backticks, emojis
    raw = 'Fix: `quoted` & *starred* & [bracketed] bug 🔥 -- "quotes"'
    msg = sanitize_commit_message(raw, 10)
    assert "`" not in msg
    assert "&" not in msg
    assert "*" not in msg
    assert "[" not in msg
    assert "]" not in msg
    assert '"' not in msg
    assert "🔥" not in msg
    assert msg.endswith(" (#10)")
    assert len(msg) <= 72

    # Collapsing spaces and whitespace
    msg = sanitize_commit_message("Multiple   spaces\tand\nnewlines", 7)
    assert msg == "Multiple spaces and newlines (#7)"

    # Truncation to 72 chars max including suffix
    long_title = "A" * 100
    msg = sanitize_commit_message(long_title, 123)
    assert len(msg) <= 72
    assert msg.endswith(" (#123)")
    assert msg.startswith("AAAA")

    # Empty or all-filtered characters fallback to 'quest'
    msg = sanitize_commit_message("   ", 5)
    assert msg == "quest (#5)"

    msg = sanitize_commit_message("🔥🔥🔥", 1)
    assert msg == "quest (#1)"


# ---------------------------------------------------------------------------
# 3. Branch name format and git check-ref-format
# ---------------------------------------------------------------------------


def test_branch_name_slug_and_validation():
    # Slug conversion: lowercase, characters outside [a-z0-9] become '-', collapsed, trimmed, max 30 chars
    assert generate_slug("Simple title") == "simple-title"
    assert generate_slug("---weird---edges---") == "weird-edges"
    assert generate_slug("Fix bug #123 (urgent!)") == "fix-bug-123-urgent"
    assert generate_slug("a" * 50) == "a" * 30
    assert generate_slug("???") == "quest"

    # Branch name generation and validation against real git check-ref-format
    branch = generate_branch_name("a1b2c3d4", 42, "Fix issue with CLI options")
    assert branch == "rune/a1b2c3d4-42-fix-issue-with-cli-options"
    assert validate_branch_name(branch)

    # Validate that invalid branch names fail validation
    assert not validate_branch_name("-invalid-branch")
    assert not validate_branch_name("rune/..double-dots")
    assert not validate_branch_name("rune/trailing-dot.")


# ---------------------------------------------------------------------------
# 4. Head determination & workspace folder creation
# ---------------------------------------------------------------------------


def test_head_determination(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # Direct route
    q_direct = make_test_quest(route="direct", base_repo="pallets/click")
    setup_head(q_direct, login="alice")
    assert q_direct.head_repo == "pallets/click"
    assert q_direct.head_owner == "pallets"
    assert q_direct.head_branch.startswith(f"rune/{q_direct.display_id}-42-")

    # Fork route
    q_fork = make_test_quest(route="fork", base_repo="pallets/click")
    setup_head(q_fork, login="alice")
    assert q_fork.head_repo == "alice/click"
    assert q_fork.head_owner == "alice"
    assert q_fork.head_branch.startswith(f"rune/{q_fork.display_id}-42-")


def test_create_workspace_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest()

    ws_path = create_workspace_folder(quest)
    assert ws_path.exists()
    assert ws_path.is_dir()
    assert quest.workspace_path == str(ws_path)

    # Refuse if already exists
    with pytest.raises(FileExistsError, match="already exists"):
        create_workspace_folder(quest)


# ---------------------------------------------------------------------------
# 5. Remote URL parsing helper
# ---------------------------------------------------------------------------


def test_parse_remote_repo():
    assert parse_remote_repo("https://github.com/alice/click.git") == "alice/click"
    assert parse_remote_repo("https://github.com/alice/click") == "alice/click"
    assert parse_remote_repo("https://github.com/alice/click/") == "alice/click"
    assert parse_remote_repo("https://github.com/alice/click.git/") == "alice/click"
    assert parse_remote_repo("git@github.com:alice/click.git") == "alice/click"
    assert parse_remote_repo("git@github.com:alice/click") == "alice/click"
    assert parse_remote_repo("ssh://git@github.com/alice/click.git") == "alice/click"
    assert parse_remote_repo("ssh://git@github.com:22/alice/click.git") == "alice/click"
    assert parse_remote_repo("invalid-url") is None
    assert parse_remote_repo("") is None


# ---------------------------------------------------------------------------
# 6. Read-only verification on real git repository
# ---------------------------------------------------------------------------


def test_verification_success_https(tmp_path):
    repo_dir = tmp_path / "ws_https"
    repo_dir.mkdir()
    branch = "rune/a1b2c3d4-42-test-branch"

    subprocess.run(["git", "init", "-b", branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/alice/click.git"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    ok, err = verify_workspace(repo_dir, "alice/click", branch)
    assert ok is True
    assert err == ""


def test_verification_success_ssh(tmp_path):
    repo_dir = tmp_path / "ws_ssh"
    repo_dir.mkdir()
    branch = "rune/a1b2c3d4-42-test-branch"

    subprocess.run(["git", "init", "-b", branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:alice/click.git"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    ok, err = verify_workspace(repo_dir, "alice/click", branch)
    assert ok is True
    assert err == ""


def test_verification_fails_when_git_missing(tmp_path):
    non_git_dir = tmp_path / "empty_dir"
    non_git_dir.mkdir()

    ok, err = verify_workspace(non_git_dir, "alice/click", "rune/test-branch")
    assert ok is False
    assert ".git" in err


def test_verification_fails_when_remote_wrong(tmp_path):
    repo_dir = tmp_path / "ws_wrong_remote"
    repo_dir.mkdir()
    branch = "rune/a1b2c3d4-42-test-branch"

    subprocess.run(["git", "init", "-b", branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/wrong/repo.git"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    ok, err = verify_workspace(repo_dir, "alice/click", branch)
    assert ok is False
    assert "alice/click" in err


def test_verification_fails_when_branch_wrong(tmp_path):
    repo_dir = tmp_path / "ws_wrong_branch"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/alice/click.git"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    ok, err = verify_workspace(repo_dir, "alice/click", "rune/a1b2c3d4-42-test-branch")
    assert ok is False
    assert "main" in err
    assert "rune/a1b2c3d4-42-test-branch" in err


# ---------------------------------------------------------------------------
# 7. Timer activation and duration override
# ---------------------------------------------------------------------------


def test_timer_activation_standard(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest(
        head_repo="alice/click",
        head_branch="rune/a1b2c3d4-42-test",
        duration_seconds=3600,
    )
    store.save_quest(quest)

    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
    res = activate_quest(quest, now=t0)
    assert res is True
    assert quest.status == "ACTIVE"
    assert quest.claimed_at == t0
    assert quest.expires_at == t0 + timedelta(seconds=3600)

    # Persisted atomically
    loaded = store.load_quest(quest.id)
    assert loaded is not None
    assert loaded.status == "ACTIVE"
    assert loaded.claimed_at == t0
    assert loaded.expires_at == t0 + timedelta(seconds=3600)


def test_timer_activation_duration_override(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    monkeypatch.setenv("RUNE_DURATION_OVERRIDE_SECONDS", "300")

    quest = make_test_quest(
        head_repo="alice/click",
        head_branch="rune/a1b2c3d4-42-test",
        duration_seconds=3600,
    )
    store.save_quest(quest)

    t0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
    res = activate_quest(quest, now=t0)
    assert res is True
    assert quest.duration_seconds == 300
    assert quest.expires_at == t0 + timedelta(seconds=300)
    assert quest.xp == 150  # XP is never modified by override


def test_timer_activation_refuses_when_active_quest_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # Active quest already in store
    q_existing = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="ACTIVE",
        head_repo="pallets/click",
        head_branch="rune/existing",
    )
    store.save_quest(q_existing)

    # New quest trying to activate
    q_new = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="SETUP_PENDING",
        head_repo="alice/click",
        head_branch="rune/new",
    )
    store.save_quest(q_new)

    res = activate_quest(q_new)
    assert res is False
    assert q_new.status == "SETUP_FAILED"
    assert q_new.failure_reason is not None
    assert "already active" in q_new.failure_reason

    # Verify persisted state
    loaded = store.load_quest(q_new.id)
    assert loaded.status == "SETUP_FAILED"
    assert "already active" in loaded.failure_reason


# ---------------------------------------------------------------------------
# 8. Stale setup recovery
# ---------------------------------------------------------------------------


def test_stale_setup_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    run_started_at = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)

    # Quest 1: SETUP_PENDING from prior run (stale)
    q1 = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="SETUP_PENDING",
        created_at=run_started_at - timedelta(minutes=10),
    )
    store.save_quest(q1)

    # Quest 2: SETUP_PENDING from current run (not stale)
    q2 = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="SETUP_PENDING",
        created_at=run_started_at + timedelta(seconds=5),
    )
    store.save_quest(q2)

    # Quest 3: ACTIVE from prior run (untouched)
    q3 = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="ACTIVE",
        created_at=run_started_at - timedelta(minutes=30),
    )
    store.save_quest(q3)

    # Quest 4: COMPLETED (untouched)
    q4 = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="COMPLETED",
        created_at=run_started_at - timedelta(hours=2),
    )
    store.save_quest(q4)

    # Quest 5: EXPIRED (untouched)
    q5 = make_test_quest(
        quest_id=str(uuid.uuid4()),
        status="EXPIRED",
        created_at=run_started_at - timedelta(hours=3),
    )
    store.save_quest(q5)

    recovered = recover_stale_setups(run_started_at)
    assert len(recovered) == 1
    assert recovered[0].id == q1.id

    # Verify q1 became SETUP_FAILED with proper reason and null timers
    l1 = store.load_quest(q1.id)
    assert l1.status == "SETUP_FAILED"
    assert l1.failure_reason == "abandoned during setup"
    assert l1.claimed_at is None
    assert l1.expires_at is None
    assert l1.issue.number == q1.issue.number  # other fields preserved

    # Verify q2 stayed SETUP_PENDING
    l2 = store.load_quest(q2.id)
    assert l2.status == "SETUP_PENDING"
    assert l2.failure_reason is None

    # Verify q3, q4, q5 remained untouched
    assert store.load_quest(q3.id).status == "ACTIVE"
    assert store.load_quest(q4.id).status == "COMPLETED"
    assert store.load_quest(q5.id).status == "EXPIRED"


# ---------------------------------------------------------------------------
# 9. Guided setup flow orchestration
# ---------------------------------------------------------------------------


def test_run_setup_flow_abort(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest()

    # User inputs 'q' to abort
    ok = run_setup_flow(quest, login="alice", action_prompt=lambda: "q")
    assert ok is False
    assert quest.status == "SETUP_PENDING"
    assert quest.claimed_at is None
    assert Path(quest.workspace_path).exists()


def test_run_setup_flow_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest()

    # User inputs 's' to skip
    ok = run_setup_flow(quest, login="alice", action_prompt=lambda: "s")
    assert ok is False
    assert quest.status == "SETUP_PENDING"
    assert quest.claimed_at is None


def test_run_setup_flow_success(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    quest = make_test_quest()

    # We first run setup_head and create workspace folder, initialize real git repo inside it
    setup_head(quest, login="alice")
    ws_dir = create_workspace_folder(quest)
    subprocess.run(["git", "init", "-b", quest.head_branch], cwd=ws_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{quest.head_repo}.git"],
        cwd=ws_dir,
        check=True,
        capture_output=True,
    )

    # Reset workspace_path and folder check by creating a new quest id so create_workspace_folder works
    new_quest = make_test_quest()
    def mock_action():
        # Setup the git repo in new_quest's workspace folder after it's created
        ws = Path(new_quest.workspace_path)
        subprocess.run(["git", "init", "-b", new_quest.head_branch], cwd=ws, check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", f"https://github.com/{new_quest.head_repo}.git"],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        return ""

    ok = run_setup_flow(new_quest, login="alice", action_prompt=mock_action)
    assert ok is True
    assert new_quest.status == "ACTIVE"
    assert new_quest.claimed_at is not None
    assert new_quest.expires_at is not None


def test_format_time_remaining():
    assert format_time_remaining(3600) == "1h"
    assert format_time_remaining(5400) == "1h 30m"
    assert format_time_remaining(180) == "3m"
    assert format_time_remaining(90) == "1m 30s"
    assert format_time_remaining(45) == "45s"
