# RuneCLI

A terminal-first developer tool that turns real GitHub issues into grounded, timed coding quests with RuneScape-inspired progression.

---

## Installation

RuneCLI requires Python 3.11+.

```bash
# Clone the repository
git clone https://github.com/khanirfan18/RuneCLI.git
cd RuneCLI

# Editable install
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"

# Or install globally using pipx
pipx install .
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | **Yes** | Personal access token (classic or fine-grained with `repo` scope) used to interact with the GitHub API. Never logged, printed, or persisted. |
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key used exclusively with Google's open-weights Gemma 4 model (`gemma-4-31b-it`). |
| `RUNE_SEARCH_USER` | No | Pre-fills the Sage prompt on the Quest Board (the GitHub user or org whose issues to search; **not** your personal username). |
| `GEMMA_MODEL` | No | Gemma model identifier (defaults to `gemma-4-31b-it`; also supports `gemma-4-26b-a4b-it`). Must start with `gemma-`. |
| `RUNE_DURATION_OVERRIDE_SECONDS` | No | Overrides quest timer duration in seconds for testing and demos. Modifies duration only, never XP. |
| `RUNE_HOME` | No | Custom root directory for local quest records, workspaces, player cache, and analysis clone caches (defaults to `~/.rune`). |
| `SENTRY_DSN` | No | Optional Sentry DSN for error telemetry. When set, only redacted tags are sent; tokens, issue content, and file paths are never transmitted. |

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

## Demo Walkthrough

1. Set your environment variables:
   ```bash
   export GITHUB_TOKEN="ghp_yourTokenHere"
   export GEMINI_API_KEY="AIzaSyYourKeyHere"
   ```
2. Launch Rune:
   ```bash
   rune
   ```
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

---

## License

MIT License. See [LICENSE](LICENSE) for details.
