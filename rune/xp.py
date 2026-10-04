"""XP calculations, RuneScape level curve progression, and player cache management."""

import math
from datetime import datetime, timezone
from typing import Any

from rune import store

# Precompute level thresholds for RuneScape curve (levels 1..99)
_THRESHOLDS: dict[int, int] = {1: 0}
_POINTS = 0
for _lvl in range(1, 99):
    _POINTS += math.floor(_lvl + 300 * (2 ** (_lvl / 7.0)))
    _THRESHOLDS[_lvl + 1] = math.floor(_POINTS / 4.0)


def rune_level(xp: int) -> int:
    """Calculate the RuneScape level for a given amount of XP (capped at 99).

    Formula:
    points=0; thresholds={1:0}; for lvl in 1..98:
      points += floor(lvl + 300*2**(lvl/7)); thresholds[lvl+1] = floor(points/4).
    Capped at 99.
    """
    if xp < 0:
        return 1
    current_lvl = 1
    for lvl in range(1, 100):
        if xp >= _THRESHOLDS[lvl]:
            current_lvl = lvl
        else:
            break
    return min(99, current_lvl)


def compute_total_xp() -> int:
    """Sum quest.xp over quests with status COMPLETED and xp_awarded=true.

    Computed authoritatively from durable quest records.
    """
    quests = store.list_quests()
    total = 0
    for q in quests:
        if q.status == "COMPLETED" and q.xp_awarded:
            total += q.xp
    return total


def sync_player_cache(now: datetime | None = None) -> dict[str, Any]:
    """Recompute stats from quest records and rewrite player.json cache.

    player.json is only a cache: {total_xp, level, updated_at}.
    """
    total_xp = compute_total_xp()
    level = rune_level(total_xp)

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    cache_data = {
        "total_xp": total_xp,
        "level": level,
        "updated_at": now.isoformat(),
    }
    store.ensure_dirs()
    try:
        store.atomic_write_json(store.player_path(), cache_data)
    except Exception:
        # Cache failure is non-fatal
        pass
    return cache_data


def get_player_stats() -> tuple[int, int]:
    """Return (total_xp, level) from player.json or rebuild from quest records.

    If player.json is missing, stale, or corrupt, recompute from quest records
    and rewrite it.
    """
    actual_xp = compute_total_xp()
    expected_level = rune_level(actual_xp)

    try:
        data = store.read_json(store.player_path())
        if (
            isinstance(data, dict)
            and "total_xp" in data
            and "level" in data
            and data["total_xp"] == actual_xp
            and data["level"] == expected_level
        ):
            return int(data["total_xp"]), int(data["level"])
    except Exception:
        pass

    # Missing, stale, or corrupt: recompute and rewrite cache
    cache = sync_player_cache()
    return cache["total_xp"], cache["level"]
