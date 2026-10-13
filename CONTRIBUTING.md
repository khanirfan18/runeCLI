# Contributing to RuneCLI

Thank you for your interest in contributing to RuneCLI! This guide covers setup, running tests, branch naming, and pull request guidelines.

---

## 1. Development Setup

RuneCLI requires Python 3.11 or newer.

1. Clone the repository:
   ```bash
   git clone https://github.com/khanirfan18/runeCLI.git
   cd runeCLI
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install RuneCLI in editable mode with development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

---

## 2. Running Tests

Run the full test suite using pytest:

```bash
python -m pytest -q
```

All tests should pass before opening a pull request. Tests must remain fast, deterministic, and offline (using mocks/fakes rather than live network calls).

Tests must never launch real external editors (`code`, `cursor`). An autouse fixture in `tests/conftest.py` intercepts process launches from `rune.editor`. Always ensure the test suite passes with warnings as errors:
```bash
python -m pytest -q -W error
```

---

## 3. Branch Naming

Use descriptive branch names with a conventional prefix:

- `feat/<short-description>`: New features or capabilities
- `fix/<short-description>`: Bug fixes
- `chore/<short-description>`: Maintenance, dependencies, documentation, or repo cleanups
- `docs/<short-description>`: Documentation changes

Examples: `feat/add-version-flag`, `fix/gemma-reason-parsing`.

---

## 4. PR Checklist

Before submitting a Pull Request, please ensure:

- [ ] All tests pass cleanly (`python -m pytest -q -W error`).
- [ ] Any new logic includes corresponding unit tests in `tests/`.
- [ ] No secrets, API keys, tokens, or `.env` files are committed.
- [ ] Commits are clear, focused, and atomic.
- [ ] Pull request description describes the problem and solution, linking any relevant issue.
