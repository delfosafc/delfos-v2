"""Tabela de unidades remotas (UASGs) — ``addr.dat``.

Substitui o ``load_addrs`` + helpers ``get_channels``/``get_switches``/
``get_ur_from_channel``/``get_electrodes_for_order``/``get_redirected_channels``
do switch.py legado.

Schema de ``addr.dat`` (CSV separado por ``;``):

    id;end1;end2;serial;order;channel

- ``id``: índice da unidade (chave)
- ``end1``, ``end2``: bytes de endereço (aceita decimal ou hex string ``0xNN``)
- ``serial``: número serial do hardware
- ``order``: ``0`` para UASGs canal; ``>0`` para switches MR64 (ordem da placa)
- ``channel``: canal do receptor quando ``order==0``; ``255`` (não usado) caso contrário
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _to_int(value: object) -> int:
    """Aceita int decimal ou string hex (``"0x80"``) e devolve int."""
    if isinstance(value, str):
        return int(value, 0)
    return int(value)  # type: ignore[arg-type]


class Units:
    """Tabela de unidades. Use ``Units.load(path)`` para carregar de ``addr.dat``."""

    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.redirected_channels: dict[int, int] = {}

    @classmethod
    def load(cls, path: str | Path) -> Units:
        df = cls._read_csv(path)
        return cls(df)

    @staticmethod
    def _read_csv(path: str | Path) -> pd.DataFrame:
        df = pd.read_csv(path, header=0, sep=";", index_col="id")
        df["end1"] = df["end1"].map(_to_int)
        df["end2"] = df["end2"].map(_to_int)
        df["order"] = df["order"].map(int)
        if "channel" in df.columns:
            df["channel"] = df["channel"].map(int)
        return df

    def reload(self, path: str | Path) -> None:
        """Recarrega in-place a partir de outro ``addr.dat``.

        Mantém a identidade do objeto (referências externas continuam válidas) e
        zera redirects de canal — coerente com o comportamento do legado, onde
        trocar a tabela de unidades implicava reset do mapeamento de canais.
        """
        self._df = self._read_csv(path)
        self.redirected_channels = {}

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    # ------------------------------------------------------------------- views

    def get_channels(self) -> pd.DataFrame:
        """UASGs canal (``order == 0``)."""
        return self._df[self._df["order"] == 0]

    def get_switches(self) -> pd.DataFrame:
        """Switches MR64 (``order > 0``), ordenados por ``order``."""
        return self._df[self._df["order"] > 0].sort_values("order")

    def addr(self, unit_id: int) -> int:
        """Endereço de 16 bits da unidade (ADDH<<8 | ADDL)."""
        return self.addr_from_row(self._df.loc[unit_id])

    @staticmethod
    def addr_from_row(row: pd.Series) -> int:
        """Endereço de 16 bits a partir de uma linha já obtida (Series)."""
        return (int(row["end1"]) << 8) | int(row["end2"])

    def ur_from_channel(self, channel: int) -> pd.Series:
        """Linha da unidade canal correspondente a ``channel``."""
        ch = self.get_channels()
        match = ch[ch["channel"] == channel]
        if match.empty:
            raise KeyError(f"Canal {channel} não encontrado em addr.dat")
        return match.iloc[0]

    # --------------------------------------------------------- mapeamento MR64

    @staticmethod
    def electrodes_for_order(electrodes: list[int], order: int) -> list[int]:
        """Mapeia eletrodos globais para os 32 índices locais da placa ``order``.

        Eletrodos fora do range ``[0..31]`` após o offset viram ``255`` (não conectado).
        """
        arr = np.asarray(electrodes, dtype=int)
        arr = arr - (order - 1) * 32 - 1
        arr[arr < 0] = 255
        arr[arr > 31] = 255
        return arr.tolist()

    # ----------------------------------------------------- redirect de canais

    def redirect_channel(self, src: int, dst: int) -> None:
        self.redirected_channels[src] = dst

    def set_redirects(self, mapping: dict[int, int]) -> None:
        self.redirected_channels = {int(k): int(v) for k, v in mapping.items()}

    def get_redirected(
        self, electrodes: list[int], channels: list[int]
    ) -> tuple[list[int], list[int]]:
        """Aplica redirect de canais sobre o par ``(eletrodos, canais)``.

        Para cada canal ``c`` em ``channels``, o dipolo medido é
        ``(electrodes[c-1], electrodes[c])``. Se ``c`` está redirecionado para
        ``c'``, esse dipolo passa a ocupar as posições ``(c'-1, c')`` no array
        de saída (9 slots fixos preenchidos com ``-1`` nos vazios).

        Sem redirect, devolve as listas originais (no-op).
        """
        if not self.redirected_channels:
            return electrodes, channels
        electrodes_out = [-1] * 9
        channels_out: list[int] = []
        for ch in channels:
            new_ch = self.redirected_channels.get(ch, ch)
            channels_out.append(new_ch)
            electrodes_out[new_ch - 1] = electrodes[ch - 1]
            electrodes_out[new_ch] = electrodes[ch]
        return electrodes_out, channels_out
