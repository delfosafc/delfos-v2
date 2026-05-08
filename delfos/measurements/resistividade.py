"""Resistividade aparente — ciclo de corrente + leitura de VP por canal.

Cobre tanto a task ``resistividade`` quanto ``fullwave`` do JSON job legado:
``fullwave`` é apenas ``resistividade(is_fullwave=True)``.
"""

from __future__ import annotations

import pandas as pd

from delfos.central import Central
from delfos.events import EventBus, MeasurementSample, NullBus
from delfos.field import Field
from delfos.measurements._helpers import (
    NO_ABORT,
    AbortFlag,
    fullwave_to_string,
    set_electrodes_all_boards,
)
from delfos.storage import ResultsStore
from delfos.units import Units


def resistividade(
    central: Central,
    units: Units,
    field: Field,
    results: ResultsStore,
    *,
    electrodes: list[int],
    current_elec: list[int],
    channels: list[int],
    line: int = 1,
    power_ma: float = 0.0,
    ciclos: int = 10,
    step: int = 0,
    is_fullwave: bool = False,
    bus: EventBus | None = None,
    abort: AbortFlag | None = None,
) -> bool:
    """Uma medida de resistividade.

    Devolve ``True`` se houve falha que justifica retry pelo caller (ciclo de
    corrente errou ou ``n_pulsos <= 1``); ``False`` em sucesso. Equivale ao
    retorno de ``Switch.resistivity_cicle`` do legado.
    """
    bus = bus or NullBus()
    abort = abort or NO_ABORT

    if not current_elec:
        current_elec = [255, 255]
    if len(electrodes) < 9:
        electrodes = electrodes + [255] * (9 - len(electrodes))

    set_electrodes_all_boards(
        central, units, field,
        electrodes=current_elec + electrodes, line=line,
    )
    cycle_result = central.run_current_cycle(corrente_ma=power_ma, stack=ciclos)
    if cycle_result.erro:
        return True

    for channel in channels:
        if abort.is_set():
            return False
        ur = units.ur_from_channel(channel)
        addr = Units.addr_from_row(ur)
        vp = central.read_vp(addr)
        if vp.n_pulsos <= 1:
            return True

        fullwave_str: str | int = 0
        if is_fullwave:
            fw = central.read_fullwave(addr)
            fullwave_str = fullwave_to_string(fw)

        pos_a = field.pos(current_elec[0])
        pos_b = field.pos(current_elec[1])
        pos_m = field.pos(electrodes[channel - 1])
        pos_n = field.pos(electrodes[channel])

        results.add_resistivity(pd.DataFrame({
            "Ax": [pos_a[0]], "Ay": [pos_a[1]],
            "Bx": [pos_b[0]], "By": [pos_b[1]],
            "Mx": [pos_m[0]], "My": [pos_m[1]],
            "Nx": [pos_n[0]], "Ny": [pos_n[1]],
            "canal": [channel],
            "Vp": [vp.vpeak], "vp_raw": [vp.vp_raw],
            "varvp": [vp.varvp], "varvp_raw": [vp.varvp_raw],
            "tensao": [cycle_result.tensao],
            "corrente": [cycle_result.corrente],
            "step": [step], "potencia": [power_ma],
            "n_pulsos": [vp.n_pulsos], "ganho": [vp.ganho],
            "amostras": [vp.amostras], "fullwave": [fullwave_str],
        }))
        bus.publish(MeasurementSample(
            kind="resistivity",
            data={
                "step": step, "channel": channel,
                "vp": vp.vpeak,
                "tensao": cycle_result.tensao,
                "corrente": cycle_result.corrente,
            },
        ))

    results.save_resistivity()
    return False
