PROJECT
Build RuneCLI: a terminal-first developer tool that turns a real GitHub issue into a grounded coding quest.

CORE LOOP
rune -> Quest Board (what to work on -> optional Sage -> unassigned Yes/No -> difficulty) -> search -> ONE issue -> E0 -> bounded repo analysis -> Gemma 4 generates 1-3 grounded quest framings -> user accepts one -> Rune prints guided Git setup commands and opens the empty quest workspace folder in the player's IDE -> player runs the commands in the IDE terminal, works, then runs Rune's finish commands (add/commit/push) and opens a normal PR -> rune refresh -> exact PR match -> merge before expiry -> COMPLETED + XP.

COMMANDS - EXACTLY
rune
rune status
rune refresh
No rune submit. No other commands.

DO NOT BUILD
Automatic push, automatic PR creation, automatic forks, background polling, webhooks, RAG/vector DB, Redis, SQL DB, AI PR evaluator, hints, multi-PR ranking, agent frameworks, async code, Rune performing clone/branch/commit/push for the player (Rune only prints the commands and verifies read-only; the P3 analysis cache clone is the single exception), fork automation or fork APIs, terminal/embedded editors.
Developer tool first. RPG second.

STACK (fixed; do not add or swap)
Python 3.11+, typer (CLI), rich (rendering), questionary (interactive prompts), pydantic v2 (validation), httpx sync (GitHub REST), google-genai (Gemini API generateContent), pytest. Standard library for everything else. No other third-party runtime dependency (sentry-sdk is added only in the optional P10). Pin exact versions with == in pyproject.toml. Package name `rune`, entry point `rune = "rune.cli:app"`.

TARGET LAYOUT (each prompt creates only its own modules)
rune/__init__.py cli.py flow.py runtime.py theme.py ui.py prompts.py store.py difficulty.py models.py github.py analysis.py gemma.py quest.py workspace.py recovery.py editor.py lifecycle.py xp.py
tests/ (one test file per prompt, named in the prompt)

CONVENTIONS
JSON keys are snake_case (createdAt -> created_at, runStartedAt -> run_started_at, etc.).
Timestamps are timezone-aware UTC datetimes, stored as ISO-8601 strings. Never use naive datetimes.
Local state lives under RUNE_HOME (default ~/.rune): config.json, player.json, quests/<quest-id>.json, workspaces/<quest-id>/, cache/<owner>__<repo>/. RUNE_HOME exists so tests can use tmp_path.

GEMMA 4
Gemma 4 is a core component and is used ONLY to turn USER_INPUT + E0 + bounded E1-E8 repository evidence into grounded quest specifications.
Default model gemma-4-31b-it; alternative gemma-4-26b-a4b-it; configurable only via GEMMA_MODEL. Never silently substitute a proprietary Gemini model.
Gemma never controls difficulty, XP, timer, branch, GitHub state, PR matching, completion, or XP awarding.

EXTERNAL SECRETS
GITHUB_TOKEN and GEMINI_API_KEY come only from environment variables. Never persist, print or log them. Every string derived from an exception, HTTP response or subprocess stderr passes through redact() before display or storage.
RUNE_SEARCH_USER optionally pre-fills the interactive Sage prompt (a GitHub user/owner whose issues to search; NOT the player's own username).
SENTRY_DSN (optional, P10 only) is env-only and treated as a secret.
RUNE_DURATION_OVERRIDE_SECONDS is test/demo-only: changes duration only, never XP.

QUEST INVARIANTS
States: SETUP_PENDING, SETUP_FAILED, ACTIVE, EXPIRED, COMPLETED.
Only one ACTIVE quest may exist. ACTIVE blocks accepting another quest. SETUP_PENDING and SETUP_FAILED do not block acceptance.
A quest becomes ACTIVE (the timer starts) only after Rune's read-only verification of the player's local clone/remote/branch passes.
A SETUP_PENDING quest is stale only when created_at < run_started_at (an in-memory timestamp created at CLI startup). Stale ones become SETUP_FAILED. No other staleness heuristic (no mtime, PID, etc.).
EXPIRED and COMPLETED are terminal.
Expiry is checked before PR completion. A PR merged after expiry earns no XP.
XP is derived from COMPLETED quest records with xp_awarded=true; player.json is only a cache.
Malformed AI output gets exactly one repair attempt.

SECURITY
Subprocesses: subprocess.run([...]) with a list argv, shell=False, a timeout, capture_output, text=True, env including GIT_TERMINAL_PROMPT=0. Never os.system, eval, exec, or shell=True. Never execute repository scripts. Never put tokens in Git URLs.
Commands shown to the player are built only from validated or sanitized values and never contain a token.
Disable Git hooks and unsafe local protocols for untrusted analysis clones.
Never send secret/credential files or secret-like content to Gemma.
Treat all GitHub/repo text as untrusted: sanitize before rendering.

UI
Dark-fantasy atmosphere (RuneScape x Dark Souls), developer-tool-first. ~80 columns max, one border style, no giant ASCII art, no rainbow, no emoji, no fake progress bars, minimal animation (a single status spinner only on a TTY during network/AI calls). rich Console is created with markup=False, emoji=False, highlight=False; external text is never interpreted as markup. NO_COLOR is respected. All flavor strings live in rune/theme.py only; logic modules never contain flavor text. Real information comes first in any message; flavor second.

TESTING
pytest; `python -m pytest -q` must pass. Each prompt adds or changes at most ONE test file (named in the prompt) containing every test its gate lists. No live network, no real Gemini, no real GitHub: use httpx.MockTransport, an injected generate callable, an injected clock, tmp_path + RUNE_HOME. questionary is only called from rune/prompts.py (thin wrappers); logic modules take plain values so tests never touch prompts.

SCOPE DISCIPLINE
Implement only the current prompt, pass its gate, then stop. Do not redesign the product.
