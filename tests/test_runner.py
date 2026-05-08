"""Testes do JobRunner — usa stubs nos measurements para isolar dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from delfos.central import Central
from delfos.events import (
    EventBus,
    JobAborted,
    JobFinished,
    JobStarted,
    StepCompleted,
)
from delfos.field import Field
from delfos.jobs import Job, JobRunner, Step
from delfos.protocol import Command
from delfos.storage import Paths, ResultsStore
from delfos.units import Units

# =============================================================================
# Helpers e stubs
# =============================================================================


def _write_addr(p: Path) -> Path:
    p.write_text(
        "id;end1;end2;serial;order;channel\n"
        "1;0x10;0x80;100;0;1\n"
        "2;0x20;0xff;200;1;255\n",
        encoding="utf-8",
    )
    return p


class _Recorder:
    """Stub callable que registra args/kwargs e devolve um valor configurável."""

    def __init__(self, return_values=None):
        self.calls: list[tuple[tuple, dict]] = []
        self._returns = list(return_values) if return_values is not None else []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._returns:
            return self._returns.pop(0)
        return None


@pytest.fixture
def runner_setup(tmp_path, fake_transport):
    units = Units.load(_write_addr(tmp_path / "addr.dat"))
    field = Field(n_electrodes=8, spa_x=1.0)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="job")
    central = Central(fake_transport)
    return central, units, field, results


# =============================================================================
# Lifecycle: eventos publicados
# =============================================================================


def test_emits_lifecycle_events(runner_setup, fake_transport, make_response):
    central, units, field, results = runner_setup
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))

    received: list = []
    bus = EventBus()
    bus.subscribe(received.append)

    runner = JobRunner(central, units, field, results, bus=bus)
    job = Job(name="lifecycle", steps=[
        Step(step=1, task="ligar"),
        Step(step=2, task="desligar"),
    ])
    result = runner.run(job)

    types = [type(e).__name__ for e in received]
    assert types == [
        "JobStarted",
        "StepStarted", "StepCompleted", "Progress",
        "StepStarted", "StepCompleted", "Progress",
        "JobFinished",
    ]
    assert isinstance(received[0], JobStarted)
    assert received[0].n_steps == 2
    assert isinstance(received[-1], JobFinished)
    assert received[-1].n_steps_completed == 2
    assert result.completed == 2
    assert result.aborted is False


# =============================================================================
# Tasks que vão direto pelo Central (ligar/desligar/ciclo)
# =============================================================================


def test_dispatch_ligar_desligar_ciclo(runner_setup, fake_transport, make_response):
    central, units, field, results = runner_setup
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0xFFFD, Command.SET_CYCLE_PERIOD))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="ligar"),
        Step(step=2, task="ciclo", params={"ciclo": 0x36}),
        Step(step=3, task="desligar"),
    ]))

    assert fake_transport.writes[0][3] == 0x4B  # LIGA_ALIM_UASGS
    assert fake_transport.writes[1][3] == 0x42  # SET_CYCLE_PERIOD
    assert fake_transport.writes[1][4] == 0x36
    assert fake_transport.writes[2][3] == 0x59  # DESLIGA_ALIM_UASGS


# =============================================================================
# Dispatch para measurements (com stubs)
# =============================================================================


def test_dispatch_chamada(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    rec = _Recorder()
    monkeypatch.setattr("delfos.jobs.runner.chamada", rec)

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="chamada", params={"ciclo": 0x36}),
    ]))

    assert len(rec.calls) == 1
    _, kwargs = rec.calls[0]
    assert kwargs["ciclo"] == 0x36


def test_dispatch_resistencia(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    rec = _Recorder()
    monkeypatch.setattr("delfos.jobs.runner.res_contato", rec)

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="resistencia", params={"linha": 2}),
    ]))

    assert rec.calls[0][1]["line"] == 2


def test_dispatch_resistividade_passes_params(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    rec = _Recorder(return_values=[False])
    monkeypatch.setattr("delfos.jobs.runner.resistividade", rec)

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=4, task="resistividade", params={
            "config": [1, 4],
            "dipolo": [2, 3, -1, -1, -1, -1, -1, -1, -1],
            "canais": [1],
            "tempo": 10,
            "corrente": 100,
            "linha": 2,
        }),
    ]))

    kwargs = rec.calls[0][1]
    assert kwargs["electrodes"] == [2, 3, -1, -1, -1, -1, -1, -1, -1]
    assert kwargs["current_elec"] == [1, 4]
    assert kwargs["channels"] == [1]
    assert kwargs["ciclos"] == 10
    assert kwargs["power_ma"] == 100
    assert kwargs["line"] == 2
    assert kwargs["is_fullwave"] is False


def test_dispatch_fullwave_sets_is_fullwave_true(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    rec = _Recorder(return_values=[False])
    monkeypatch.setattr("delfos.jobs.runner.resistividade", rec)

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=4, task="fullwave", params={
            "config": [1, 4], "dipolo": [2, 3] + [-1] * 7, "canais": [1],
        }),
    ]))

    assert rec.calls[0][1]["is_fullwave"] is True


def test_resistividade_retries_on_failure(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    # Primeira chamada falha (True), segunda sucede (False)
    rec = _Recorder(return_values=[True, False])
    monkeypatch.setattr("delfos.jobs.runner.resistividade", rec)

    runner = JobRunner(central, units, field, results, resistividade_retries=1)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="resistividade", params={
            "config": [1, 4], "dipolo": [2, 3] + [-1] * 7, "canais": [1],
        }),
    ]))
    assert len(rec.calls) == 2


def test_resistividade_gives_up_after_retries(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    rec = _Recorder(return_values=[True, True, True])
    monkeypatch.setattr("delfos.jobs.runner.resistividade", rec)

    runner = JobRunner(central, units, field, results, resistividade_retries=1)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="resistividade", params={
            "config": [1, 4], "dipolo": [2, 3] + [-1] * 7, "canais": [1],
        }),
    ]))
    # 1 inicial + 1 retry = 2 chamadas
    assert len(rec.calls) == 2


# =============================================================================
# Tasks de configuração (distancias, eletrodos)
# =============================================================================


def test_dispatch_distancias_reconfigures_field(runner_setup):
    central, units, field, results = runner_setup
    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="distancias",
             params={"eletrodos": 16, "spa_x": 5, "ini_x": 0}),
    ]))
    assert field.n_electrodes == 16
    assert field.spa_x == 5


def test_dispatch_eletrodos_sets_redirects(runner_setup):
    central, units, field, results = runner_setup
    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="eletrodos", params={"eletrodos": {"5": 1, "6": 2}}),
    ]))
    assert field.redirected_electrodes == {5: 1, 6: 2}


def test_dispatch_datfile_calls_save_dat(runner_setup, monkeypatch):
    central, units, field, results = runner_setup
    calls: list[float] = []
    monkeypatch.setattr(
        results, "save_dat",
        lambda *, spa: calls.append(spa),
    )

    runner = JobRunner(central, units, field, results)
    runner.run(Job(name="t", steps=[
        Step(step=1, task="datFile", params={"spa": 5}),
    ]))
    assert calls == [5]


# =============================================================================
# Tasks que precisam de callback externo
# =============================================================================


def test_serial_without_callback_raises(runner_setup):
    central, units, field, results = runner_setup
    runner = JobRunner(central, units, field, results)
    with pytest.raises(NotImplementedError, match="reconnect"):
        runner.run(Job(name="t", steps=[
            Step(step=1, task="serial", params={"porta": "COM5"}),
        ]))


def test_serial_uses_reconnect_callback(runner_setup):
    central, units, field, results = runner_setup
    calls: list[str] = []
    runner = JobRunner(
        central, units, field, results,
        reconnect=lambda port: calls.append(port),
    )
    runner.run(Job(name="t", steps=[
        Step(step=1, task="serial", params={"porta": "COM5"}),
    ]))
    assert calls == ["COM5"]


def test_enderecos_without_callback_raises(runner_setup):
    central, units, field, results = runner_setup
    runner = JobRunner(central, units, field, results)
    with pytest.raises(NotImplementedError, match="reload_addrs"):
        runner.run(Job(name="t", steps=[
            Step(step=1, task="enderecos", params={"arquivo": "addr2"}),
        ]))


# =============================================================================
# Abort e step_stop
# =============================================================================


class _ManualAbort:
    def __init__(self):
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def trigger(self):
        self._set = True


def test_aborts_mid_job(runner_setup, fake_transport, make_response):
    central, units, field, results = runner_setup
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))

    abort = _ManualAbort()
    received: list = []
    bus = EventBus()

    def listener(event):
        received.append(event)
        if isinstance(event, StepCompleted) and event.step == 1:
            abort.trigger()

    bus.subscribe(listener)

    runner = JobRunner(central, units, field, results, bus=bus)
    result = runner.run(
        Job(name="t", steps=[
            Step(step=1, task="ligar"),
            Step(step=2, task="desligar"),  # nunca executa
        ]),
        abort=abort,
    )
    assert result.aborted is True
    assert result.completed == 1
    assert any(isinstance(e, JobAborted) for e in received)


def test_step_stop_limits_execution(runner_setup, fake_transport, make_response):
    central, units, field, results = runner_setup
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))

    runner = JobRunner(central, units, field, results)
    result = runner.run(
        Job(name="t", steps=[
            Step(step=1, task="ligar"),
            Step(step=10, task="desligar"),
        ]),
        step_stop=5,  # step.step (10) > 5 → para
    )
    assert result.completed == 1


# =============================================================================
# Integração com loader.validate
# =============================================================================


def test_loader_rejects_removed_task(tmp_path):
    import json

    from delfos.jobs import load_job
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"step": 1, "task": "sismica"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="sismica.*removida"):
        load_job(p)


def test_loader_rejects_unknown_task(tmp_path):
    import json

    from delfos.jobs import load_job
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps([{"step": 1, "task": "fubar"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="desconhecida"):
        load_job(p)
