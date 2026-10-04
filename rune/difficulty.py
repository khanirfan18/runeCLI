"""Authoritative quest difficulty definitions for RuneCLI.

The only place these values exist:
EASY   = 60 min / 100 XP
NORMAL = 180 min / 150 XP
HARD   = 360 min / 250 XP
EPIC   = 540 min / 400 XP
"""

from enum import Enum
from typing import NamedTuple


class Difficulty(str, Enum):
    """Quest difficulty tiers."""

    EASY = "EASY"
    NORMAL = "NORMAL"
    HARD = "HARD"
    EPIC = "EPIC"


class DifficultyInfo(NamedTuple):
    """Duration in minutes and reward in XP for a difficulty tier."""

    minutes: int
    xp: int


DIFFICULTY_LOOKUP: dict[Difficulty, DifficultyInfo] = {
    Difficulty.EASY: DifficultyInfo(minutes=60, xp=100),
    Difficulty.NORMAL: DifficultyInfo(minutes=180, xp=150),
    Difficulty.HARD: DifficultyInfo(minutes=360, xp=250),
    Difficulty.EPIC: DifficultyInfo(minutes=540, xp=400),
}

# Aliases for convenience
DIFFICULTIES = DIFFICULTY_LOOKUP
DIFFICULTY_TABLE = DIFFICULTY_LOOKUP


def get_difficulty(key: Difficulty | str) -> DifficultyInfo:
    """Return DifficultyInfo for a Difficulty enum or case-insensitive string name."""
    if isinstance(key, str):
        try:
            diff = Difficulty(key.upper())
        except ValueError as exc:
            raise KeyError(f"Unknown difficulty: {key}") from exc
        return DIFFICULTY_LOOKUP[diff]
    return DIFFICULTY_LOOKUP[key]
