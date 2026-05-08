"""Resistência de contato — mede par a par (1-2, 2-3, ..., N-1 - N)."""

from __future__ import annotations

import pandas as pd

from delfos.central import Central
from delfos.events import EventBus, MeasurementSample, NullBus
from delfos.field import Field
from delfos.measurements._helpers import (
    NO_ABORT,
    AbortFlag,
    set_electrodes_all_boards,
)
from delfos.storage import ResultsStore
from delfos.units import Units


def res_contato(
    central: Central,
    units: Units,
    field: Field,
    results: ResultsStore,
    *,
    line: int = 1,
    settle_timeout: float = 0.6,
    bus: EventBus | None = None,
    abort: AbortFlag | None = None,
) -> None:
    """Para cada par de eletrodos consecutivos, conecta como dipolo e mede
    tensão/corrente via transmissor da Central. Resistência = ``1000 V/I``."""
    bus = bus or NullBus()
    abort = abort or NO_ABORT

    n_pairs = field.n_electrodes - 1
    results.clear_resistance()

    old_timeout = central.transport.timeout
    central.transport.set_timeout(settle_timeout)
    try:
        for atual in range(1, n_pairs + 1):
            if abort.is_set():
                break
            current_elec = [atual, atual + 1]
            signal = [255] * 9
            set_electrodes_all_boards(
                central, units, field,
                electrodes=current_elec + signal, line=line,
            )
            reading = central.measure_contact_resistance_pulse(
                current_pwm=0, settle_timeout=settle_timeout,
            )
            try:
                resistencia = round(1000 * reading.tensao / reading.corrente)
            except ZeroDivisionError:
                resistencia = round(1000 * reading.tensao / 0.1)
            results.add_resistance(pd.DataFrame({
                "eletrodo1": [atual],
                "eletrodo2": [atual + 1],
                "tensao": [reading.tensao],
                "corrente": [reading.corrente],
                "resistencia": [resistencia],
            }))
            bus.publish(MeasurementSample(
                kind="resistance",
                data={
                    "par": (atual, atual + 1),
                    "tensao": reading.tensao,
                    "corrente": reading.corrente,
                    "resistencia": resistencia,
                },
            ))
        # finaliza: zera as placas e desliga transmissor
        set_electrodes_all_boards(
            central, units, field,
            electrodes=[255] * 11, line=line, off=True,
        )
        results.save_resistance()
    finally:
        central.transport.set_timeout(old_timeout)
        central.current_off()
