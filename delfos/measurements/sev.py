"""SEV — Sondagem Elétrica Vertical (medida no canal 1)."""

from __future__ import annotations

import time

import pandas as pd

from delfos.central import Central, CurrentReading, ProtocolError
from delfos.events import EventBus, MeasurementSample, NullBus
from delfos.measurements._helpers import (
    NO_ABORT,
    AbortFlag,
    fullwave_to_string,
)
from delfos.protocol import GeoVariable
from delfos.storage import ResultsStore
from delfos.units import Units


def sev(
    central: Central,
    units: Units,
    results: ResultsStore,
    *,
    power_ma: float = 0.0,
    cicle_time: float = 7,
    step: int = 0,
    is_fullwave: bool = False,
    bus: EventBus | None = None,
    abort: AbortFlag | None = None,
) -> None:
    """Liga corrente em modo auto, mede VP em loop (~0.5s entre leituras),
    desliga e captura a leitura final do canal 1."""
    bus = bus or NullBus()
    abort = abort or NO_ABORT

    central.current_auto(corrente_ma=power_ma)
    central.start_geo(GeoVariable.VP)
    last = _sev_current_loop(central, cicle_time=cicle_time, abort=abort, bus=bus)
    central.stop_geo(GeoVariable.VP)
    central.current_off()

    channel = 1
    ur = units.ur_from_channel(channel)
    addr = Units.addr_from_row(ur)
    vp = central.read_vp(addr)
    if vp.n_pulsos <= 1:
        return

    fullwave_str: str | int = 0
    if is_fullwave:
        fw = central.read_fullwave(addr)
        fullwave_str = fullwave_to_string(fw)

    results.add_sev(pd.DataFrame({
        "canal": [channel],
        "Vp": [vp.vpeak], "vp_raw": [vp.vp_raw],
        "varvp": [vp.varvp], "varvp_raw": [vp.varvp_raw],
        "tensao": [last.tensao], "corrente": [last.corrente],
        "step": [step], "potencia": [power_ma],
        "fullwave": [fullwave_str],
        "n_pulsos": [vp.n_pulsos], "ganho": [vp.ganho],
    }))
    results.save_sev()
    bus.publish(MeasurementSample(
        kind="sev",
        data={"step": step, "vp": vp.vpeak,
              "tensao": last.tensao, "corrente": last.corrente},
    ))


def _sev_current_loop(
    central: Central,
    *,
    cicle_time: float,
    abort: AbortFlag,
    bus: EventBus,
) -> CurrentReading:
    """Lê INF_CORRENTE_TRANSM em loop por ``2*(cicle_time-2)`` iterações,
    espaçando ~0.5s entre leituras. Devolve a última amostra."""
    time.sleep(2)
    last = CurrentReading(0.0, 0.0, 0, 0, b"")
    iterations = 2 * (int(cicle_time) - 2)
    for _ in range(iterations):
        if abort.is_set():
            break
        start = time.perf_counter()
        try:
            last = central.read_current()
            bus.publish(MeasurementSample(
                kind="sev_current",
                data={"tensao": last.tensao, "corrente": last.corrente},
            ))
        except ProtocolError:
            pass
        elapsed = time.perf_counter() - start
        if elapsed < 0.48:
            time.sleep(0.5 - elapsed)
    return last
