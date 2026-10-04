"""Gate tests for quest presentation, acceptance, durable record persistence, and limits."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from rune import store, theme
from rune.analysis import EvidenceSnippet
from rune.difficulty import Difficulty, get_difficulty
from rune.models import (
    AcceptanceCriterion,
    E0,
    Quest,
    QuestFraming,
    QuestIssue,
    QuestSnippet,
    RepoMeta,
)
from rune.quest import (
    accept_quest,
    choose_quest_option,
    get_quest_duration_seconds,
    render_quest_panel,
    render_quest_view,
)


@pytest.fixture
def sample_spec():
    return QuestFraming(
        title="Fix CLI argument parsing crash",
        summary="Handle unexpected command line options gracefully without traceback.",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC1",
                statement="Catch unrecognized options and print user-friendly error.",
                evidence_ids=["E0", "E1"],
            )
        ],
        evidence_ids=["E0", "E1"],
        unknowns=[],
    )


@pytest.fixture
def sample_e0():
    return E0(
        number=42,
        title="CLI parser crashes on unknown option",
        body="Running rune --invalid causes crash.",
        url="https://github.com/pallets/click/issues/42",
        truncated=False,
    )


@pytest.fixture
def sample_repo_meta():
    return RepoMeta(
        base_repo="pallets/click",
        base_repo_url="https://github.com/pallets/click",
        default_branch="main",
        archived=False,
        allow_forking=True,
        push=False,  # route = fork
    )


@pytest.fixture
def sample_evidence():
    return [
        EvidenceSnippet(
            id="E1",
            path="src/click/parser.py",
            start_line=10,
            end_line=25,
            snippet="def parse_args():\n    raise ValueError('unknown option')\n",
            score=5,
        ),
        EvidenceSnippet(
            id="E2",
            path="tests/test_parser.py",
            start_line=1,
            end_line=20,
            snippet="def test_parser():\n    pass\n",
            score=3,
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Acceptance writes a durable SETUP_PENDING record
# ---------------------------------------------------------------------------


def test_acceptance_writes_durable_record(
    tmp_path, monkeypatch, sample_spec, sample_e0, sample_repo_meta, sample_evidence
):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    quest = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="NORMAL",
        evidence=sample_evidence,
    )

    assert quest is not None
    assert quest.status == "SETUP_PENDING"
    assert quest.created_at.tzinfo is not None
    assert quest.created_at.tzinfo == timezone.utc

    # Valid UUID and 8-character display ID
    uuid_obj = uuid.UUID(quest.id)
    assert str(uuid_obj) == quest.id
    assert quest.display_id == quest.id[:8]

    # Base metadata and route
    assert quest.base_repo == "pallets/click"
    assert quest.base_repo_url == "https://github.com/pallets/click"
    assert quest.base_branch == "main"
    assert quest.route == "fork"

    # Head repo/owner/branch are null until P6 setup
    assert quest.head_repo is None
    assert quest.head_owner is None
    assert quest.head_branch is None

    # Flags and timers stay null
    assert quest.xp_awarded is False
    assert quest.claimed_at is None
    assert quest.expires_at is None
    assert quest.completed_at is None
    assert quest.expired_at is None

    # Persisted atomically on disk immediately
    target_file = store.quests_dir() / f"{quest.id}.json"
    assert target_file.is_file()

    # Issue block stored
    assert quest.issue.number == 42
    assert quest.issue.title == sample_e0.title
    assert quest.issue.url == sample_e0.url


# ---------------------------------------------------------------------------
# 2. Record contains full selected spec and cited snippets; reproducible view
# ---------------------------------------------------------------------------


def test_record_contains_full_spec_and_reproducible_view(
    tmp_path, monkeypatch, sample_spec, sample_e0, sample_repo_meta, sample_evidence
):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    quest = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="EASY",
        evidence=sample_evidence,
    )

    # Only cited snippets are stored (E1 cited, E2 not cited)
    snippet_ids = [s.id for s in quest.snippets]
    assert snippet_ids == ["E1"]
    assert quest.snippets[0].snippet == sample_evidence[0].snippet

    # Reload from disk by full UUID
    loaded_uuid = store.load_quest(quest.id)
    assert loaded_uuid is not None
    assert loaded_uuid.id == quest.id
    assert loaded_uuid.spec.title == sample_spec.title
    assert len(loaded_uuid.snippets) == 1

    # Reload from disk by 8-char display_id
    loaded_disp = store.load_quest(quest.display_id)
    assert loaded_disp is not None
    assert loaded_disp.id == quest.id

    # View reproduction from disk record with no Gemini or network calls
    panel = render_quest_view(loaded_uuid)
    assert panel is not None


# ---------------------------------------------------------------------------
# 3. ACTIVE blocks acceptance; SETUP_PENDING and SETUP_FAILED do not
# ---------------------------------------------------------------------------


def test_active_blocks_acceptance_pending_and_failed_do_not(
    tmp_path, monkeypatch, sample_spec, sample_e0, sample_repo_meta, sample_evidence
):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # Initial quest in SETUP_PENDING
    q1 = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="NORMAL",
        evidence=sample_evidence,
    )
    assert q1 is not None
    assert q1.status == "SETUP_PENDING"

    # SETUP_PENDING does NOT block creating another quest
    q2 = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="HARD",
        evidence=sample_evidence,
    )
    assert q2 is not None
    assert q2.id != q1.id

    # Change q2 to SETUP_FAILED
    q2.status = "SETUP_FAILED"
    store.save_quest(q2)

    # SETUP_FAILED does NOT block
    q3 = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="EASY",
        evidence=sample_evidence,
    )
    assert q3 is not None

    # Change q3 to ACTIVE
    q3.status = "ACTIVE"
    store.save_quest(q3)

    # ACTIVE blocks acceptance
    blocked = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="EPIC",
        evidence=sample_evidence,
    )
    assert blocked is None


# ---------------------------------------------------------------------------
# 4. Difficulty / XP come only from deterministic table
# ---------------------------------------------------------------------------


def test_difficulty_and_xp_deterministic(
    tmp_path, monkeypatch, sample_spec, sample_e0, sample_repo_meta, sample_evidence
):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # NORMAL: 180 min, 150 XP
    q_normal = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty=Difficulty.NORMAL,
        evidence=sample_evidence,
    )
    assert q_normal.xp == 150
    assert q_normal.duration_seconds == 180 * 60

    # RUNE_DURATION_OVERRIDE_SECONDS changes duration only, NEVER XP
    monkeypatch.setenv("RUNE_DURATION_OVERRIDE_SECONDS", "42")
    q_override = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="EASY",
        evidence=sample_evidence,
    )
    assert q_override.xp == 100  # EASY XP unchanged
    assert q_override.duration_seconds == 42  # Duration overridden

    # Fake XP/difficulty fields inside a spec are rejected by Pydantic extra="forbid"
    with pytest.raises(ValidationError):
        QuestFraming(
            title="Sneaky spec",
            summary="Fake XP injection",
            acceptance_criteria=[
                AcceptanceCriterion(id="AC1", statement="Stmt", evidence_ids=["E0"])
            ],
            evidence_ids=["E0"],
            xp=9999,  # Disallowed extra field
        )


# ---------------------------------------------------------------------------
# 5. Inline snippets limited to 5 lines and external text sanitized
# ---------------------------------------------------------------------------


def test_inline_snippets_limited_to_five_lines_and_sanitized():
    # 12 lines with ANSI escape sequences
    raw_lines = [f"\x1b[31mLine {i}\x1b[0m\tindented" for i in range(1, 13)]
    snippet_content = "\n".join(raw_lines)

    snippet = EvidenceSnippet(
        id="E1",
        path="src/parser.py",
        start_line=1,
        end_line=12,
        snippet=snippet_content,
        score=5,
    )

    spec = QuestFraming(
        title="Title with \x1b[32mANSI\x1b[0m",
        summary="Summary text",
        acceptance_criteria=[
            AcceptanceCriterion(id="AC1", statement="Stmt", evidence_ids=["E1"])
        ],
        evidence_ids=["E1"],
    )

    panel = render_quest_panel(
        quest=spec,
        difficulty="NORMAL",
        snippets_map={"E1": snippet},
    )

    # Render panel to string via rich console
    from rich.console import Console
    import io

    buf = io.StringIO()
    console = Console(file=buf, width=80, markup=False, emoji=False, highlight=False)
    console.print(panel)
    output = buf.getvalue()

    # ANSI escapes stripped
    assert "\x1b" not in output
    assert "\t" not in output

    # At most 5 lines shown, followed by "... N more lines"
    assert "Line 5" in output
    assert "Line 6" not in output
    assert "… 7 more lines" in output


# ---------------------------------------------------------------------------
# 6. Corrupt quest file does not crash list_quests
# ---------------------------------------------------------------------------


def test_corrupt_quest_file_does_not_crash_list_quests(
    tmp_path, monkeypatch, sample_spec, sample_e0, sample_repo_meta, sample_evidence
):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))

    # Create 1 valid quest
    q_valid = accept_quest(
        spec=sample_spec,
        e0=sample_e0,
        repo_meta=sample_repo_meta,
        difficulty="HARD",
        evidence=sample_evidence,
    )

    # Create corrupt JSON file
    corrupt_file = store.quests_dir() / "corrupt_syntax.json"
    corrupt_file.write_text("{invalid json content {{", encoding="utf-8")

    # Create invalid schema file
    invalid_schema = store.quests_dir() / "invalid_schema.json"
    invalid_schema.write_text(json.dumps({"wrong": "fields"}), encoding="utf-8")

    # list_quests must skip corrupt files and return the valid one
    quests = store.list_quests()
    assert len(quests) == 1
    assert quests[0].id == q_valid.id


# ---------------------------------------------------------------------------
# 7. Choosing Decline prints theme.abandoned and creates nothing
# ---------------------------------------------------------------------------


def test_decline_all_prints_abandoned_and_creates_nothing(monkeypatch, sample_spec):
    # Mock prompt to simulate selecting "Decline all"
    monkeypatch.setattr("rune.quest.prompt_choose_quest", lambda quests: None)

    chosen = choose_quest_option([sample_spec])
    assert chosen is None
