"""Authoritative quest lifecycle processing, expiry, PR matching, and completion accounting."""

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, NamedTuple

from rune import store, theme
from rune.difficulty import get_difficulty
from rune.github import GitHubClient, GitHubError
from rune.models import Quest, QuestPR
from rune.ui import ext, get_console, redact
from rune.workspace import format_time_remaining, render_finish_panel
from rune.xp import compute_total_xp, get_player_stats, rune_level, sync_player_cache


class LifecycleOutcome(str, Enum):
    """Lifecycle transition outcomes."""

    NO_ACTIVE = "NO_ACTIVE"
    EXPIRED = "EXPIRED"
    NO_PR = "NO_PR"
    PR_OPEN = "PR_OPEN"
    PR_CLOSED_UNMERGED = "PR_CLOSED_UNMERGED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


# Module-level aliases
NO_ACTIVE = LifecycleOutcome.NO_ACTIVE
EXPIRED = LifecycleOutcome.EXPIRED
NO_PR = LifecycleOutcome.NO_PR
PR_OPEN = LifecycleOutcome.PR_OPEN
PR_CLOSED_UNMERGED = LifecycleOutcome.PR_CLOSED_UNMERGED
COMPLETED = LifecycleOutcome.COMPLETED
ERROR = LifecycleOutcome.ERROR


class ProcessResult(NamedTuple):
    """Result of processing an active quest."""

    outcome: LifecycleOutcome
    quest: Quest | None = None
    pr: QuestPR | None = None
    error: str | None = None
    level_up: bool = False
    old_level: int = 1
    new_level: int = 1
    xp_awarded: int = 0
    total_xp: int = 0


def match_pull_requests(quest: Quest, prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the single exact matching pull request according to four authoritative criteria.

    All four required:
    1. pr.base.repo.full_name == quest.base_repo
    2. pr.base.ref == quest.base_branch
    3. pr.head.repo.full_name == quest.head_repo (compared case-insensitively; head.repo may be null -> no match)
    4. pr.head.ref == quest.head_branch

    If several exact matches: created_at DESC, then PR number DESC; pick first.
    """
    matches: list[dict[str, Any]] = []

    for pr in prs:
        # 1. Base repo
        base_obj = pr.get("base")
        if not base_obj or not isinstance(base_obj, dict):
            continue
        base_repo_obj = base_obj.get("repo")
        if not base_repo_obj or not isinstance(base_repo_obj, dict):
            continue
        base_repo_name = base_repo_obj.get("full_name")
        if base_repo_name != quest.base_repo:
            continue

        # 2. Base ref
        base_ref = base_obj.get("ref")
        if base_ref != quest.base_branch:
            continue

        # 3. Head repo (case-insensitive; head.repo can be None if fork was deleted)
        head_obj = pr.get("head")
        if not head_obj or not isinstance(head_obj, dict):
            continue
        head_repo_obj = head_obj.get("repo")
        if not head_repo_obj or not isinstance(head_repo_obj, dict):
            continue
        head_repo_name = head_repo_obj.get("full_name")
        if not head_repo_name or not quest.head_repo:
            continue
        if head_repo_name.lower() != quest.head_repo.lower():
            continue

        # 4. Head ref
        head_ref = head_obj.get("ref")
        if head_ref != quest.head_branch:
            continue

        matches.append(pr)

    if not matches:
        return None

    def sort_key(p: dict[str, Any]) -> tuple[datetime, int]:
        raw_created = p.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.min.replace(tzinfo=timezone.utc)
        return (dt, p.get("number") or 0)

    matches.sort(key=sort_key, reverse=True)
    return matches[0]


def process_active_quest(
    now: datetime | None = None,
    github: GitHubClient | None = None,
) -> ProcessResult:
    """Process the single ACTIVE quest: handle expiry, PR matching, completion, and XP awarding.

    This is the ONLY place that handles ACTIVE -> EXPIRED and ACTIVE -> COMPLETED transitions.
    """
    console = get_console()
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Load the ACTIVE quest
    active_quests = store.get_quests_by_status("ACTIVE")
    if not active_quests:
        return ProcessResult(outcome=LifecycleOutcome.NO_ACTIVE)

    quest = active_quests[0]

    # Corrupt check: expires_at must not be null
    if quest.expires_at is None:
        msg = f"Quest {quest.display_id} has status ACTIVE but expires_at is null."
        console.print(redact(msg))
        return ProcessResult(outcome=LifecycleOutcome.ERROR, quest=quest, error=msg)

    # 2. Expiry check
    if now >= quest.expires_at:
        quest.status = "EXPIRED"
        quest.expired_at = now
        store.save_quest(quest)
        return ProcessResult(outcome=LifecycleOutcome.EXPIRED, quest=quest)

    # 3. Fetch PRs
    client: GitHubClient | None = github
    if client is None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token or not str(token).strip():
            msg = redact(theme.missing_token)
            console.print(msg)
            return ProcessResult(outcome=LifecycleOutcome.ERROR, quest=quest, error=msg)
        try:
            client = GitHubClient(token=token)
        except Exception as exc:
            msg = redact(str(exc))
            console.print(msg)
            return ProcessResult(outcome=LifecycleOutcome.ERROR, quest=quest, error=msg)

    head_owner = quest.head_owner or ""
    head_branch = quest.head_branch or ""

    try:
        prs = client.list_pull_requests(
            base_repo=quest.base_repo,
            head_owner=head_owner,
            head_branch=head_branch,
            max_pages=2,
        )
    except Exception as exc:
        msg = redact(str(exc))
        console.print(msg)
        return ProcessResult(outcome=LifecycleOutcome.ERROR, quest=quest, error=msg)

    # 4. Exact PR match
    matched_pr = match_pull_requests(quest, prs)
    if matched_pr is None:
        return ProcessResult(outcome=LifecycleOutcome.NO_PR, quest=quest)

    # 5. Merged check
    merged_at = matched_pr.get("merged_at")
    merged = merged_at is not None
    pr_number = int(matched_pr.get("number", 0))
    pr_url = str(matched_pr.get("html_url") or matched_pr.get("url") or "")
    pr_state = str(matched_pr.get("state") or "")

    quest.pr = QuestPR(
        number=pr_number,
        url=pr_url,
        state=pr_state,
        merged=merged,
    )

    # 6. Completion and XP award
    if merged:
        old_xp = compute_total_xp()
        old_level = rune_level(old_xp)

        quest.status = "COMPLETED"
        quest.completed_at = now
        quest.xp_awarded = True
        store.save_quest(quest)

        new_xp = compute_total_xp()
        new_level = rune_level(new_xp)
        level_up = new_level > old_level

        try:
            sync_player_cache(now=now)
        except Exception:
            pass

        return ProcessResult(
            outcome=LifecycleOutcome.COMPLETED,
            quest=quest,
            pr=quest.pr,
            level_up=level_up,
            old_level=old_level,
            new_level=new_level,
            xp_awarded=quest.xp,
            total_xp=new_xp,
        )
    else:
        store.save_quest(quest)
        if pr_state.lower() == "open":
            return ProcessResult(
                outcome=LifecycleOutcome.PR_OPEN, quest=quest, pr=quest.pr
            )
        else:
            return ProcessResult(
                outcome=LifecycleOutcome.PR_CLOSED_UNMERGED, quest=quest, pr=quest.pr
            )


def render_status_view(
    now: datetime | None = None,
    github: GitHubClient | None = None,
) -> None:
    """Print the full view from stored records for `rune status`."""
    console = get_console()
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Trigger process_active_quest exactly once
    result = process_active_quest(now=now, github=github)

    total_xp, level = get_player_stats()
    console.print(theme.status_header.format(level=level, xp=total_xp))

    target_quest: Quest | None = result.quest
    if target_quest is None:
        quests = store.list_quests()
        if not quests:
            console.print("No active quest.")
            return
        quests.sort(key=lambda q: q.created_at, reverse=True)
        target_quest = quests[0]

    # Render by status
    if target_quest.status == "ACTIVE":
        console.print(ext(target_quest.spec.title))
        diff_name = theme.DIFFICULTY_NAMES.get(
            target_quest.difficulty, target_quest.difficulty
        )
        console.print(f"Difficulty: {diff_name}")

        if target_quest.expires_at is not None:
            time_left = max(
                0, int((target_quest.expires_at - now).total_seconds())
            )
            console.print(theme.timer.format(time=format_time_remaining(time_left)))

        if target_quest.pr:
            console.print(f"PR #{target_quest.pr.number}: {target_quest.pr.state}")
        else:
            console.print("PR: none found")

        console.print(render_finish_panel(target_quest))

    elif target_quest.status == "SETUP_PENDING":
        console.print(theme.setup_pending)

    elif target_quest.status == "SETUP_FAILED":
        reason = (
            f" ({target_quest.failure_reason})"
            if target_quest.failure_reason
            else ""
        )
        console.print(f"{theme.setup_failed}{reason}")
        console.print("A new quest may be accepted.")

    elif target_quest.status == "EXPIRED":
        console.print(ext(theme.expired), style=theme.EMBER)

    elif target_quest.status == "COMPLETED":
        console.print(theme.completed)
        console.print(theme.reward.format(xp=target_quest.xp))


def render_refresh_view(
    now: datetime | None = None,
    github: GitHubClient | None = None,
) -> ProcessResult:
    """Print a concise 1-3 line outcome for `rune refresh`."""
    console = get_console()
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    result = process_active_quest(now=now, github=github)

    if result.outcome == LifecycleOutcome.NO_ACTIVE:
        console.print("No active quest.")

    elif result.outcome == LifecycleOutcome.EXPIRED:
        console.print(theme.expired)

    elif result.outcome == LifecycleOutcome.NO_PR:
        assert result.quest is not None
        time_left = max(
            0, int((result.quest.expires_at - now).total_seconds())  # type: ignore[operator]
        )
        console.print("Quest active. No pull request found yet.")
        console.print(theme.timer.format(time=format_time_remaining(time_left)))

    elif result.outcome == LifecycleOutcome.PR_OPEN:
        assert result.quest is not None and result.pr is not None
        time_left = max(
            0, int((result.quest.expires_at - now).total_seconds())  # type: ignore[operator]
        )
        console.print(f"PR #{result.pr.number} is open. Merge it before expiry.")
        console.print(theme.timer.format(time=format_time_remaining(time_left)))

    elif result.outcome == LifecycleOutcome.PR_CLOSED_UNMERGED:
        assert result.quest is not None and result.pr is not None
        time_left = max(
            0, int((result.quest.expires_at - now).total_seconds())  # type: ignore[operator]
        )
        console.print(f"PR #{result.pr.number} is closed without being merged.")
        console.print(theme.timer.format(time=format_time_remaining(time_left)))

    elif result.outcome == LifecycleOutcome.COMPLETED:
        console.print(theme.completed)
        console.print(theme.reward.format(xp=result.xp_awarded))
        console.print(f"Total XP: {result.total_xp} (Level {result.new_level})")
        if result.level_up:
            console.print(theme.level_up.format(level=result.new_level))

    elif result.outcome == LifecycleOutcome.ERROR:
        console.print(f"Error checking quest: {result.error}")

    return result
