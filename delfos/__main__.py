"""Entrypoint ``python -m delfos`` — delega para o CLI Typer."""

from delfos.cli._app import app

if __name__ == "__main__":
    app()
