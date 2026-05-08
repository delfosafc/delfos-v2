"""API pública: ``Session`` compõe transport + central + units + field +
results + logs + event bus em um único ponto de entrada.

Uso típico::

    from delfos import Session, load_job
    s = Session(port="COM5", line="L1")
    s.connect()
    s.subscribe(print)
    s.run_job(load_job("contato.json"))

Para testes ou uso com transporte alternativo, passe ``transport=`` (qualquer
objeto compatível com ``SerialTransport``: ``write/read/set_timeout/timeout``).
Quando o transport é injetado, ``connect``/``disconnect`` apenas instanciam ou
descartam o ``Central`` que o envolve — o ciclo de vida do transporte é do
chamador.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from delfos.central import Central
from delfos.events import Event, EventBus
from delfos.field import Field
from delfos.jobs.runner import JobResult, JobRunner
from delfos.jobs.schema import Job
from delfos.storage import LogWriter, Paths, ResultsStore
from delfos.transport import SerialTransport
from delfos.units import Units


class Session:
    """Fachada estável da biblioteca. Tudo que vive em ``delfos.*`` público
    passa por aqui."""

    def __init__(
        self,
        *,
        port: str | None = None,
        baudrate: int = 115200,
        line: str = "data",
        files_root: str | Path | None = None,
        addr_file: str | Path | None = None,
        n_electrodes: int = 32,
        spa_x: float = 1.0,
        n_tries: int = 5,
        transport: Any = None,
        units: Units | None = None,
        field: Field | None = None,
    ):
        self._port = port
        self._baudrate = baudrate
        self._n_tries = n_tries

        self._paths = Paths(files_root=files_root, line=line)

        if units is None:
            addr_path = Path(addr_file) if addr_file else self._paths.addr_dat
            units = Units.load(addr_path)
        self._units = units

        self._field = field if field is not None else Field(
            n_electrodes=n_electrodes, spa_x=spa_x
        )

        # Results e logs nascem com base_name = line; run_job recria com job.name.
        self._results = ResultsStore(self._paths, base_name=line)
        self._logs = LogWriter(self._paths, base_name=line)

        self._bus = EventBus()
        self._abort = threading.Event()

        self._owns_transport = transport is None
        self._transport: Any = transport
        self._central: Central | None = None

    # ------------------------------------------------------------------ ciclo

    def connect(self) -> None:
        """Abre o transporte (se for próprio) e cria o ``Central``."""
        if self._central is not None:
            return
        if self._transport is None:
            if self._port is None:
                raise RuntimeError(
                    "Session sem porta nem transport — passe `port=...` ou `transport=...`"
                )
            self._transport = SerialTransport(self._port, baudrate=self._baudrate)
        if hasattr(self._transport, "is_connected") and not self._transport.is_connected:
            self._transport.connect()
        self._central = Central(self._transport, n_tries=self._n_tries)

    def disconnect(self) -> None:
        """Descarta o ``Central``; fecha o transporte se for próprio."""
        if self._owns_transport and self._transport is not None:
            try:
                self._transport.disconnect()
            finally:
                self._transport = None
        self._central = None

    def reconnect(self, port: str | None = None) -> None:
        """Recria a conexão. Quando o transport é injetado, só faz sentido
        sem trocar de porta — passar ``port`` nesse caso é erro."""
        if not self._owns_transport:
            if port is not None:
                raise RuntimeError(
                    "Session com transport injetado: reconnect com porta nova "
                    "não é suportado — recrie a Session"
                )
            self._central = Central(self._transport, n_tries=self._n_tries)
            return
        if port is not None:
            self._port = port
        self.disconnect()
        self.connect()

    def __enter__(self) -> Session:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    # -------------------------------------------------------------- properties

    @property
    def is_connected(self) -> bool:
        return self._central is not None

    @property
    def central(self) -> Central:
        if self._central is None:
            raise RuntimeError("Session: chame connect() antes de acessar central")
        return self._central

    @property
    def units(self) -> Units:
        return self._units

    @property
    def field(self) -> Field:
        return self._field

    @property
    def results(self) -> ResultsStore:
        return self._results

    @property
    def logs(self) -> LogWriter:
        return self._logs

    @property
    def paths(self) -> Paths:
        return self._paths

    @property
    def bus(self) -> EventBus:
        return self._bus

    # ------------------------------------------------------------- pub/sub

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._bus.subscribe(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        self._bus.unsubscribe(callback)

    # ------------------------------------------------------------- execução

    def run_job(
        self,
        job: Job,
        *,
        step_stop: int | None = None,
        base_name: str | None = None,
    ) -> JobResult:
        """Executa ``job`` recriando results+logs com ``base_name = job.name``
        (ou o override). Limpa a flag de abort antes de iniciar."""
        if self._central is None:
            raise RuntimeError("Session.run_job: chame connect() antes")
        self._abort.clear()
        name = base_name or job.name
        self._results = ResultsStore(self._paths, base_name=name)
        self._logs = LogWriter(self._paths, base_name=name)
        if job.field:
            self._field.reconfigure(**{
                k: v for k, v in job.field.items()
                if k in ("n_electrodes", "spa_x", "spa_y", "ini_x", "ini_y")
            })
            # alias de schema TOML: `eletrodos` (PT) → `n_electrodes`
            if "eletrodos" in job.field:
                self._field.reconfigure(n_electrodes=job.field["eletrodos"])
        runner = JobRunner(
            self._central,
            self._units,
            self._field,
            self._results,
            bus=self._bus,
            logs=self._logs,
            reconnect=self._on_serial_task,
            reload_addrs=self._on_addrs_task,
        )
        return runner.run(job, abort=self._abort, step_stop=step_stop)

    def abort(self) -> None:
        """Sinaliza abort cooperativo para o job em execução."""
        self._abort.set()

    # ---------------------------------------------------- callbacks p/ runner

    def _on_serial_task(self, port: str) -> None:
        self.reconnect(port=port)

    def _on_addrs_task(self, arquivo: str | None) -> None:
        path = self._resolve_addr_file(arquivo)
        self._units.reload(path)

    def _resolve_addr_file(self, arquivo: str | Path | None) -> Path:
        """Resolve o argumento da task ``enderecos``:
        - ``None`` → ``paths.addr_dat`` (default)
        - caminho absoluto → usa direto
        - relativo → procura em ``paths.system``; adiciona ``.dat`` se faltar
        """
        if arquivo is None:
            return self._paths.addr_dat
        p = Path(arquivo)
        if p.is_absolute():
            return p
        candidate = self._paths.system / p
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".dat")
        return candidate
