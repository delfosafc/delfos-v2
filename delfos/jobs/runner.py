"""JobRunner — executa um Job, fazendo dispatch das tasks para Central +
measurements, emitindo eventos no bus e respeitando abort cooperativo.

As tasks que precisam de hooks externos (``serial`` e ``enderecos``) recebem
callbacks no construtor. Sem callback, o runner falha com ``NotImplementedError``
quando a task aparece — mensagem aponta para usar a Session (fase 7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from delfos.central import Central
from delfos.events import (
    EventBus,
    JobAborted,
    JobFinished,
    JobStarted,
    NullBus,
    Progress,
    StepCompleted,
    StepStarted,
)
from delfos.field import Field
from delfos.jobs.schema import Job, Step
from delfos.measurements import (
    NO_ABORT,
    AbortFlag,
    chamada,
    res_contato,
    resistividade,
    sev,
    sp,
)
from delfos.storage import LogWriter, ResultsStore
from delfos.units import Units


@dataclass(frozen=True)
class JobResult:
    completed: int  # quantos steps rodaram até o fim
    aborted: bool


class JobRunner:
    """Executa um ``Job`` despachando cada step para a camada apropriada."""

    def __init__(
        self,
        central: Central,
        units: Units,
        field: Field,
        results: ResultsStore,
        *,
        bus: EventBus | None = None,
        logs: LogWriter | None = None,
        reconnect: Callable[[str], None] | None = None,
        reload_addrs: Callable[[str | None], None] | None = None,
        resistividade_retries: int = 1,
    ):
        self._central = central
        self._units = units
        self._field = field
        self._results = results
        self._bus = bus or NullBus()
        self._logs = logs
        self._reconnect = reconnect
        self._reload_addrs = reload_addrs
        self._retries = resistividade_retries

    def run(
        self,
        job: Job,
        *,
        abort: AbortFlag | None = None,
        step_stop: int | None = None,
    ) -> JobResult:
        abort = abort or NO_ABORT
        n = len(job.steps)
        self._bus.publish(JobStarted(job_name=job.name, n_steps=n))
        completed = 0
        aborted = False
        try:
            for idx, step in enumerate(job.steps, start=1):
                if abort.is_set():
                    self._bus.publish(JobAborted(step=step.step, reason="abort flag"))
                    aborted = True
                    break
                if step_stop is not None and step.step > step_stop:
                    break
                self._bus.publish(StepStarted(step=step.step, task=step.task))
                self._dispatch(step, abort=abort)
                self._bus.publish(StepCompleted(step=step.step, task=step.task))
                self._bus.publish(Progress(current=idx, total=n))
                completed += 1
        finally:
            self._bus.publish(
                JobFinished(job_name=job.name, n_steps_completed=completed)
            )
        return JobResult(completed=completed, aborted=aborted)

    # ---------------------------------------------------------------- dispatch

    def _dispatch(self, step: Step, *, abort: AbortFlag) -> None:
        params = step.params
        task = step.task

        if task == "ligar":
            self._central.liga_alim_uasgs()
        elif task == "desligar":
            self._central.desliga_alim_uasgs()
        elif task == "ciclo":
            self._central.set_cycle(params["ciclo"])
        elif task == "chamada":
            chamada(
                self._central, self._units,
                ciclo=params.get("ciclo"),
                bus=self._bus, abort=abort, logs=self._logs,
            )
        elif task == "resistencia":
            res_contato(
                self._central, self._units, self._field, self._results,
                line=params.get("linha", 1),
                bus=self._bus, abort=abort,
            )
        elif task == "resistividade":
            self._run_resistividade(step, abort=abort, is_fullwave=False)
        elif task == "fullwave":
            self._run_resistividade(step, abort=abort, is_fullwave=True)
        elif task == "sev":
            sev(
                self._central, self._units, self._results,
                power_ma=params.get("corrente", 0),
                cicle_time=params.get("tempo", 7),
                step=step.step,
                is_fullwave=params.get("fullwave", False),
                bus=self._bus, abort=abort,
            )
        elif task == "sp":
            sp(
                self._central, self._units, self._field, self._results,
                eletrodo=params["eletrodo"],
                channel=params.get("canal", 1),
                line=params.get("linha", 1),
                step=step.step,
                is_fullwave=params.get("fullwave", True),
                bus=self._bus, abort=abort,
            )
        elif task == "distancias":
            self._field.reconfigure(
                n_electrodes=params["eletrodos"],
                spa_x=params.get("spa_x", 1),
                ini_x=params.get("ini_x", 0),
            )
        elif task == "eletrodos":
            self._field.set_redirects(params["eletrodos"])
        elif task == "datFile":
            self._results.save_dat(spa=params.get("spa", 2.5))
        elif task == "enderecos":
            if self._reload_addrs is None:
                raise NotImplementedError(
                    "task 'enderecos' requer um callback reload_addrs "
                    "(disponível via Session — fase 7)"
                )
            self._reload_addrs(params.get("arquivo"))
        elif task == "serial":
            if self._reconnect is None:
                raise NotImplementedError(
                    "task 'serial' requer um callback reconnect "
                    "(disponível via Session — fase 7)"
                )
            self._reconnect(params["porta"])
        else:
            # Loader já valida tasks; chegar aqui significa runner desatualizado.
            raise ValueError(f"task '{task}' não implementada no runner")

    def _run_resistividade(
        self, step: Step, *, abort: AbortFlag, is_fullwave: bool
    ) -> None:
        """Roda resistividade com retry: se o measurement devolver ``True``
        (n_pulsos baixo ou ciclo errou), reexecuta até ``self._retries`` vezes.
        """
        params = step.params
        for _ in range(self._retries + 1):
            failed = resistividade(
                self._central, self._units, self._field, self._results,
                electrodes=params["dipolo"],
                current_elec=params["config"],
                channels=params["canais"],
                line=params.get("linha", 1),
                power_ma=params.get("corrente", 0),
                ciclos=params.get("tempo", 10),
                step=step.step,
                is_fullwave=is_fullwave,
                bus=self._bus,
                abort=abort,
            )
            if not failed:
                return
