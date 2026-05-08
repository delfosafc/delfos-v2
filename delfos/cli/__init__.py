"""CLI Typer — frontend fino sobre ``delfos.Session``.

Entrypoints:
- ``python -m delfos`` (atalho via ``delfos/__main__.py``)
- ``python -m delfos.cli``

Re-exporta o objeto ``app`` para uso programático em testes (``CliRunner``).
"""

from delfos.cli._app import app

__all__ = ["app"]
