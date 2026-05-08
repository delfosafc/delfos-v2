"""Logs em arquivo (output, debug, error) com timestamp."""

from __future__ import annotations

import datetime as dt

from delfos.storage.paths import Paths


class LogWriter:
    """Escreve linhas com timestamp ``HH:MM:SS`` em arquivos por categoria."""

    def __init__(self, paths: Paths, base_name: str):
        self.paths = paths
        self.base_name = base_name

    @staticmethod
    def _ts() -> str:
        return dt.datetime.now().strftime("%H:%M:%S")

    def output(self, text: str) -> None:
        with self.paths.output(self.base_name).open("a", encoding="utf-8") as f:
            f.write(f"{self._ts()} - {text}\n")

    def debug(self, text: str) -> None:
        with self.paths.debug(self.base_name).open("a", encoding="utf-8") as f:
            f.write(f"{self._ts()} - {text}\n")

    def error(self, text: str) -> None:
        with self.paths.error(self.base_name).open("a", encoding="utf-8") as f:
            f.write(f"{self._ts()} - {text}\n")
