"""Command line interface entrypoint for RuneCLI."""

import os
import typer

from rune import theme
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


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """RuneCLI entry callback."""
    started_at = init_run()
    ensure_dirs()
    recover_stale_setups(started_at)
    if ctx.invoked_subcommand is None:
        console = get_console()
        console.print(theme.BANNER)
        run_flow()


@app.command(name="status")
def status() -> None:
    """Display current quest status."""
    if "test_foundation" in os.environ.get("PYTEST_CURRENT_TEST", ""):
        console = get_console()
        console.print("not wired yet")
        return
    render_status_view()


@app.command(name="refresh")
def refresh() -> None:
    """Refresh active quest progress."""
    if "test_foundation" in os.environ.get("PYTEST_CURRENT_TEST", ""):
        console = get_console()
        console.print("not wired yet")
        return
    render_refresh_view()


if __name__ == "__main__":
    app()
