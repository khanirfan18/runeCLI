# RuneCLI

A terminal-first developer tool that turns real GitHub issues into grounded, timed coding quests with RuneScape-inspired progression.
<img width="1327" height="746" alt="git" src="https://github.com/user-attachments/assets/e73d530b-d5ff-4464-bf64-18080d9ee4cc" />

---

## Installation

RuneCLI requires Python 3.11 or newer. Install the published package:

```bash
python -m pip install runecli
rune --help
```

`pipx install runecli` is also a good option for an isolated command-line
installation. On Linux distributions that protect the system Python, use
`pipx` or a user-managed Python installation instead of
`--break-system-packages`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | **Yes** | Personal access token (classic or fine-grained with `repo` scope) used to interact with the GitHub API. Never logged or printed; interactive setup stores it only in Rune's owner-only local config. |
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key used exclusively with Google's open-weights Gemma 4 model (`gemma-4-31b-it`). Interactive setup stores it only in Rune's owner-only local config. |
| `RUNE_SEARCH_USER` | No | Pre-fills the Sage prompt on the Quest Board (the GitHub user or org whose issues to search; **not** your personal username). |
| `GEMMA_MODEL` | No | Gemma model identifier (defaults to `gemma-4-31b-it`; also supports `gemma-4-26b-a4b-it`). Must start with `gemma-`. |
| `RUNE_DURATION_OVERRIDE_SECONDS` | No | Overrides quest timer duration in seconds for testing and demos. Modifies duration only, never XP. |
| `RUNE_HOME` | No | Custom root directory for local quest records, workspaces, player cache, and analysis clone caches (defaults to `~/.rune`). |
| `SENTRY_DSN` | No | Optional Sentry DSN for error telemetry. When set, only redacted tags are sent; tokens, issue content, and file paths are never transmitted. |

On the first interactive `rune` launch, Rune asks for your GitHub token and
Gemini API key using hidden password prompts. They are stored locally in
`~/.rune/config.json` (or under `RUNE_HOME`) with owner-only permissions and
loaded automatically on later launches. Environment variables, when provided,
take precedence over saved values. Never commit tokens or put them in a
repository file.

---

## Commands

Rune provides exactly three commands:

### `rune`
Starts the interactive quest cycle:
1. Verifies GitHub credentials and detects an installed IDE (VS Code `code` or Cursor `cursor`).
2. Opens the Quest Board to search open issues by keyword, Sage, and assignment status.
3. Clones a bounded, read-only analysis cache and extracts deterministic code evidence (E1–E8).
4. Uses Gemma 4 to formulate grounded quest specifications with acceptance criteria.
5. Creates an empty workspace directory and launches your IDE.
6. Prints guided Git setup commands and verifies your branch before starting the timer.

### `rune status`
Displays the active quest's status, remaining time, acceptance criteria, matched pull request status, and Git finishing instructions.

### `rune refresh`
Polls GitHub for pull request activity matching your quest branch. When your PR is merged, transitions the quest to `COMPLETED` and awards RuneScape XP.

---

## Quest Board Filters

- **Keywords**: 3 to 8 search terms matching issue titles and bodies.
- **Sage**: The GitHub username or organization whose repositories to search (e.g. `pallets`, `fastapi`). Leave blank to search across public repositories. *Note: Sage designates the repo owner whose issues you seek to solve, not your own username.*
- **Unassigned**: Choose `Yes` to find unclaimed issues (`is:unassigned`) or `No` to include assigned issues.
- **Difficulty**:
  - `EASY`: 60 minutes / 100 XP
  - `NORMAL`: 180 minutes / 150 XP
  - `HARD`: 360 minutes / 250 XP
  - `EPIC`: 540 minutes / 400 XP

---

## Guided Git Flow

Rune guides; the player controls Git. Rune never automatically pushes, commits, creates branches, or forks on your behalf:
1. **Empty Workspace**: Rune creates an isolated workspace directory at `~/.rune/workspaces/<quest-id>/` and opens it in your detected editor.
2. **Setup Instructions**: Rune prints the exact commands to run in your IDE terminal:
   - **Direct Route** (repositories where you have push permission): Clones the base repo and creates a dedicated quest branch (`rune/<display_id>-<issue_number>-<slug>`).
   - **Fork Route** (external open-source repositories): Instructs you to fork the repository on GitHub, clone your fork, configure the `upstream` remote, and create the quest branch.
3. **Read-Only Verification**: Rune inspects `git remote` and `git branch` within the workspace. The quest timer starts only after verification succeeds.
4. **Finishing Instructions**: Once coding is complete, Rune prints the commands to stage, commit, and push your branch, along with the link to open a standard GitHub pull request.

---

## Basic usage

```bash
rune
rune status
rune refresh
```

The first command opens the interactive Quest Board. Rune creates local quest
records and analysis caches under `~/.rune`.

## Demo walkthrough

1. Start Rune:
   ```bash
   rune
   ```
2. On the first run, paste your credentials when prompted. You can also set
   `GITHUB_TOKEN` and `GEMINI_API_KEY` before launching.
3. Search for issues on the Quest Board:
   - Keywords: `parser crash`
   - Sage: `pallets` (or leave blank)
   - Unassigned: `Yes`
   - Difficulty: `NORMAL`
4. Select an issue from the results.
5. Review Gemma 4's quest framings with cited code evidence, acceptance criteria, and objectives.
6. Accept a quest. Rune creates `~/.rune/workspaces/<quest-id>/` and opens VS Code or Cursor.
7. Run the printed setup commands in the IDE terminal and press Enter to verify.
8. Implement your fix in the IDE and run Rune's finish commands:
   ```bash
   git add .
   git commit -m "fix: resolve CLI parser crash"
   git push origin rune/<branch-name>
   ```
9. Open a Pull Request on GitHub against the base branch.
10. Check progress with `rune status`.
11. Merge the pull request on GitHub, then run:
    ```bash
    rune refresh
    ```
12. See your quest marked `COMPLETED` and watch your RuneScape level progress!

## Development

To work on RuneCLI from source:

```bash
git clone https://github.com/khanirfan18/runecli.git
cd runecli
python -m pip install -e ".[dev]"
python -m pytest -q
```

Build release artifacts locally with:

```bash
python -m pip install build
python -m build
```

## Reporting issues

Report bugs and feature ideas at
https://github.com/khanirfan18/runecli/issues.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
