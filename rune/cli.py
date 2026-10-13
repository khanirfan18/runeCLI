"""Command line interface entrypoint for RuneCLI."""

import importlib.metadata
import os
import typer

from rune import theme
from rune.credentials import load_saved_credentials
from rune.flow import run_flow
from rune.lifecycle import render_refresh_view, render_status_view
from rune.recovery import recover_stale_setups
from rune.runtime import init_run
from rune.store import ensure_dirs
from rune.ui import get_console

app = typer.Typer(
    name="rune",
    help="Turn a real GitHub issue into a grounded coding quest.",
    add_completion=False,
)


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
        run_flow()


@app.command(name="status")
def status() -> None:
    """Display current quest status."""
    render_status_view()


@app.command(name="refresh")
def refresh() -> None:
    """Refresh active quest progress."""
    render_refresh_view()


if __name__ == "__main__":
    app()
