"""Pytest fixtures and configuration for RuneCLI test suite."""

import subprocess
import sys
from unittest.mock import MagicMock
import pytest

_original_popen = subprocess.Popen


class EditorLaunchRecorder:
    """Records editor process launches without spawning real OS processes."""

    def __init__(self):
        self.launches: list[dict] = []

    def record(self, args, kwargs, proc):
        self.launches.append({"args": args, "kwargs": kwargs, "proc": proc})

    def clear(self):
        self.launches.clear()


@pytest.fixture(autouse=True)
def prevent_real_editor_launch(request, monkeypatch):
    """Autouse fixture that prevents any test from spawning a real editor (VS Code, Cursor).

    Replaces process launches originating from rune.editor with a recorder mock.
    Tests requiring the raw launcher can opt out with:
        @pytest.mark.allow_real_editor_launch
    """
    if "allow_real_editor_launch" in request.keywords:
        return None

    recorder = EditorLaunchRecorder()

    def intercepted_popen(*args, **kwargs):
        # Check if caller is inside rune.editor
        f = sys._getframe(1)
        is_editor_call = False
        while f:
            if f.f_globals.get("__name__") == "rune.editor":
                is_editor_call = True
                break
            f = f.f_back

        if is_editor_call:
            fake_proc = MagicMock()
            fake_proc.pid = 99999
            fake_proc.returncode = 0
            fake_proc.poll.return_value = 0
            fake_proc.wait.return_value = 0
            fake_proc.communicate.return_value = ("", "")
            recorder.record(args, kwargs, fake_proc)
            return fake_proc

        return _original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", intercepted_popen)
    return recorder
