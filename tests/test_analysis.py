"""Gate tests for read-only analysis clone, limits, secret filtering, and evidence extraction."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rune import store
from rune.analysis import (
    EXACT_SECRET_REGEX,
    IGNORED_DIRS,
    MAX_EVIDENCE_SNIPPETS,
    MAX_FILES_SCANNED,
    MAX_FILE_SIZE,
    MAX_LINES_PER_SNIPPET,
    MAX_TOTAL_EVIDENCE_CHARS,
    SECRET_FILE_PATTERNS,
    build_clone_cmd,
    clone_repo,
    contains_secret,
    extract_e0_tokens,
    extract_evidence,
    is_secret_file,
    prepare_cache_dir,
    validate_cache_target,
)
from rune.models import E0, RepoMeta


# ---------------------------------------------------------------------------
# 1. Determinism and Ordering
# ---------------------------------------------------------------------------


def test_evidence_determinism_and_ordering(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create various source files
    (repo / "src").mkdir()
    (repo / "src" / "parser.py").write_text(
        "class Parser:\n    def parse_tokens(self):\n        pass\n",
        encoding="utf-8",
    )
    (repo / "src" / "lexer.py").write_text(
        "class Lexer:\n    def tokenize_input(self):\n        pass\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_parser.py").write_text(
        "def test_parser():\n    assert True\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Project\nParser and lexer documentation.\n",
        encoding="utf-8",
    )

    e0 = E0(
        number=1,
        title="Fix parser tokens issue",
        body="The parser fails when handling unexpected tokens in input stream.",
        url="https://github.com/owner/repo/issues/1",
        truncated=False,
    )

    # Run extraction twice on the same tree
    run1 = extract_evidence(repo, e0)
    run2 = extract_evidence(repo, e0)

    # Identical evidence
    assert len(run1) == len(run2)
    assert run1 == run2

    # Ordering must be score DESC, then path ASC
    for i in range(len(run1) - 1):
        curr = run1[i]
        nxt = run1[i + 1]
        assert (curr.score > nxt.score) or (
            curr.score == nxt.score and curr.path < nxt.path
        )


# ---------------------------------------------------------------------------
# 2. Resource Caps
# ---------------------------------------------------------------------------


def test_caps_file_size(tmp_path):
    repo = tmp_path / "repo_size"
    repo.mkdir()

    # File exceeding 200KB limit
    large_file = repo / "large.py"
    large_file.write_text("token " * 50000, encoding="utf-8")  # ~300KB
    assert large_file.stat().st_size > MAX_FILE_SIZE

    # Normal file
    normal_file = repo / "normal.py"
    normal_file.write_text("token parser = 1\n", encoding="utf-8")

    e0 = E0(number=1, title="token parser", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    paths = [e.path for e in evidence]
    assert "large.py" not in paths
    assert "normal.py" in paths


def test_caps_max_snippets_and_ids(tmp_path):
    repo = tmp_path / "repo_max_snippets"
    repo.mkdir()

    # Create 15 matching files
    for i in range(15):
        (repo / f"file_{i:02d}.py").write_text(
            f"# File {i}\ntoken match in file\n", encoding="utf-8"
        )

    e0 = E0(number=1, title="token match", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    # Exactly 8 snippets collected
    assert len(evidence) == MAX_EVIDENCE_SNIPPETS
    assert [e.id for e in evidence] == ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]


def test_caps_max_lines_per_snippet_and_window(tmp_path):
    repo = tmp_path / "repo_lines"
    repo.mkdir()

    # 120 lines, token hit at line 40
    lines = [f"# line {i}" for i in range(1, 121)]
    lines[39] = "token_target = 42"  # line 40 (1-indexed)
    (repo / "source.py").write_text("\n".join(lines), encoding="utf-8")

    e0 = E0(number=1, title="token_target", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    assert len(evidence) == 1
    snip = evidence[0]
    # Starts 10 lines before hit line 40 -> line 30
    assert snip.start_line == 30
    assert snip.end_line - snip.start_line + 1 <= MAX_LINES_PER_SNIPPET
    assert len(snip.snippet.splitlines()) <= MAX_LINES_PER_SNIPPET


def test_caps_total_chars_12000_and_line_truncation(tmp_path):
    repo = tmp_path / "repo_chars"
    repo.mkdir()

    # Create files each having ~3000 chars of matching lines
    for i in range(6):
        content = "\n".join([f"token line {j:03d} " + ("x" * 50) for j in range(50)])
        (repo / f"file_{i}.py").write_text(content, encoding="utf-8")

    e0 = E0(number=1, title="token match", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    total_chars = sum(len(e.snippet) for e in evidence)
    assert total_chars <= MAX_TOTAL_EVIDENCE_CHARS

    # The last snippet must be truncated cleanly to whole lines
    last_snippet = evidence[-1]
    assert "\n" in last_snippet.snippet


def test_caps_files_scanned(tmp_path, monkeypatch):
    repo = tmp_path / "repo_scanned"
    repo.mkdir()

    # Create 50 files
    for i in range(50):
        (repo / f"f_{i:03d}.py").write_text("token content\n", encoding="utf-8")

    # Lower scan limit to 10
    monkeypatch.setattr("rune.analysis.MAX_FILES_SCANNED", 10)

    e0 = E0(number=1, title="token", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    # We cannot collect more than 10 files
    assert len(evidence) <= 10


# ---------------------------------------------------------------------------
# 3. Secret Filtering
# ---------------------------------------------------------------------------


def test_secret_files_never_read(tmp_path):
    repo = tmp_path / "repo_secrets"
    repo.mkdir()

    secret_names = [
        ".env",
        ".env.local",
        "cert.pem",
        "server.key",
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "secrets.yaml",
        ".npmrc",
        ".pypirc",
        ".netrc",
    ]

    for name in secret_names:
        (repo / name).write_text("token keyword in secret file\n", encoding="utf-8")

    # Non-secret matching file
    (repo / "main.py").write_text("token keyword in clean file\n", encoding="utf-8")

    e0 = E0(number=1, title="token keyword", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    paths = [e.path for e in evidence]
    for s in secret_names:
        assert s not in paths
    assert "main.py" in paths


def test_exact_secret_regex_rejects_snippet(tmp_path):
    repo = tmp_path / "repo_secret_regex"
    repo.mkdir()

    # Exact regex matching files
    (repo / "bad1.py").write_text("api_key = 'secret_val'\ntoken keyword\n", encoding="utf-8")
    (repo / "bad2.py").write_text("password: '12345'\ntoken keyword\n", encoding="utf-8")
    (repo / "bad3.py").write_text("secret := 'shh'\ntoken keyword\n", encoding="utf-8")
    (repo / "good.py").write_text("normal_var = 'value'\ntoken keyword\n", encoding="utf-8")

    e0 = E0(number=1, title="token keyword", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    paths = [e.path for e in evidence]
    assert "bad1.py" not in paths
    assert "bad2.py" not in paths
    assert "bad3.py" not in paths
    assert "good.py" in paths


def test_content_patterns_and_task_list(tmp_path):
    repo = tmp_path / "repo_patterns"
    repo.mkdir()

    # AWS key
    (repo / "aws.py").write_text("AKIAIOSFODNN7EXAMPLE\ntoken keyword\n", encoding="utf-8")
    # GitHub PAT
    (repo / "pat1.py").write_text("ghp_1234567890abcdef\ntoken keyword\n", encoding="utf-8")
    (repo / "pat2.py").write_text("github_pat_1234567890\ntoken keyword\n", encoding="utf-8")
    # OpenAI key (>= 20 chars after sk-)
    (repo / "oai.py").write_text("sk-12345678901234567890abcdef\ntoken keyword\n", encoding="utf-8")
    # Google API key
    (repo / "goog.py").write_text("AIzaSyD-sample-key-1234\ntoken keyword\n", encoding="utf-8")
    # Private keys
    (repo / "pk.py").write_text("-----BEGIN RSA PRIVATE KEY-----\ntoken keyword\n", encoding="utf-8")

    # "task-list" must NOT be rejected by sk-
    (repo / "tasks.py").write_text("process_task-list_items()\ntoken keyword\n", encoding="utf-8")

    e0 = E0(number=1, title="token keyword", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    paths = [e.path for e in evidence]
    assert "aws.py" not in paths
    assert "pat1.py" not in paths
    assert "pat2.py" not in paths
    assert "oai.py" not in paths
    assert "goog.py" not in paths
    assert "pk.py" not in paths
    # tasks.py is preserved
    assert "tasks.py" in paths


# ---------------------------------------------------------------------------
# 4. Symlinks and Ignored Dirs
# ---------------------------------------------------------------------------


def test_symlinks_and_ignored_dirs_pruned(tmp_path):
    repo = tmp_path / "repo_symlinks"
    repo.mkdir()

    # Regular matching file
    (repo / "app.py").write_text("token search keyword\n", encoding="utf-8")

    # Ignored directories
    for ig in IGNORED_DIRS:
        ig_dir = repo / ig
        ig_dir.mkdir(parents=True, exist_ok=True)
        (ig_dir / "hidden.py").write_text("token search keyword\n", encoding="utf-8")

    # Symlink within repo
    sym_file = repo / "sym_internal.py"
    try:
        sym_file.symlink_to(repo / "app.py")
    except OSError:
        pass

    # Symlink escaping root
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "external.py"
    outside_file.write_text("token search keyword\n", encoding="utf-8")

    sym_external = repo / "sym_external.py"
    try:
        sym_external.symlink_to(outside_file)
    except OSError:
        pass

    e0 = E0(number=1, title="token search keyword", body="", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    paths = [e.path for e in evidence]
    assert paths == ["app.py"]


# ---------------------------------------------------------------------------
# 5. Cache Deletion and Validation
# ---------------------------------------------------------------------------


def test_cache_validation_and_symlink_unlinking(tmp_path, monkeypatch):
    cache_root = tmp_path / ".rune" / "cache"
    cache_root.mkdir(parents=True)
    monkeypatch.setattr(store, "cache_dir", lambda: cache_root)

    # Valid name passes
    path = validate_cache_target("pallets", "click")
    assert path == cache_root / "pallets__click"

    # Traversal names refused
    with pytest.raises(ValueError, match="Invalid"):
        validate_cache_target("../evil", "click")
    with pytest.raises(ValueError, match="Invalid"):
        validate_cache_target("pallets", "../../root")

    # Symlink handling: unlinks ONLY the symlink, never touches external directory
    sensitive_outside = tmp_path / "sensitive_folder"
    sensitive_outside.mkdir()
    canary = sensitive_outside / "important.txt"
    canary.write_text("do not delete", encoding="utf-8")

    symlink_target = cache_root / "testowner__testrepo"
    symlink_target.symlink_to(sensitive_outside)

    # prepare_cache_dir must remove the symlink only
    prepared = prepare_cache_dir("testowner", "testrepo")
    assert not prepared.exists()
    assert not prepared.is_symlink()
    # Canary outside is untouched
    assert canary.exists()
    assert canary.read_text(encoding="utf-8") == "do not delete"

    # Directory deletion: removes only that target directory
    prepared.mkdir()
    (prepared / "temp_file.txt").write_text("cached data", encoding="utf-8")
    assert prepared.exists()

    re_prepared = prepare_cache_dir("testowner", "testrepo")
    assert not (re_prepared / "temp_file.txt").exists()


# ---------------------------------------------------------------------------
# 6. Clone Command Construction and Safety
# ---------------------------------------------------------------------------


def test_clone_argv_exact_and_safe(tmp_path):
    cmd = build_clone_cmd(
        default_branch="main",
        url="https://github.com/pallets/click.git",
        dest="/tmp/dest",
        empty_hooks_dir="/tmp/hooks",
    )

    assert isinstance(cmd, list)
    assert cmd[0] == "git"
    assert "-c" in cmd
    assert "core.hooksPath=/tmp/hooks" in cmd
    assert "protocol.file.allow=never" in cmd
    assert "core.fsmonitor=false" in cmd
    assert "clone" in cmd
    assert "--depth" in cmd and "1" in cmd
    assert "--no-tags" in cmd
    assert "--single-branch" in cmd
    assert "--no-recurse-submodules" in cmd
    assert "--branch" in cmd and "main" in cmd

    # "--" must immediately precede the URL
    url_idx = cmd.index("https://github.com/pallets/click.git")
    assert cmd[url_idx - 1] == "--"
    assert cmd[url_idx + 1] == "/tmp/dest"

    # Branch starting with "-" is rejected
    with pytest.raises(ValueError, match="Invalid default branch"):
        build_clone_cmd(
            default_branch="--upload-pack=exploit",
            url="https://github.com/owner/repo.git",
            dest="/tmp/dest",
            empty_hooks_dir="/tmp/hooks",
        )


def test_clone_repo_executes_safe_subprocess(tmp_path, monkeypatch):
    cache_root = tmp_path / ".rune" / "cache"
    cache_root.mkdir(parents=True)
    monkeypatch.setattr(store, "cache_dir", lambda: cache_root)

    captured_args = {}

    def mock_run(cmd, **kwargs):
        captured_args["cmd"] = cmd
        captured_args["kwargs"] = kwargs
        # Create destination dir to simulate git clone
        dest_dir = Path(cmd[-1])
        dest_dir.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    dest = clone_repo("pallets", "click", "main")
    assert dest.exists()

    cmd = captured_args["cmd"]
    kwargs = captured_args["kwargs"]

    assert kwargs.get("shell") is False
    assert kwargs.get("timeout") == 120
    assert kwargs.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"
    assert "ghp_" not in " ".join(cmd)
    assert "token" not in " ".join(cmd)


# ---------------------------------------------------------------------------
# 7. No Execution of Fixture Repo
# ---------------------------------------------------------------------------


def test_nothing_from_fixture_repo_executed(tmp_path):
    repo = tmp_path / "repo_malicious"
    repo.mkdir()

    marker = tmp_path / "executed_marker.txt"

    # Create various scripts that would create marker if executed
    (repo / "setup.py").write_text(
        f"import pathlib\npathlib.Path('{marker}').write_text('bad')\n", encoding="utf-8"
    )
    (repo / "Makefile").write_text(
        f"all:\n\ttouch {marker}\n", encoding="utf-8"
    )
    (repo / "install.sh").write_text(
        f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8"
    )

    try:
        os.chmod(repo / "install.sh", 0o777)
    except OSError:
        pass

    e0 = E0(number=1, title="setup install", body="help", url="https://...", truncated=False)
    evidence = extract_evidence(repo, e0)

    # Marker was never touched
    assert not marker.exists()
