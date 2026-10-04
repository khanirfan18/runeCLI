"""Stale setup recovery for RuneCLI."""

import sys
from datetime import datetime, timezone

from rune import store
from rune.models import Quest
from rune.runtime import run_started_at as get_run_started_at


def recover_stale_setups(run_started_at: datetime | None = None) -> list[Quest]:
    """Scan all quests and mark any SETUP_PENDING quest created before run_started_at as SETUP_FAILED.

    Preserves all other fields.
    """
    if run_started_at is None:
        try:
            run_started_at = get_run_started_at()
        except RuntimeError:
            return []

    if run_started_at.tzinfo is None:
        run_started_at = run_started_at.replace(tzinfo=timezone.utc)

    recovered: list[Quest] = []
    quests = store.list_quests()
    for quest in quests:
        if quest.status != "SETUP_PENDING":
            continue

        if quest.created_at is None:
            sys.stderr.write(f"Warning: Quest {quest.id} has no created_at, skipping recovery.\n")
            continue

        created_at = quest.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        if created_at < run_started_at:
            quest.status = "SETUP_FAILED"
            quest.failure_reason = "abandoned during setup"
            quest.claimed_at = None
            quest.expires_at = None
            store.save_quest(quest)
            recovered.append(quest)

    return recovered
