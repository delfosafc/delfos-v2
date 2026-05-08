"""Tabela de unidades remotas (UASGs) — ``addr.dat``.

Substitui o ``load_addrs`` + helpers ``get_channels``/``get_switches``/
``get_ur_from_channel``/``get_electrodes_for_order``/``get_redirected_channels``
do switch.py legado.

**Schema v2** (recomendado, CSV separado por ``;``):

    addr;kind;slot;channel;serial
    0x0080;channel;;1;32770
    0x6Cff;switch;1;;65378

- ``addr``: endereço de 16 bits (aceita hex ``0xNNNN`` ou decimal)
- ``kind``: ``channel`` (UASG receptor) ou ``switch`` (placa MR64)
- ``slot``: posição da placa, vazio para channels (1, 2, 3...)
- ``channel``: número do canal, vazio para switches (1, 2, 3...)
- ``serial``: número serial do hardware (opcional, informativo)

ID da unidade é o índice da linha (1-based, sem coluna ``id`` explícita).

**Schema v1** (formato legado, ainda aceito com aviso de depreciação):

    id;end1;end2;serial;order;channel
    1;0x00;0x80;32770;0;1
    5;0x6C;0xff;65378;1;255

Migrado em memória para o schema v2; os arquivos no disco não são tocados.
Para converter de vez, use ``delfos migrate-addr <v1.dat> [v2.dat]``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

KIND_CHANNEL = "channel"
KIND_SWITCH = "switch"
_VALID_KINDS = frozenset({KIND_CHANNEL, KIND_SWITCH})


def _to_int(value: object) -> int:
    """Aceita int decimal ou string hex (``"0x80"``) e devolve int."""
    if isinstance(value, str):
        return int(value, 0)
    return int(value)  # type: ignore[arg-type]


def _parse_optional_int(value: object) -> int | None:
    """Vazio (NaN/string vazia) vira ``None``; resto vai por ``_to_int``."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, str) and value.strip() in ("", "-"):
        return None
    return _to_int(value)


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
        raw = pd.read_csv(path, header=0, sep=";", dtype=str, keep_default_na=False)
        cols = set(raw.columns)
        if {"addr", "kind"}.issubset(cols):
            return Units._parse_v2(raw)
        if {"end1", "end2", "order"}.issubset(cols):
            warnings.warn(
                f"addr.dat {Path(path).name}: schema v1 (id;end1;end2;...;order) "
                "está depreciado — use addr;kind;slot;channel;serial. "
                "Migrado em memória.",
                DeprecationWarning,
                stacklevel=3,
            )
            return Units._parse_v1(raw)
        raise ValueError(
            f"Schema desconhecido em {path}: colunas={sorted(cols)}. "
            f"Esperado v2 (addr;kind;slot;channel;serial) ou "
            f"v1 (id;end1;end2;serial;order;channel)."
        )

    @staticmethod
    def _parse_v2(raw: pd.DataFrame) -> pd.DataFrame:
        index = pd.RangeIndex(1, len(raw) + 1, name="id")
        addrs = [_to_int(v) for v in raw["addr"]]
        kinds_raw = [str(k).strip().lower() for k in raw["kind"]]
        invalid = [k for k in kinds_raw if k not in _VALID_KINDS]
        if invalid:
            raise ValueError(
                f"valores de 'kind' inválidos: {sorted(set(invalid))}. "
                f"Esperado: {sorted(_VALID_KINDS)}"
            )
        slots = [_parse_optional_int(v) for v in raw.get("slot", [None] * len(raw))]
        channels = [
            _parse_optional_int(v) for v in raw.get("channel", [None] * len(raw))
        ]
        serials = [
            _parse_optional_int(v) for v in raw.get("serial", [None] * len(raw))
        ]
        return pd.DataFrame(
            {
                "addr": addrs,
                "kind": kinds_raw,
                "slot": slots,
                "channel": channels,
                "serial": serials,
            },
            index=index,
        )

    @staticmethod
    def _parse_v1(raw: pd.DataFrame) -> pd.DataFrame:
        end1 = [_to_int(v) for v in raw["end1"]]
        end2 = [_to_int(v) for v in raw["end2"]]
        order = [_to_int(v) for v in raw["order"]]
        channel_v1 = (
            [_to_int(v) for v in raw["channel"]] if "channel" in raw.columns else None
        )

        if "id" in raw.columns:
            ids = [_to_int(v) for v in raw["id"]]
            index = pd.Index(ids, name="id")
        else:
            index = pd.RangeIndex(1, len(raw) + 1, name="id")

        addrs = [(h << 8) | low for h, low in zip(end1, end2, strict=True)]
        kinds = [KIND_CHANNEL if o == 0 else KIND_SWITCH for o in order]
        slots = [int(o) if o > 0 else None for o in order]
        if channel_v1 is not None:
            channels = [
                int(c) if k == KIND_CHANNEL else None
                for c, k in zip(channel_v1, kinds, strict=True)
            ]
        else:
            channels = [None] * len(raw)
        serials = (
            [_parse_optional_int(v) for v in raw["serial"]]
            if "serial" in raw.columns
            else [None] * len(raw)
        )
        return pd.DataFrame(
            {
                "addr": addrs,
                "kind": kinds,
                "slot": slots,
                "channel": channels,
                "serial": serials,
            },
            index=index,
        )

    def reload(self, path: str | Path) -> None:
        """Recarrega in-place a partir de outro ``addr.dat``.

        Mantém a identidade do objeto (referências externas continuam válidas) e
        zera redirects de canal — coerente com o legado.
        """
        self._df = self._read_csv(path)
        self.redirected_channels = {}

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    # ------------------------------------------------------------------- views

    def get_channels(self) -> pd.DataFrame:
        """UASGs do tipo ``channel``."""
        return self._df[self._df["kind"] == KIND_CHANNEL]

    def get_switches(self) -> pd.DataFrame:
        """Switches MR64 (``kind == "switch"``), ordenados por ``slot``."""
        return self._df[self._df["kind"] == KIND_SWITCH].sort_values("slot")

    def addr(self, unit_id: int) -> int:
        """Endereço de 16 bits da unidade."""
        return int(self._df.loc[unit_id, "addr"])

    @staticmethod
    def addr_from_row(row: pd.Series) -> int:
        """Endereço de 16 bits a partir de uma linha já obtida (Series)."""
        return int(row["addr"])

    def ur_from_channel(self, channel: int) -> pd.Series:
        """Linha da unidade canal correspondente a ``channel``."""
        ch = self.get_channels()
        match = ch[ch["channel"] == channel]
        if match.empty:
            raise KeyError(f"Canal {channel} não encontrado em addr.dat")
        return match.iloc[0]

    # --------------------------------------------------------- mapeamento MR64

    @staticmethod
    def electrodes_for_slot(electrodes: list[int], slot: int) -> list[int]:
        """Mapeia eletrodos globais para os 32 índices locais da placa ``slot``.

        Eletrodos fora do range ``[0..31]`` após o offset viram ``255`` (não conectado).
        """
        arr = np.asarray(electrodes, dtype=int)
        arr = arr - (slot - 1) * 32 - 1
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
