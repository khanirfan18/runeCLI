"""Quest presentation, selection, and acceptance orchestration for RuneCLI."""

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from rune import store, theme
from rune.analysis import EvidenceSnippet
from rune.difficulty import Difficulty, DifficultyInfo, get_difficulty
from rune.models import E0, Quest, QuestIssue, QuestSnippet, QuestFraming, RepoMeta
from rune.prompts import prompt_choose_quest
from rune.ui import box, ext, get_console, section, truncate


def get_quest_duration_seconds(diff_info: DifficultyInfo) -> int:
    """Return quest duration in seconds, honoring RUNE_DURATION_OVERRIDE_SECONDS."""
    override = os.environ.get("RUNE_DURATION_OVERRIDE_SECONDS")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return diff_info.minutes * 60


def render_quest_panel(
    quest: QuestFraming,
    difficulty: Difficulty | str,
    snippets_map: dict[str, Any],
    index: int = 1,
    title: str | None = None,
) -> Panel:
    """Render a single quest proposal box according to the design specification."""
    diff_info = get_difficulty(difficulty)
    diff_key = (
        difficulty.value if hasattr(difficulty, "value") else str(difficulty).upper()
    )
    diff_name = theme.DIFFICULTY_NAMES.get(diff_key, diff_key)

    renderables: list[Any] = []

    # Title & Summary
    renderables.append(ext(quest.title))
    renderables.append(Text(""))
    renderables.append(ext(quest.summary))
    renderables.append(Text(""))

    # Difficulty details
    diff_line = f"Difficulty: {diff_name} · {diff_info.minutes}m · +{diff_info.xp} XP"
    renderables.append(Text(diff_line, style="bold"))
    renderables.append(Text(""))

    # Objectives (Acceptance Criteria)
    renderables.append(section(theme.objectives))
    for ac in quest.acceptance_criteria:
        cites = ", ".join(ac.evidence_ids)
        renderables.append(ext(f"[{ac.id}] {ac.statement} (evidence: {cites})"))

    # Inscriptions (Cited snippets, max 5 lines each)
    cited_ids = set(quest.evidence_ids)
    for ac in quest.acceptance_criteria:
        cited_ids.update(ac.evidence_ids)
    cited_ids.discard("E0")

    if cited_ids:
        renderables.append(Text(""))
        renderables.append(section(theme.inscriptions))
        for eid in sorted(cited_ids):
            if eid in snippets_map:
                s = snippets_map[eid]
                renderables.append(ext(f"{s.path} ({s.id}):"))
                lines = s.snippet.splitlines()
                shown = lines[:5]
                for line in shown:
                    renderables.append(ext(f"  {line}"))
                if len(lines) > 5:
                    renderables.append(ext(f"  … {len(lines) - 5} more lines"))

    panel_title = title or f"Quest Option {index}"
    return box(Group(*renderables), title=panel_title)


def render_quest_view(quest: Quest) -> Panel:
    """Render a quest view from a durable Quest record without network/Gemini calls."""
    snippets_map = {s.id: s for s in quest.snippets}
    return render_quest_panel(
        quest.spec,
        quest.difficulty,
        snippets_map,
        title=f"Quest {quest.display_id}",
    )


def show_offered_quests(
    quests: list[QuestFraming],
    difficulty: Difficulty | str,
    evidence: list[EvidenceSnippet],
) -> None:
    """Print all offered quest proposal panels."""
    console = get_console()
    snippets_map = {s.id: s for s in evidence}
    for idx, q in enumerate(quests, start=1):
        panel = render_quest_panel(q, difficulty, snippets_map, index=idx)
        console.print(panel)


def choose_quest_option(quests: list[QuestFraming]) -> QuestFraming | None:
    """Prompt the user to accept a quest or decline all."""
    chosen = prompt_choose_quest(quests)
    if chosen is None:
        get_console().print(theme.abandoned)
        return None
    return chosen


def accept_quest(
    spec: QuestFraming,
    e0: E0,
    repo_meta: RepoMeta,
    difficulty: Difficulty | str,
    evidence: list[EvidenceSnippet],
) -> Quest | None:
    """Accept and atomically persist a quest in SETUP_PENDING status.

    Refuses if any quest has status ACTIVE.
    """
    console = get_console()
    active_quests = store.get_quests_by_status("ACTIVE")
    if active_quests:
        active_q = active_quests[0]
        console.print(
            theme.active_exists.format(
                title=active_q.spec.title, id=active_q.display_id
            )
        )
        return None

    diff_info = get_difficulty(difficulty)
    duration = get_quest_duration_seconds(diff_info)
    diff_str = (
        difficulty.value if hasattr(difficulty, "value") else str(difficulty)
    )

    # Collect cited snippets (full text, E0 excluded as it is stored in issue)
    snippets_map = {s.id: s for s in evidence}
    cited_ids: set[str] = set(spec.evidence_ids)
    for ac in spec.acceptance_criteria:
        cited_ids.update(ac.evidence_ids)
    cited_ids.discard("E0")

    stored_snippets: list[QuestSnippet] = []
    for eid in sorted(cited_ids):
        if eid in snippets_map:
            s = snippets_map[eid]
            stored_snippets.append(
                QuestSnippet(
                    id=s.id,
                    path=s.path,
                    start_line=s.start_line,
                    end_line=s.end_line,
                    snippet=s.snippet,
                )
            )

    quest_id = str(uuid.uuid4())
    display_id = quest_id[:8]
    now = datetime.now(timezone.utc)

    quest = Quest(
        id=quest_id,
        display_id=display_id,
        status="SETUP_PENDING",
        created_at=now,
        claimed_at=None,
        expires_at=None,
        completed_at=None,
        expired_at=None,
        failure_reason=None,
        issue=QuestIssue(number=e0.number, title=e0.title, url=e0.url),
        base_repo=repo_meta.base_repo,
        base_repo_url=repo_meta.base_repo_url,
        base_branch=repo_meta.default_branch,
        route=repo_meta.route,
        head_repo=None,
        head_owner=None,
        head_branch=None,
        difficulty=diff_str,
        xp=diff_info.xp,
        duration_seconds=duration,
        xp_awarded=False,
        workspace_path=None,
        pr=None,
        spec=spec,
        snippets=stored_snippets,
    )

    store.save_quest(quest)
    return quest
