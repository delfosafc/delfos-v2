"""Chamada — pinga todas as unidades do addr.dat e reporta sucesso/falha."""

from __future__ import annotations

from dataclasses import dataclass

from delfos.central import Central, ProtocolError
from delfos.events import EventBus, NullBus, UnitResponse
from delfos.measurements._helpers import NO_ABORT, AbortFlag
from delfos.protocol import CyclePeriod
from delfos.storage import LogWriter
from delfos.units import Units


@dataclass(frozen=True)
class ChamadaResult:
    failed_units: list[int]


def chamada(
    central: Central,
    units: Units,
    *,
    ciclo: CyclePeriod | int | None = None,
    bus: EventBus | None = None,
    abort: AbortFlag | None = None,
    logs: LogWriter | None = None,
) -> ChamadaResult:
    """Pinga a Central e em seguida cada UASG do ``addr.dat``.

    Para cada unidade, publica um ``UnitResponse(success=...)`` no bus.
    Devolve a lista de ids que falharam.
    """
    bus = bus or NullBus()
    abort = abort or NO_ABORT

    if ciclo is not None:
        central.set_cycle(ciclo)

    failed: list[int] = []
    if logs is not None:
        logs.output("Iniciando a chamada das unidades")

    central.ping_central()

    for unit_id, row in units.df.iterrows():
        if abort.is_set():
            break
        addr = Units.addr_from_row(row)
        try:
            central.ping_unit(addr)
            ok = True
        except ProtocolError:
            ok = False
        unit_id_int = int(unit_id)  # type: ignore[arg-type]
        serial = str(row.get("serial", ""))
        bus.publish(UnitResponse(unit_id=unit_id_int, success=ok, detail=serial))
        if logs is not None:
            if ok:
                logs.output(f"Unidade {unit_id_int} respondeu!")
            else:
                logs.output(f"Unidade {unit_id_int} não respondeu!")
        if not ok:
            failed.append(unit_id_int)

    if failed and logs is not None:
        logs.output(f"Falhas na chamada: {failed}")

    return ChamadaResult(failed_units=failed)
