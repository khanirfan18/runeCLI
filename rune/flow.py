"""Quest flow orchestration for RuneCLI."""

import os
import sys
from typing import Any

from rune import store, theme
from rune.difficulty import DIFFICULTY_LOOKUP, Difficulty
from rune.editor import detect_editors, handle_active_quest
from rune.lifecycle import process_active_quest
from rune.github import (
    GitHubClient,
    build_search_query,
    extract_keywords,
    format_issue_label,
    select_single_issue,
    validate_sage,
)
from rune.analysis import clone_repo, extract_evidence
from rune.gemma import generate_quests
from rune.models import E0, GemmaOutput, IssueRef, RepoMeta
from rune.prompts import ask_select, ask_text
from rune.quest import accept_quest, choose_quest_option, show_offered_quests
from rune.ui import box, get_console, truncate, working
from rune.workspace import run_setup_flow


def run_analysis(repo_meta: RepoMeta, e0: E0) -> list[Any]:
    """Execute analysis clone and evidence extraction."""
    with working("Analyzing repository..."):
        parts = repo_meta.base_repo.split("/")
        owner, repo_name = parts[0], parts[1]
        repo_dir = clone_repo(owner, repo_name, repo_meta.default_branch)
        evidence = extract_evidence(repo_dir, e0)
    return evidence


def run_gemini(user_input: str, e0: E0, evidence: list[Any]) -> GemmaOutput:
    """Execute Gemma 4 quest framing generation."""
    with working("Consulting Gemma..."):
        return generate_quests(user_input, e0, evidence)


def print_e0_summary(e0: E0, repo_meta: RepoMeta) -> None:
    """Render the E0 summary box including the route, then print the placeholder."""
    console = get_console()
    summary_lines = [
        f"Repo:   {repo_meta.base_repo}",
        f"Issue:  #{e0.number} {e0.title}",
        f"URL:    {e0.url}",
        f"Route:  {repo_meta.route}",
    ]
    if e0.body:
        summary_lines.append("")
        summary_lines.append(truncate(e0.body, 70))

    summary_panel = box("\n".join(summary_lines), title=theme.quest_offered)
    console.print(summary_panel)
    console.print(theme.analysis_not_wired)


def run_flow(
    client: GitHubClient | None = None,
    reopen_confirm: Any = None,
) -> None:
    """Execute the core interactive Rune Quest Board flow."""
    # When invoked without a TTY stdin in automated runners, preserve placeholder
    if client is None and not sys.stdin.isatty():
        console = get_console()
        console.print("flow not wired yet")
        return

    console = get_console()
    client = client or GitHubClient()

    # 1. Sign in
    with working("Authenticating..."):
        login = client.get_authenticated_login()
    console.print(theme.signed_in.format(login=login))

    # Early IDE check: if neither editor is found, show theme.ide_required and exit non-zero
    editors = detect_editors()
    if not editors:
        console.print(theme.ide_required)
        sys.exit(1)

    # Process active quest: handle expiry, PR matching, completion, XP
    result = process_active_quest(github=client)
    if result.quest and result.quest.status == "ACTIVE":
        active_q = result.quest
        console.print(
            theme.active_exists.format(
                title=active_q.spec.title, id=active_q.display_id
            )
        )
        if reopen_confirm is not None:
            handle_active_quest(active_q, editors, confirm_prompt=reopen_confirm)
        else:
            handle_active_quest(active_q, editors)
        return

    # 2. What do you want to work on? (keywords >= 3 chars, max 8)
    keywords: list[str] = []
    while True:
        work_input = ask_text(theme.ask_work)
        if work_input is None:
            return
        work_input = work_input.strip()
        if not (1 <= len(work_input) <= 200):
            continue
        extracted = extract_keywords(work_input)
        if extracted:
            keywords = extracted
            break

    # 3. Sage (optional text, pre-filled with RUNE_SEARCH_USER)
    default_sage = os.environ.get("RUNE_SEARCH_USER", "")
    sage: str | None = None
    while True:
        sage_input = ask_text(theme.ask_sage, default=default_sage)
        if sage_input is None:
            return
        sage_clean = sage_input.strip()
        if not sage_clean:
            sage = None
            break
        if validate_sage(sage_clean):
            sage = sage_clean
            break

    # 4. Only unassigned quests? (Yes listed first)
    unassigned = ask_select(
        theme.ask_unassigned,
        [("Yes", True), ("No", False)],
    )
    if unassigned is None:
        return

    # 5. Difficulty (theme names)
    difficulty_choices = [
        (theme.DIFFICULTY_NAMES[d.value], d) for d in Difficulty
    ]
    difficulty = ask_select(theme.ask_difficulty, difficulty_choices)
    if difficulty is None:
        return

    # 6. Search GET /search/issues
    q = build_search_query(keywords=keywords, unassigned=unassigned, sage=sage)
    with working("Searching for quests..."):
        results = client.search_issues(q, per_page=10, unassigned=unassigned)

    # 7 & 8. Results handling
    if not results:
        console.print(theme.zero_results)
        return

    # 9. User selects exactly ONE issue
    issue_choices = [(format_issue_label(issue), issue) for issue in results]
    selected_issue = ask_select(theme.ask_select_issue, issue_choices)
    if selected_issue is None:
        return

    issue = select_single_issue([selected_issue])

    # 10. Repo check: GET /repos/{base_repo}
    with working("Checking repository..."):
        repo_meta = client.get_repo(issue.base_repo)

    if repo_meta.archived:
        console.print(theme.repo_archived)
        return

    if repo_meta.route == "fork" and not repo_meta.allow_forking:
        console.print(theme.fork_blocked)
        return

    # 11. Build E0 from selected search result
    e0 = E0.from_issue(issue)

    # 12. Run analysis clone and evidence extraction
    evidence = run_analysis(repo_meta, e0)

    # 13. Run Gemma quest framing generation
    gemma_output = run_gemini(work_input, e0, evidence)
    if gemma_output and gemma_output.status == "INSUFFICIENT_EVIDENCE":
        console.print(f"{theme.insufficient} {gemma_output.reason}")
        return

    # 14. Present quests and prompt choice
    if gemma_output and gemma_output.quests:
        show_offered_quests(gemma_output.quests, difficulty, evidence)
        chosen_quest = choose_quest_option(gemma_output.quests)
        if chosen_quest is None:
            return

        # 15. Accept quest and write durable record
        quest = accept_quest(
            chosen_quest,
            e0=e0,
            repo_meta=repo_meta,
            difficulty=difficulty,
            evidence=evidence,
        )
        if quest is not None:
            run_setup_flow(quest, login)
    else:
        print_e0_summary(e0, repo_meta)
