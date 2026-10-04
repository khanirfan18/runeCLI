"""Runtime state tracking for RuneCLI."""

from datetime import datetime, timezone

_RUN_STARTED_AT: datetime | None = None


def init_run() -> datetime:
    """Initialize the module-level RUN_STARTED_AT timestamp on first call."""
    global _RUN_STARTED_AT
    if _RUN_STARTED_AT is None:
        _RUN_STARTED_AT = datetime.now(timezone.utc)
    return _RUN_STARTED_AT


def run_started_at() -> datetime:
    """Return the RUN_STARTED_AT timestamp, or raise RuntimeError if uninitialized."""
    if _RUN_STARTED_AT is None:
        raise RuntimeError("init_run has not been called")
    return _RUN_STARTED_AT
