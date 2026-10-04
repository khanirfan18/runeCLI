"""Filesystem storage and local state management for RuneCLI."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StoreError(Exception):
    """Controlled exception for storage failures."""
    pass


def rune_home() -> Path:
    """Return the root path for Rune local state (RUNE_HOME env or ~/.rune)."""
    env_home = os.environ.get("RUNE_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".rune").resolve()


def quests_dir() -> Path:
    """Return the quests directory under RUNE_HOME."""
    return rune_home() / "quests"


def workspaces_dir() -> Path:
    """Return the workspaces directory under RUNE_HOME."""
    return rune_home() / "workspaces"


def cache_dir() -> Path:
    """Return the repository analysis cache directory under RUNE_HOME."""
    return rune_home() / "cache"


def config_path() -> Path:
    """Return the path to config.json under RUNE_HOME."""
    return rune_home() / "config.json"


def player_path() -> Path:
    """Return the path to player.json under RUNE_HOME."""
    return rune_home() / "player.json"


def ensure_dirs() -> None:
    """Create directory structure under RUNE_HOME and initialize config.json if missing."""
    for d in (rune_home(), quests_dir(), workspaces_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True)
    cfg = config_path()
    if not cfg.exists():
        atomic_write_json(cfg, {"version": 1})


def atomic_write_json(path: Path | str, data: Any) -> None:
    """Atomically write JSON data to a target path via a temporary file in the same directory."""
    target_path = Path(path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Serialize first so serialization failure never touches the filesystem
    content = json.dumps(data, indent=2)

    temp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=target_path.parent, delete=False, encoding="utf-8") as f:
            temp_file = Path(f.name)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, target_path)
        temp_file = None
    finally:
        if temp_file is not None and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def read_json(path: Path | str) -> Any | None:
    """Read JSON from path. Return None if missing, or raise StoreError if corrupt."""
    target_path = Path(path).resolve()
    if not target_path.exists():
        return None
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise StoreError(f"Failed to read JSON at {target_path}: {exc}") from exc


def save_quest(quest: Any) -> Path:
    """Atomically persist a quest record under RUNE_HOME/quests/<id>.json."""
    ensure_dirs()
    target_path = quests_dir() / f"{quest.id}.json"
    atomic_write_json(target_path, quest.model_dump(mode="json"))
    return target_path


def load_quest(quest_id: str) -> Any | None:
    """Load a quest record by full UUID or 8-char display ID. Return None if not found."""
    from rune.models import Quest

    q_dir = quests_dir()
    if not q_dir.exists():
        return None

    target_path = (
        q_dir / f"{quest_id}.json"
        if not quest_id.endswith(".json")
        else q_dir / quest_id
    )
    if not target_path.exists():
        matches = [p for p in q_dir.glob("*.json") if p.stem.startswith(quest_id)]
        if matches:
            target_path = matches[0]
        else:
            return None

    data = read_json(target_path)
    if data is None:
        return None
    return Quest.model_validate(data)


def list_quests() -> list[Any]:
    """List all stored quests, skipping corrupt files and reporting them."""
    import sys
    from rune.models import Quest

    q_dir = quests_dir()
    if not q_dir.exists():
        return []

    quests: list[Any] = []
    for path in sorted(q_dir.glob("*.json")):
        try:
            data = read_json(path)
            if data is not None:
                quests.append(Quest.model_validate(data))
        except Exception as exc:
            sys.stderr.write(f"Warning: Corrupt quest file {path.name}: {exc}\n")

    return quests


def get_quests_by_status(status: str) -> list[Any]:
    """Return all stored quests matching a given status."""
    return [q for q in list_quests() if q.status == status]

