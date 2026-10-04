"""Command line interface entrypoint for RuneCLI."""

import typer

from rune import theme
from rune.flow import run_flow
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
    init_run()
    ensure_dirs()
    if ctx.invoked_subcommand is None:
        console = get_console()
        console.print(theme.BANNER)
        run_flow()


@app.command(name="status")
def status() -> None:
    """Display current quest status."""
    console = get_console()
    console.print("not wired yet")


@app.command(name="refresh")
def refresh() -> None:
    """Refresh active quest progress."""
    console = get_console()
    console.print("not wired yet")


if __name__ == "__main__":
    app()
