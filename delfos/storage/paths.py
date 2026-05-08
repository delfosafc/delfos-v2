"""Resolução de caminhos do filesystem.

Replica o layout do SB64_dash legado:

    <files_root>/
      system/
        addr.dat
        jobs/*.json
      <line>/
        output/<base_name> output.txt
        output/<base_name> debug.txt
        output/<base_name> error.txt
        res/<base_name>.csv
        data/<base_name>.csv
        sp/<base_name>.csv
        sev/<base_name>.csv
        processed/<base_name>.dat

``files_root`` default é ``./files`` relativo ao CWD do processo (não ao
código). Configurável passando explicitamente ou via Session.
"""

from __future__ import annotations

from pathlib import Path


class Paths:
    """Resolve paths sob demanda, criando diretórios pai quando necessário."""

    def __init__(
        self,
        files_root: str | Path | None = None,
        line: str = "data",
    ):
        if files_root is None:
            files_root = Path.cwd() / "files"
        self.files_root = Path(files_root)
        self.line = line or "data"

    @property
    def system(self) -> Path:
        return self.files_root / "system"

    @property
    def jobs(self) -> Path:
        return self.system / "jobs"

    @property
    def addr_dat(self) -> Path:
        return self.system / "addr.dat"

    @property
    def data_folder(self) -> Path:
        return self.files_root / self.line

    def _resolve(self, *parts: str) -> Path:
        p = self.data_folder.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def output(self, base_name: str) -> Path:
        return self._resolve("output", f"{base_name} output.txt")

    def debug(self, base_name: str) -> Path:
        return self._resolve("output", f"{base_name} debug.txt")

    def error(self, base_name: str) -> Path:
        return self._resolve("output", f"{base_name} error.txt")

    def resistance(self, base_name: str) -> Path:
        return self._resolve("res", f"{base_name}.csv")

    def data(self, base_name: str) -> Path:
        return self._resolve("data", f"{base_name}.csv")

    def sp(self, base_name: str) -> Path:
        return self._resolve("sp", f"{base_name}.csv")

    def sev(self, base_name: str) -> Path:
        return self._resolve("sev", f"{base_name}.csv")

    def processed(self, base_name: str) -> Path:
        return self._resolve("processed", f"{base_name}.dat")
