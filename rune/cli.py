"""Command line interface entrypoint for RuneCLI."""

import importlib.metadata
import os
import sys
from contextlib import contextmanager
import typer

from rune import theme
from rune.credentials import load_saved_credentials
from rune.flow import run_flow
from rune.gemma import GemmaError
from rune.github import GitHubAuthError, GitHubNotFoundError, GitHubRateLimitError
from rune.lifecycle import render_refresh_view, render_status_view
from rune.recovery import recover_stale_setups
from rune.runtime import init_run
from rune.store import StoreError, ensure_dirs
from rune.ui import get_console, redact

app = typer.Typer(
    name="rune",
    help="Turn a real GitHub issue into a grounded coding quest.",
    add_completion=False,
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
)


@contextmanager
def handle_cli_errors():
    """Wrap CLI execution in a friendly error handler for known and unexpected errors."""
    try:
        yield
    except KeyboardInterrupt:
        console = get_console()
        console.print("Quest board closed.")
        sys.exit(130)
    except (
        GemmaError,
        GitHubAuthError,
        GitHubRateLimitError,
        GitHubNotFoundError,
        StoreError,
    ) as exc:
        console = get_console()
        console.print(redact(str(exc)), soft_wrap=True)
        if isinstance(exc, GemmaError):
            console.print(
                "Google's API had a problem. This is usually temporary, so please run rune again in a few minutes.",
                soft_wrap=True,
            )
        sys.exit(1)
    except (typer.Exit, SystemExit):
        raise
    except Exception as exc:
        if os.environ.get("RUNE_DEBUG") == "1":
            raise
        console = get_console()
        console.print(
            "Something unexpected went wrong. Please open an issue at https://github.com/khanirfan18/runeCLI/issues",
            soft_wrap=True,
        )
        console.print(redact(f"{type(exc).__name__}: {exc}"), soft_wrap=True)
        sys.exit(1)


def version_callback(value: bool) -> None:
    if value:
        try:
            ver = importlib.metadata.version("runecli")
        except Exception:
            ver = "unknown"
        typer.echo(f"runecli {ver}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """RuneCLI entry callback."""
    started_at = init_run()
    ensure_dirs()
    load_saved_credentials()
    recover_stale_setups(started_at)
    if ctx.invoked_subcommand is None:
        console = get_console()
        console.print(theme.BANNER)
        with handle_cli_errors():
            run_flow()


@app.command(name="status")
def status() -> None:
    """Display current quest status."""
    with handle_cli_errors():
        render_status_view()


@app.command(name="refresh")
def refresh() -> None:
    """Refresh active quest progress."""
    with handle_cli_errors():
        render_refresh_view()


if __name__ == "__main__":
    app()
