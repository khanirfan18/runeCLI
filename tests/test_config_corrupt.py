"""Tests verifying that empty or corrupt config.json does not crash the CLI."""

import json
import os
import sys
import pytest
from typer.testing import CliRunner

from rune import store
from rune.cli import app
from rune.credentials import load_saved_credentials


@pytest.mark.parametrize(
    "corrupt_content,expect_warning",
    [
        ("", True),                           # 0-byte file
        ("invalid json {{{", True),           # Invalid JSON
        ("[1, 2, 3]", True),                  # JSON that is a list
        ('{"credentials": "not-dict"}', True),# Wrong type for credentials
        ('{"credentials": {"github_token": 123}}', False), # Wrong type for token value (ignored or handled)
        ('{"credentials": {}}', False),       # Missing keys (valid empty credentials)
    ],
)
def test_corrupt_config_load_saved_credentials(tmp_path, monkeypatch, capsys, corrupt_content, expect_warning):
    """Test load_saved_credentials handles corrupt config without crashing."""
    monkeypatch.setenv("RUNE_HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store.ensure_dirs()

    cfg_file = store.config_path()
    cfg_file.write_text(corrupt_content, encoding="utf-8")

    # Must not raise StoreError or any exception
    load_saved_credentials()

    captured = capsys.readouterr()
    if expect_warning:
        assert "Your config file could not be read, so Rune will ask for your keys again." in captured.err
    assert "GITHUB_TOKEN" not in os.environ
    assert "GEMINI_API_KEY" not in os.environ


@pytest.mark.parametrize(
    "corrupt_content",
    [
        "",
        "invalid json {{{",
        "[1, 2, 3]",
        '{"credentials": "not-dict"}',
    ],
)
def test_cli_commands_survive_corrupt_config(tmp_path, monkeypatch, corrupt_content):
    """Confirm rune, rune status, and rune refresh survive corrupt config without a traceback."""
    monkeypatch.setenv("RUNE_HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store.ensure_dirs()

    store.config_path().write_text(corrupt_content, encoding="utf-8")

    runner = CliRunner()

    # status command survives without traceback
    status_res = runner.invoke(app, ["status"])
    assert status_res.exit_code == 0
    assert "Traceback" not in status_res.output

    # refresh command survives without traceback
    refresh_res = runner.invoke(app, ["refresh"])
    assert refresh_res.exit_code == 0
    assert "Traceback" not in refresh_res.output

    # rune bare command survives without traceback (exits 1 due to no TTY)
    bare_res = runner.invoke(app, [])
    assert bare_res.exit_code == 1
    assert "Traceback" not in bare_res.output
