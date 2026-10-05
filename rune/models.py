"""Domain models for RuneCLI issue selection, repository metadata, quest inputs, and AI framing.

Contains IssueRef, RepoMeta, E0, and Gemma AI output models.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from rune.ui import sanitize


class IssueRef(BaseModel):
    """Reference to a candidate GitHub issue returned from search."""

    number: int
    title: str
    body: str = ""
    url: str
    base_repo: str
    assignee_logins: list[str] = Field(default_factory=list)

    @field_validator("body", mode="before")
    @classmethod
    def _coerce_body(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    def label(self) -> str:
        """Return raw label string in 'owner/repo #n title' format."""
        return f"{self.base_repo} #{self.number} {self.title}"


class RepoMeta(BaseModel):
    """Metadata and access permissions for a target repository."""

    base_repo: str
    base_repo_url: str
    default_branch: str
    archived: bool
    allow_forking: bool = True
    push: bool
    route: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.route:
            self.route = "direct" if self.push else "fork"


class E0(BaseModel):
    """Normalized evidence artifact E0 extracted from the selected issue.

    Title is capped at 300 chars, body is capped at 4000 chars,
    and truncated is True if either field was clipped. Text is sanitized.
    The original issue is not modified.
    """

    number: int
    title: str
    body: str
    url: str
    truncated: bool = False

    @classmethod
    def from_issue(cls, issue: IssueRef) -> "E0":
        """Build E0 from an IssueRef without modifying the original issue."""
        clean_title = sanitize(issue.title)
        clean_body = sanitize(issue.body)

        clipped = False
        if len(clean_title) > 300:
            clean_title = clean_title[:300]
            clipped = True

        if len(clean_body) > 4000:
            clean_body = clean_body[:4000]
            clipped = True

        return cls(
            number=issue.number,
            title=clean_title,
            body=clean_body,
            url=issue.url,
            truncated=clipped,
        )


class AcceptanceCriterion(BaseModel):
    """A single verifiable criterion for completing a quest."""

    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str = Field(..., max_length=300)
    evidence_ids: list[str] = Field(..., min_length=1)


class QuestFraming(BaseModel):
    """A grounded quest proposal generated from repository evidence."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=120)
    summary: str = Field(..., max_length=600)
    acceptance_criteria: list[AcceptanceCriterion] = Field(..., min_length=1, max_length=6)
    evidence_ids: list[str] = Field(..., min_length=1)
    unknowns: list[str] = Field(default_factory=list)


class GemmaOutput(BaseModel):
    """Top-level JSON contract for Gemma 4 quest framing generation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["OK", "INSUFFICIENT_EVIDENCE"]
    quests: list[QuestFraming] = Field(default_factory=list)
    reason: str | None = None

    def check_evidence_ids(self, allowed_ids: set[str] | list[str]) -> None:
        """Validate that all referenced evidence IDs exist in the allowed set."""
        allowed_set = set(allowed_ids)
        for q_idx, q in enumerate(self.quests):
            for eid in q.evidence_ids:
                if eid not in allowed_set:
                    raise ValueError(f"Unknown evidence_id '{eid}' in quest {q_idx}")
            for ac in q.acceptance_criteria:
                for eid in ac.evidence_ids:
                    if eid not in allowed_set:
                        raise ValueError(f"Unknown evidence_id '{eid}' in criterion {ac.id}")

    @model_validator(mode="after")
    def validate_invariants(self, info: ValidationInfo) -> "GemmaOutput":
        if self.status == "OK":
            if not (1 <= len(self.quests) <= 3):
                raise ValueError(
                    f"Status OK requires between 1 and 3 quests, got {len(self.quests)}"
                )
            # Successful responses do not expose a reason to the application.
            # Models sometimes add a harmless explanation despite the schema.
            if self.reason is not None:
                self.reason = None
        elif self.status == "INSUFFICIENT_EVIDENCE":
            if len(self.quests) != 0:
                raise ValueError(
                    f"Status INSUFFICIENT_EVIDENCE must have quests=[], got {len(self.quests)}"
                )
            if self.reason is None or not self.reason.strip():
                raise ValueError(
                    "Status INSUFFICIENT_EVIDENCE requires a non-empty reason string"
                )

        if info.context and "allowed_evidence_ids" in info.context:
            self.check_evidence_ids(info.context["allowed_evidence_ids"])

        return self


class QuestIssue(BaseModel):
    """Target issue details stored in the durable quest record."""

    model_config = ConfigDict(extra="forbid")

    number: int
    title: str
    url: str


class QuestPR(BaseModel):
    """Pull request reference for completion verification."""

    model_config = ConfigDict(extra="forbid")

    number: int
    url: str
    state: str
    merged: bool = False


class QuestSnippet(BaseModel):
    """Stored cited evidence snippet in the durable quest record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    start_line: int
    end_line: int
    snippet: str


QuestStatus = Literal["SETUP_PENDING", "SETUP_FAILED", "ACTIVE", "EXPIRED", "COMPLETED"]


class Quest(BaseModel):
    """Durable quest record persisted as JSON under RUNE_HOME/quests/<id>.json."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_id: str
    status: QuestStatus = "SETUP_PENDING"
    created_at: datetime
    claimed_at: datetime | None = None
    expires_at: datetime | None = None
    completed_at: datetime | None = None
    expired_at: datetime | None = None
    failure_reason: str | None = None

    issue: QuestIssue
    base_repo: str
    base_repo_url: str
    base_branch: str
    route: Literal["direct", "fork"]
    head_repo: str | None = None
    head_owner: str | None = None
    head_branch: str | None = None

    difficulty: str
    xp: int
    duration_seconds: int
    xp_awarded: bool = False
    workspace_path: str | None = None
    pr: QuestPR | None = None

    spec: QuestFraming
    snippets: list[QuestSnippet] = Field(default_factory=list)

    @field_validator("created_at", "claimed_at", "expires_at", "completed_at", "expired_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
