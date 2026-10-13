"""Tests for --version and -V CLI options."""

from unittest.mock import patch
import importlib.metadata
from typer.testing import CliRunner
from rune.cli import app


def test_version_flag_success():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().startswith("runecli ")
    assert "unknown" not in result.output or "0.1." in result.output


def test_version_short_flag_V():
    runner = CliRunner()
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert result.output.strip().startswith("runecli ")


def test_version_missing_metadata():
    runner = CliRunner()
    with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == "runecli unknown"

        result_short = runner.invoke(app, ["-V"])
        assert result_short.exit_code == 0
        assert result_short.output.strip() == "runecli unknown"


def test_small_v_is_not_version():
    runner = CliRunner()
    result = runner.invoke(app, ["-v"])
    assert result.exit_code != 0
    assert "No such option: -v" in result.output
