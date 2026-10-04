"""Read-only analysis clone and deterministic evidence extraction for RuneCLI.

Safely clones public repositories into RUNE_HOME/cache/<owner>__<repo>/,
scans files with strict security filters and resource bounds, scores relevance
against E0, and extracts evidence snippets E1..E8.
"""

import fnmatch
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rune import store
from rune.models import E0, RepoMeta
from rune.ui import redact, sanitize

# Resource limits
MAX_FILES_SCANNED = 3000
MAX_FILE_SIZE = 200 * 1024  # 204,800 bytes
MAX_EVIDENCE_SNIPPETS = 8
MAX_LINES_PER_SNIPPET = 60
MAX_TOTAL_EVIDENCE_CHARS = 12000

# Directory prune list
IGNORED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    ".cache",
    ".next",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "target",
}

# Secret files to never read (case-insensitive fnmatch)
SECRET_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "credentials*",
    "secrets*",
    ".npmrc",
    ".pypirc",
    ".netrc",
]

# Exact secret assignment regex specified by project rules
EXACT_SECRET_REGEX = re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]", re.I)

# Token and key patterns
AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")

# Binary extensions to skip
COMMON_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war",
    ".db", ".sqlite", ".sqlite3",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flv",
    ".wasm",
}

# Generated file patterns
GENERATED_EXTS = {
    ".min.js", ".min.css", ".map", ".svg",
}

GENERATED_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "pipfile.lock", "cargo.lock", "composer.lock", "gemfile.lock", "go.sum",
}

# Common source code extensions eligible for preference bonus
COMMON_CODE_EXTS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".c", ".cpp", ".cc", ".cxx",
    ".h", ".hpp", ".hh", ".rs", ".go", ".java", ".kt", ".kts", ".rb", ".php",
    ".cs", ".swift", ".scala", ".sh", ".bash", ".zsh", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".sql", ".lua", ".r", ".pl", ".pm",
}

# English stop words (length >= 3)
STOP_WORDS = {
    "about", "above", "after", "again", "against", "all", "and", "any", "are",
    "aren", "because", "been", "before", "being", "below", "between", "both",
    "but", "can", "cannot", "could", "couldn", "did", "didn", "does", "doesn",
    "doing", "don", "down", "during", "each", "few", "for", "from", "further",
    "had", "hadn", "has", "hasn", "have", "haven", "having", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "into", "isn", "its",
    "itself", "let", "more", "most", "mustn", "not", "off", "once", "only",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan", "she", "should", "shouldn", "some", "such", "than", "that", "the",
    "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "too", "under", "until", "very", "was", "wasn",
    "were", "weren", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "won", "would", "wouldn", "you", "your", "yours",
    "yourself", "yourselves",
}

# Owner / repo validation regex: alphanumeric, underscores, dots, hyphens
RE_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.-]+$")


class AnalysisError(Exception):
    """Raised when repository clone or analysis fails."""


class EvidenceSnippet(BaseModel):
    """Grounded evidence snippet extracted from the cloned repository."""

    id: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    score: int

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


def validate_cache_target(owner: str, repo: str) -> Path:
    """Validate owner and repo and ensure the target directory parent is cache_dir()."""
    if not RE_OWNER_REPO.match(owner):
        raise ValueError(f"Invalid repository owner: {owner}")
    if not RE_OWNER_REPO.match(repo):
        raise ValueError(f"Invalid repository name: {repo}")

    cache_parent = store.cache_dir().resolve()
    target_path = store.cache_dir() / f"{owner}__{repo}"

    # Confirm resolved path's parent is exactly cache_dir() (prevents path traversal)
    if not target_path.is_symlink():
        if target_path.resolve().parent != cache_parent:
            raise ValueError(f"Path traversal detected: {owner}__{repo}")

    return target_path


def prepare_cache_dir(owner: str, repo: str) -> Path:
    """Safely prepare the cache directory for a repository clone.

    If target is a symlink, unlinks only the link.
    If target exists as a directory, removes only that directory.
    Refuses any path outside cache_dir().
    """
    target_path = validate_cache_target(owner, repo)
    cache_parent = store.cache_dir().resolve()

    if target_path.is_symlink():
        target_path.unlink()
    elif target_path.exists():
        if target_path.resolve().parent != cache_parent:
            raise ValueError("Target path parent is not the cache directory.")
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    return target_path


def build_clone_cmd(
    default_branch: str,
    url: str,
    dest: str,
    empty_hooks_dir: str,
) -> list[str]:
    """Build the exact git clone argv command list.

    Rejects a default_branch that starts with '-'.
    """
    if default_branch.startswith("-"):
        raise ValueError(f"Invalid default branch starting with '-': {default_branch}")

    return [
        "git",
        "-c", f"core.hooksPath={empty_hooks_dir}",
        "-c", "protocol.file.allow=never",
        "-c", "core.fsmonitor=false",
        "clone",
        "--depth", "1",
        "--no-tags",
        "--single-branch",
        "--no-recurse-submodules",
        "--branch", default_branch,
        "--",
        url,
        dest,
    ]


def clone_repo(
    owner: str,
    repo: str,
    default_branch: str,
) -> Path:
    """Clone a public repository into the validated RUNE_HOME/cache directory.

    Executes git clone in a read-only, safe configuration without hooks,
    submodules, or repo script execution.
    """
    target_path = prepare_cache_dir(owner, repo)
    url = f"https://github.com/{owner}/{repo}.git"

    with tempfile.TemporaryDirectory() as empty_hooks_dir:
        cmd = build_clone_cmd(default_branch, url, str(target_path), empty_hooks_dir)
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            cmd,
            shell=False,
            timeout=120,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise AnalysisError(redact(f"Git clone failed: {result.stderr}"))

    return target_path


def extract_e0_tokens(title: str, body: str) -> list[str]:
    """Extract up to 30 lowercase alphanumeric tokens of length >= 3 from E0, excluding stop words."""
    combined = f"{title} {body}".lower()
    words = re.findall(r"[a-z0-9]+", combined)
    tokens: list[str] = []
    seen: set[str] = set()
    for w in words:
        if len(w) >= 3 and w not in STOP_WORDS and w not in seen:
            seen.add(w)
            tokens.append(w)
            if len(tokens) == 30:
                break
    return tokens


def is_secret_file(basename: str) -> bool:
    """Check if the filename matches any secret file patterns."""
    lower = basename.lower()
    for pat in SECRET_FILE_PATTERNS:
        if fnmatch.fnmatch(lower, pat.lower()):
            return True
    return False


def contains_secret(text: str) -> bool:
    """Check if text contains secret assignments or known secret patterns."""
    if EXACT_SECRET_REGEX.search(text):
        return True
    if AWS_KEY_RE.search(text):
        return True
    if "ghp_" in text:
        return True
    if "github_pat_" in text:
        return True
    if OPENAI_KEY_RE.search(text):
        return True
    if "AIza" in text:
        return True
    if PRIVATE_KEY_RE.search(text):
        return True
    return False


def is_generated_or_binary(rel_path: str, basename: str, file_path: Path) -> bool:
    """Check if a file is a binary or generated asset."""
    lower_base = basename.lower()

    # Lockfiles and generated configs
    if lower_base in GENERATED_FILENAMES or lower_base.endswith(".lock"):
        return True
    for gen_ext in GENERATED_EXTS:
        if lower_base.endswith(gen_ext):
            return True

    # Known binary extensions
    _, ext = os.path.splitext(lower_base)
    if ext in COMMON_BINARY_EXTS:
        return True

    # NUL byte in first 8000 bytes
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8000)
            if b"\x00" in chunk:
                return True
    except OSError:
        return True

    return False


def get_preference_bonus(rel_posix_path: str, basename: str) -> int:
    """Return +1 preference bonus for source files, tests, README, and configs."""
    lower_base = basename.lower()
    lower_path = rel_posix_path.lower()
    _, ext = os.path.splitext(lower_base)

    if ext in COMMON_CODE_EXTS:
        return 1

    if "test" in lower_base or "test" in lower_path:
        return 1

    if lower_base.startswith("readme"):
        return 1

    if lower_base in ("pyproject.toml", "package.json"):
        return 1

    if ext in (".cfg", ".toml", ".yaml", ".yml"):
        return 1

    return 0


def extract_evidence(repo_dir: Path, e0: E0) -> list[EvidenceSnippet]:
    """Scan a repository directory deterministically and extract evidence snippets E1..E8.

    Applies file count, size, and line caps, secret filters, and token relevance scoring.
    """
    tokens = extract_e0_tokens(e0.title, e0.body)
    if not tokens:
        return []

    repo_root = repo_dir.resolve()
    real_root = os.path.realpath(repo_root)

    scanned_files_count = 0
    qualifying_candidates: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(repo_root, topdown=True, followlinks=False):
        # Sort dirs and files for deterministic traversal
        dirs.sort()
        files.sort()

        # Prune ignored directories and symlink directories
        dirs[:] = [
            d for d in dirs
            if d not in IGNORED_DIRS
            and not os.path.islink(os.path.join(root, d))
        ]

        for fname in files:
            scanned_files_count += 1
            if scanned_files_count > MAX_FILES_SCANNED:
                break

            file_path = Path(root) / fname

            # Skip symlinks
            if file_path.is_symlink():
                continue

            # Ensure realpath stays inside repo root
            try:
                real_path = os.path.realpath(file_path)
            except OSError:
                continue

            if not (real_path == real_root or real_path.startswith(real_root + os.sep)):
                continue

            # File size limit
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            # Secret filename check
            if is_secret_file(fname):
                continue

            rel_posix = file_path.relative_to(repo_root).as_posix()

            # Skip binary and generated files
            if is_generated_or_binary(rel_posix, fname, file_path):
                continue

            # Read file content as UTF-8
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            # Token scoring
            basename_parts = set(p for p in re.split(r"[^a-zA-Z0-9]+", fname.lower()) if p)
            dir_path_str = os.path.dirname(rel_posix).lower()
            content_lower = content.lower()

            token_score = 0
            for tok in tokens:
                if tok in basename_parts:
                    token_score += 3
                if dir_path_str and tok in dir_path_str:
                    token_score += 2
                if tok in content_lower:
                    token_score += 1

            if token_score <= 0:
                continue

            # Preference bonus
            bonus = get_preference_bonus(rel_posix, fname)
            final_score = token_score + bonus

            # Determine snippet window (at most 60 lines)
            lines = content.splitlines()
            first_hit_line: int | None = None
            for idx, line in enumerate(lines, start=1):
                l_lower = line.lower()
                if any(tok in l_lower for tok in tokens):
                    first_hit_line = idx
                    break

            if first_hit_line is not None:
                start_line = max(1, first_hit_line - 10)
            else:
                start_line = 1

            end_line = min(len(lines), start_line + MAX_LINES_PER_SNIPPET - 1)
            snippet_lines = lines[start_line - 1 : end_line]
            snippet_raw = "\n".join(snippet_lines)
            snippet_clean = sanitize(snippet_raw)

            # Enforce secret rules on snippet
            if contains_secret(snippet_clean) or contains_secret(snippet_raw):
                continue

            qualifying_candidates.append({
                "path": rel_posix,
                "start_line": start_line,
                "end_line": end_line,
                "snippet": snippet_clean,
                "score": final_score,
            })

        if scanned_files_count > MAX_FILES_SCANNED:
            break

    # Sort candidates by score DESC, then path ASC
    qualifying_candidates.sort(key=lambda c: (-c["score"], c["path"]))

    # Enforce total evidence limits (max 8 snippets, max 12000 total chars)
    evidence: list[EvidenceSnippet] = []
    current_chars = 0

    for cand in qualifying_candidates:
        if len(evidence) >= MAX_EVIDENCE_SNIPPETS:
            break

        snip = cand["snippet"]
        if current_chars + len(snip) <= MAX_TOTAL_EVIDENCE_CHARS:
            eid = f"E{len(evidence) + 1}"
            evidence.append(
                EvidenceSnippet(
                    id=eid,
                    path=cand["path"],
                    start_line=cand["start_line"],
                    end_line=cand["end_line"],
                    snippet=snip,
                    score=cand["score"],
                )
            )
            current_chars += len(snip)
        else:
            # Enforce total 12000-char cap by truncating the last snippet to whole lines
            budget = MAX_TOTAL_EVIDENCE_CHARS - current_chars
            if budget <= 0:
                break

            lines = snip.split("\n")
            kept: list[str] = []
            for l in lines:
                test_text = "\n".join(kept + [l])
                if len(test_text) <= budget:
                    kept.append(l)
                else:
                    break

            if not kept:
                break

            truncated = "\n".join(kept)
            eid = f"E{len(evidence) + 1}"
            end_line = cand["start_line"] + len(kept) - 1
            evidence.append(
                EvidenceSnippet(
                    id=eid,
                    path=cand["path"],
                    start_line=cand["start_line"],
                    end_line=end_line,
                    snippet=truncated,
                    score=cand["score"],
                )
            )
            current_chars += len(truncated)
            break

    return evidence


def analyze_repo(repo_meta: RepoMeta, e0: E0) -> list[EvidenceSnippet]:
    """Orchestrate clone and evidence extraction for a selected quest issue."""
    parts = repo_meta.base_repo.split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid base_repo format: {repo_meta.base_repo}")
    owner, repo_name = parts[0], parts[1]
    repo_dir = clone_repo(owner, repo_name, repo_meta.default_branch)
    return extract_evidence(repo_dir, e0)
