# RuneCLI

A terminal-first developer tool that turns real GitHub issues into grounded, timed coding quests with RuneScape-inspired progression.

<!-- TODO: demo GIF -->
<img width="1327" height="746" alt="RuneCLI Walkthrough" src="https://github.com/user-attachments/assets/e73d530b-d5ff-4464-bf64-18080d9ee4cc" />

---

## Installation

RuneCLI requires Python 3.11 or newer.

```bash
pip install runecli
```

Or install in an isolated environment using [pipx](https://github.com/pypa/pipx):

```bash
pipx install runecli
```

---

## 3-Step Quickstart

1. **Login & Configure**:
   ```bash
   rune
   ```
   On your first launch, Rune prompts for your GitHub token and Gemini API key, storing them in your local configuration.

2. **Pick a Quest**:
   Filter open issues on the Quest Board by keywords, Sage (repo owner), and difficulty. Review Gemma-formulated acceptance criteria and accept a quest.

3. **Finish a PR & Claim XP**:
   Follow guided Git commands in your IDE terminal, open a GitHub pull request, and run:
   ```bash
   rune refresh
   ```
   When your PR is merged before the timer expires, the quest completes and Rune awards RuneScape XP!

---

> [!NOTE]
> **Beta Notice — Credential Security**: Your tokens stay on your machine. Rune stores your `GITHUB_TOKEN` and `GEMINI_API_KEY` in a local file at `~/.rune/config.json` (or under `$RUNE_HOME`) with owner-only permissions (`chmod 0600`). This is a local file on your filesystem, not the OS keychain. Environment variables, when set, always take precedence. Never commit or share this configuration file.

---

[![PyPI version](https://img.shields.io/pypi/v/runecli.svg)](https://pypi.org/project/runecli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/khanirfan18/runeCLI/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## How It Works

- **Deterministic Code Evidence**: When you select an issue, Rune clones a shallow, read-only analysis cache and extracts bounded code evidence (E1–E8) matching the issue discussion.
- **Grounded Quest Framing**: Rune passes evidence to Google's open-weights Gemma 4 model (`gemma-4-31b-it`) via the Gemini API to formulate grounded quest specifications with concrete acceptance criteria.
- **Guided Git Flow**: Rune creates an isolated workspace directory at `~/.rune/workspaces/<quest-id>/`, opens your editor (VS Code or Cursor), and prints exact setup commands. Rune only reads Git status to verify setup—you retain full control over branching, commits, and pushes.
- **XP & Level Progression**: Rune tracks PR status matching your quest branch. Merging before the quest timer expires earns RuneScape XP based on quest difficulty.

---

## Contributing

We welcome contributions! Please see our [Contributing Guide](https://github.com/khanirfan18/runeCLI/blob/main/CONTRIBUTING.md) for local development setup, testing instructions, and pull request guidelines.

---

## Commands

Rune provides three focused commands:

### `rune`
Starts the interactive quest cycle:
1. Verifies credentials and detects an installed IDE (VS Code `code` or Cursor `cursor`).
2. Opens the Quest Board to search open issues.
3. Clones a bounded, read-only analysis cache and extracts evidence.
4. Generates grounded quest framings with Gemma 4 (`gemma-4-31b-it`).
5. Creates an isolated workspace and launches your IDE.
6. Prints guided Git setup commands and verifies your branch before starting the timer.

### `rune status`
Displays the active quest's status, remaining time, acceptance criteria, matched pull request status, and finish instructions.

### `rune refresh`
Checks GitHub for pull request activity matching your quest branch. When your PR is merged, transitions the quest to `COMPLETED` and awards RuneScape XP.

---

## Quest Board Filters

- **Keywords**: 3 to 8 search terms matching issue titles and bodies.
- **Sage**: The GitHub username or organization whose repositories to search (e.g. `pallets`, `fastapi`). Leave blank to search across public repositories.
- **Unassigned**: Choose `Yes` to find unclaimed issues (`is:unassigned`) or `No` to include assigned issues.
- **Difficulty**:
  - `EASY`: 60 minutes / 100 XP
  - `NORMAL`: 180 minutes / 150 XP
  - `HARD`: 360 minutes / 250 XP
  - `EPIC`: 540 minutes / 400 XP

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | **Yes** | Personal access token (classic or fine-grained with `repo` scope) used to interact with the GitHub API. Never logged or printed. |
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key used exclusively with Google's open-weights Gemma 4 model (`gemma-4-31b-it`). |
| `RUNE_SEARCH_USER` | No | Pre-fills the Sage prompt on the Quest Board (the GitHub user or org whose issues to search). |
| `GEMMA_MODEL` | No | Gemma model identifier (defaults to `gemma-4-31b-it`; also supports `gemma-4-26b-a4b-it`). Must start with `gemma-`. |
| `RUNE_HOME` | No | Custom root directory for local quest records, workspaces, player cache, and analysis clone caches (defaults to `~/.rune`). |

---

## Development

To work on RuneCLI from source:

```bash
git clone https://github.com/khanirfan18/runeCLI.git
cd runeCLI
python -m pip install -e ".[dev]"
python -m pytest -q
```

---

## Reporting Issues

Report bugs and feature ideas on GitHub at [https://github.com/khanirfan18/runeCLI/issues](https://github.com/khanirfan18/runeCLI/issues).

---

## License

MIT License. See [LICENSE](https://github.com/khanirfan18/runeCLI/blob/main/LICENSE) for details.
