"""Tests for filesystem permissions and credential security."""

import os
import stat
from pathlib import Path
from unittest.mock import patch
import pytest

from rune import store


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission modes do not apply on Windows")
def test_temp_file_mode_before_replace(tmp_path, monkeypatch):
    """Test mode of the temporary file used in atomic_write_json before os.replace."""
    monkeypatch.setenv("RUNE_HOME", str(tmp_path))
    store.ensure_dirs()

    captured_modes = []
    original_replace = os.replace

    def spy_replace(src, dst):
        src_path = Path(src)
        if src_path.exists():
            mode = src_path.stat().st_mode & 0o777
            captured_modes.append(mode)
        return original_replace(src, dst)

    with patch("os.replace", side_effect=spy_replace):
        target = store.config_path()
        store.atomic_write_json(target, {"test": True})

    assert len(captured_modes) == 1
    # Check whether the temp file already has mode 0o600 before replace
    assert captured_modes[0] == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission modes do not apply on Windows")
def test_rune_home_and_config_permissions(tmp_path, monkeypatch):
    """RUNE_HOME must be 0700 and initial config.json must be 0600."""
    rune_dir = tmp_path / "rune_test_home"
    monkeypatch.setenv("RUNE_HOME", str(rune_dir))

    store.ensure_dirs()

    # RUNE_HOME must be 0700
    home_mode = rune_dir.stat().st_mode & 0o777
    assert home_mode == 0o700

    # Initial config.json must be 0600
    cfg = store.config_path()
    assert cfg.exists()
    cfg_mode = cfg.stat().st_mode & 0o777
    assert cfg_mode == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission modes do not apply on Windows")
def test_existing_rune_home_chmod_to_0700(tmp_path, monkeypatch):
    """If RUNE_HOME already existed with loose permissions (e.g. 0755), ensure_dirs chmods it to 0700."""
    rune_dir = tmp_path / "preexisting_home"
    rune_dir.mkdir(mode=0o755)
    monkeypatch.setenv("RUNE_HOME", str(rune_dir))

    store.ensure_dirs()

    home_mode = rune_dir.stat().st_mode & 0o777
    assert home_mode == 0o700
