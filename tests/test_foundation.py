"""Tests for RuneCLI foundation, theme, storage, and UI utilities."""

import io
import json
import os
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from rune import runtime, store, theme, ui
from rune.cli import app


def test_sanitize_ansi_and_osc():
    # ANSI CSI escape sequences
    text_csi = "\x1b[31;1mRed Bold\x1b[0m Normal \x1b[2K"
    assert ui.sanitize(text_csi) == "Red Bold Normal "

    # ANSI OSC escape sequences
    text_osc = "\x1b]0;Window Title\x07Clean \x1b]8;;https://example.com\x1b\\Link\x1b]8;;\x1b\\"
    assert ui.sanitize(text_osc) == "Clean Link"


def test_sanitize_control_chars_and_tabs():
    # Tabs converted to 4 spaces, newlines kept, other control characters removed
    raw = "Line 1\tIndent\x00\x07\x08\x1f\nLine 2\r\nLine 3\x7f"
    sanitized = ui.sanitize(raw)
    assert sanitized == "Line 1    Indent\nLine 2\nLine 3"
    assert "\t" not in sanitized
    assert "\x00" not in sanitized
    assert "\x07" not in sanitized
    assert "\r" not in sanitized
    assert "\x7f" not in sanitized


def test_sanitize_bidi_and_zero_width():
    # Bidi controls: U+202A-U+202E, U+2066-U+2069
    # Zero-width: U+200B-U+200F, U+FEFF, U+2060
    bidi_sample = "Safe\u202a\u202b\u202c\u202d\u202eText\u2066\u2067\u2068\u2069"
    zw_sample = "Zero\u200b\u200c\u200d\u200e\u200f\ufeff\u2060Width"
    assert ui.sanitize(bidi_sample) == "SafeText"
    assert ui.sanitize(zw_sample) == "ZeroWidth"


def test_truncate_never_exceeds_columns():
    long_text = "This is a very long text that must be truncated to fit within eighty columns." * 2
    truncated_80 = ui.truncate(long_text, 80)
    assert len(truncated_80) <= 80
    assert truncated_80.endswith("…")

    truncated_20 = ui.truncate(long_text, 20)
    assert len(truncated_20) == 20
    assert truncated_20.endswith("…")

    # Multiline text collapsed to single line
    multiline = "First line\nSecond line\nThird line"
    truncated_multi = ui.truncate(multiline, 25)
    assert "\n" not in truncated_multi
    assert len(truncated_multi) <= 25

    # Short text remains untouched
    assert ui.truncate("Short", 80) == "Short"


def test_wrap_preserves_paragraphs_and_breaks_long_tokens():
    # Long unbroken token
    long_token = "A" * 120
    wrapped_tokens = ui.wrap(long_token, 80)
    assert len(wrapped_tokens) == 2
    assert wrapped_tokens[0] == "A" * 80
    assert wrapped_tokens[1] == "A" * 40
    for line in wrapped_tokens:
        assert len(line) <= 80

    # Paragraphs separated by blank line
    doc = "First paragraph with some text.\n\nSecond paragraph following an empty line."
    wrapped_doc = ui.wrap(doc, 80)
    assert "" in wrapped_doc  # Blank line preserved between paragraphs
    assert wrapped_doc == [
        "First paragraph with some text.",
        "",
        "Second paragraph following an empty line.",
    ]


def test_redact_secrets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_super_secret_token_12345")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_secret_key_abcde")

    msg = "Call to GitHub using ghp_super_secret_token_12345 and Gemini key gemini_secret_key_abcde failed."
    redacted = ui.redact(msg)
    assert "ghp_super_secret_token_12345" not in redacted
    assert "gemini_secret_key_abcde" not in redacted
    assert redacted == "Call to GitHub using *** and Gemini key *** failed."


def test_atomic_write_json_leaves_no_temp_and_preserves_old(tmp_path):
    target = tmp_path / "data.json"
    initial_data = {"preserved": True, "count": 1}
    store.atomic_write_json(target, initial_data)
    assert target.exists()
    assert store.read_json(target) == initial_data

    # Attempt to write unserializable object
    bad_data = {"invalid": {1, 2, 3}}  # sets are not JSON serializable
    with pytest.raises(TypeError):
        store.atomic_write_json(target, bad_data)

    # Old file remains intact
    assert target.exists()
    assert store.read_json(target) == initial_data

    # No leftover temporary files
    files = list(tmp_path.iterdir())
    assert files == [target]


def test_read_json_corrupt_raises_store_error(tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("invalid json content {{{", encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.read_json(target)

    # Missing returns None
    missing = tmp_path / "missing.json"
    assert store.read_json(missing) is None


def test_run_started_at_timezone_aware():
    first = runtime.init_run()
    assert first.tzinfo is not None
    assert first.tzinfo == timezone.utc

    second = runtime.init_run()
    assert first == second
    assert runtime.run_started_at() == first


def test_run_started_at_uninitialized_raises():
    with patch.object(runtime, "_RUN_STARTED_AT", None):
        with pytest.raises(RuntimeError, match="init_run has not been called"):
            runtime.run_started_at()


def test_typer_app_cli_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNE_HOME", str(tmp_path / ".rune"))
    runner = CliRunner()

    # --help works
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "status" in help_result.output
    assert "refresh" in help_result.output

    # Exactly status and refresh subcommands
    command_names = [cmd.name for cmd in app.registered_commands]
    assert sorted(command_names) == ["refresh", "status"]

    # Bare invocation exits 0 and prints banner and placeholder
    bare_result = runner.invoke(app, [])
    assert bare_result.exit_code == 0
    assert theme.BANNER in bare_result.output
    assert "flow not wired yet" in bare_result.output

    # Subcommand status exits 0
    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0
    assert "not wired yet" in status_result.output

    # Subcommand refresh exits 0
    refresh_result = runner.invoke(app, ["refresh"])
    assert refresh_result.exit_code == 0
    assert "not wired yet" in refresh_result.output


def test_external_text_renders_literally():
    console = ui.get_console()
    sample = "[red]x[/red] and :smile:"
    rendered_text = ui.ext(sample)

    buf = io.StringIO()
    test_console = Console(file=buf, width=console.width, markup=False, emoji=False, highlight=False)
    test_console.print(rendered_text)

    output = buf.getvalue()
    assert "[red]x[/red]" in output
    assert ":smile:" in output


def test_store_directory_structure(tmp_path, monkeypatch):
    home = tmp_path / "custom_rune"
    monkeypatch.setenv("RUNE_HOME", str(home))

    assert store.rune_home() == home
    assert store.quests_dir() == home / "quests"
    assert store.workspaces_dir() == home / "workspaces"
    assert store.cache_dir() == home / "cache"
    assert store.config_path() == home / "config.json"
    assert store.player_path() == home / "player.json"

    store.ensure_dirs()
    assert (home / "quests").is_dir()
    assert (home / "workspaces").is_dir()
    assert (home / "cache").is_dir()
    assert (home / "config.json").is_file()

    cfg = store.read_json(store.config_path())
    assert cfg == {"version": 1}


def test_prompts_require_tty(monkeypatch):
    from rune import prompts
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(RuntimeError, match="Interactive prompt requires a TTY stdin."):
        prompts.ask_text("Enter name")

    with pytest.raises(RuntimeError, match="Interactive prompt requires a TTY stdin."):
        prompts.ask_select("Select difficulty", [("Novice", "EASY")])
