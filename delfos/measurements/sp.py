"""SP — Potencial Espontâneo medido num eletrodo."""

from __future__ import annotations

import time

import pandas as pd

from delfos.central import Central
from delfos.events import EventBus, MeasurementSample, NullBus
from delfos.field import Field
from delfos.measurements._helpers import (
    AbortFlag,
    fullwave_to_string,
    set_electrodes_all_boards,
)
from delfos.protocol import GeoVariable
from delfos.storage import ResultsStore
from delfos.units import Units


def sp(
    central: Central,
    units: Units,
    field: Field,
    results: ResultsStore,
    *,
    eletrodo: int,
    channel: int = 1,
    line: int = 1,
    step: int = 0,
    is_fullwave: bool = True,
    settle: float = 2.0,
    bus: EventBus | None = None,
    abort: AbortFlag | None = None,  # noqa: ARG001 (mantido por simetria)
) -> None:
    """Mede SP num eletrodo. Quando ``channel == 2``, inverte o sinal
    (convenção herdada do switch.py)."""
    bus = bus or NullBus()

    current_elec = [255, 255]
    if channel == 1:
        signal = [eletrodo, 255, 255]
    elif channel == 2:
        signal = [255, 255, eletrodo]
    else:
        signal = [255, 255, 255]
    signal = signal + [255] * 6  # 9 itens

    set_electrodes_all_boards(
        central, units, field,
        electrodes=current_elec + signal, line=line,
    )
    central.start_geo(GeoVariable.SP)
    time.sleep(settle)
    central.stop_geo(GeoVariable.SP)

    ur = units.ur_from_channel(channel)
    addr = Units.addr_from_row(ur)
    sp_reading = central.read_sp(addr)

    fullwave_str: str | int = 0
    if is_fullwave:
        fw = central.read_fullwave(addr)
        fullwave_str = fullwave_to_string(fw)

    sp1, sp2, sp3 = sp_reading.sp1, sp_reading.sp2, sp_reading.sp3
    if channel == 2:
        sp1, sp2, sp3 = -sp1, -sp2, -sp3

    pos_x, _ = field.pos(eletrodo)

    results.add_sp(pd.DataFrame({
        "X": [pos_x],
        "SP1": [sp1], "SP2": [sp2], "SP3": [sp3],
        "step": [step], "fullwave": [fullwave_str],
    }))
    results.save_sp()
    bus.publish(MeasurementSample(
        kind="sp",
        data={"step": step, "X": pos_x,
              "SP1": sp1, "SP2": sp2, "SP3": sp3},
    ))
