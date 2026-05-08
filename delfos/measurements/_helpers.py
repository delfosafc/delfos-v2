"""Helpers compartilhados pelos measurements (abort flag, set_electrodes
multi-placa, formatação de fullwave)."""

from __future__ import annotations

import time
from typing import Protocol

import numpy as np

from delfos.central import Central, FullwaveReading
from delfos.field import Field
from delfos.units import Units


class AbortFlag(Protocol):
    """Compatível com ``threading.Event`` (apenas ``.is_set()`` é exigido)."""

    def is_set(self) -> bool: ...


class _NoAbort:
    def is_set(self) -> bool:
        return False


NO_ABORT: AbortFlag = _NoAbort()


def set_electrodes_all_boards(
    central: Central,
    units: Units,
    field: Field,
    electrodes: list[int],
    *,
    line: int = 1,
    off: bool = False,
    sleep_after: float = 0.3,
) -> None:
    """Envia frames MR64 (CONEX_ELETRODO 0xAA) para cada placa switch.

    Quando ``off=False`` (default) o helper primeiro zera as placas (envia
    ``[255]*11``) e depois envia ``electrodes`` aplicando redirects do field
    + mapeamento por order. Equivale a ``Switch.set_electrodes`` do legado.

    ``electrodes`` é uma lista de 11 ints: ``[I+, I-, S0..S8]``.
    """
    if off:
        target = [255] * 11
    else:
        # 1) zera tudo
        set_electrodes_all_boards(
            central, units, field, [255] * 11,
            line=line, off=True, sleep_after=0,
        )
        # 2) aplica redirects de field
        target = field.apply_redirects(electrodes)

    for _, row in units.get_switches().iterrows():
        per_board = units.electrodes_for_order(target, int(row["order"]))
        addr = Units.addr_from_row(row)
        central.set_electrodes(addr, electrodes=per_board, line=line)

    if sleep_after > 0:
        time.sleep(sleep_after)


def fullwave_to_string(fw: FullwaveReading) -> str:
    """Serializa o array de samples como string de inteiros separados por espaço.

    Mesmo formato usado em ``SB64_dash/switch.py.read_fullwave``.
    """
    return np.array2string(
        fw.samples, separator=" ", max_line_width=np.inf, threshold=30000
    )[1:-1]
