"""Campo geométrico de eletrodos.

Equivalente ao ``set_field`` + ``redirected_electrodes`` do switch.py legado,
isolado num modelo independente. Mantém um DataFrame de posições (x, y) por
eletrodo e permite redirecionamento (1→1) entre eletrodos físicos.
"""

from __future__ import annotations

import pandas as pd


class Field:
    """Posições (x, y) dos eletrodos do campo, com redirects opcionais."""

    def __init__(
        self,
        n_electrodes: int = 32,
        *,
        spa_x: float = 1.0,
        spa_y: float = 0.0,
        ini_x: float = 0.0,
        ini_y: float = 0.0,
    ):
        self.redirected_electrodes: dict[int, int] = {}
        self.n_electrodes = n_electrodes
        self.spa_x = spa_x
        self.spa_y = spa_y
        self.ini_x = ini_x
        self.ini_y = ini_y
        self._compute_positions()

    def reconfigure(
        self,
        *,
        n_electrodes: int | None = None,
        spa_x: float | None = None,
        spa_y: float | None = None,
        ini_x: float | None = None,
        ini_y: float | None = None,
    ) -> None:
        """Atualiza um ou mais parâmetros do campo e recomputa posições."""
        if n_electrodes is not None:
            self.n_electrodes = n_electrodes
        if spa_x is not None:
            self.spa_x = spa_x
        if spa_y is not None:
            self.spa_y = spa_y
        if ini_x is not None:
            self.ini_x = ini_x
        if ini_y is not None:
            self.ini_y = ini_y
        self._compute_positions()

    def _compute_positions(self) -> None:
        pos_x = [round(self.ini_x + i * self.spa_x, 2) for i in range(self.n_electrodes)]
        pos_y = [round(self.ini_y + i * self.spa_y, 2) for i in range(self.n_electrodes)]
        self._df = pd.DataFrame(
            {
                "eletrodo": range(1, self.n_electrodes + 1),
                "x": pos_x,
                "y": pos_y,
            }
        ).set_index("eletrodo")

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    def pos(self, eletrodo: int) -> tuple[float, float]:
        """(x, y) do eletrodo, aplicando redirect se houver. ``(-1, -1)`` se desconhecido."""
        e = self.redirected_electrodes.get(eletrodo, eletrodo)
        try:
            row = self._df.loc[e]
        except KeyError:
            return -1.0, -1.0
        return float(row.x), float(row.y)

    def redirect_electrode(self, src: int, dst: int) -> None:
        self.redirected_electrodes[src] = dst

    def set_redirects(self, mapping: dict[int, int]) -> None:
        """Substitui o mapa de redirects. Útil para a task ``eletrodos`` do job."""
        self.redirected_electrodes = {int(k): int(v) for k, v in mapping.items()}

    def apply_redirects(self, electrodes: list[int]) -> list[int]:
        """Aplica o mapa de redirects a uma lista de eletrodos."""
        return [self.redirected_electrodes.get(e, e) for e in electrodes]
