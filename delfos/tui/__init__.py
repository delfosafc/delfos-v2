"""TUI Textual — frontend interativo para uso headless via SSH.

Re-exporta ``DelfosApp`` e ``run`` para o entrypoint. A árvore de telas e
widgets vive em ``delfos.tui._app`` (com underscore para evitar a colisão
com o atributo ``app`` do ``App`` quando se monkeypatcha em testes — mesma
convenção do CLI).
"""

from delfos.tui._app import DelfosApp, run

__all__ = ["DelfosApp", "run"]
