"""Testes da fachada ``delfos.Session``.

Cobrem ciclo (connect/disconnect/reconnect), execução de job ponta a ponta
com transport injetado, abort cooperativo, callbacks de tasks ``serial`` e
``enderecos``, e a superfície pública re-exportada por ``delfos``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import delfos
from delfos import (
    EventBus,
    Job,
    JobAborted,
    JobFinished,
    JobStarted,
    Session,
    Step,
    StepCompleted,
    StepStarted,
    load_job,
)
from delfos.protocol import Command

# =============================================================================
# Helpers
# =============================================================================


def _write_addr(p: Path, *, channel_id: int = 0x10) -> Path:
    p.write_text(
        "addr;kind;slot;channel;serial\n"
        f"0x{channel_id:02x}80;channel;;1;100\n"
        "0x20ff;switch;1;;200\n",
        encoding="utf-8",
    )
    return p


def _make_session(tmp_path, transport, **overrides) -> Session:
    addr = _write_addr(tmp_path / "addr.dat")
    kwargs = dict(
        line="L1",
        files_root=tmp_path / "out",
        addr_file=addr,
        n_electrodes=8,
        transport=transport,
    )
    kwargs.update(overrides)
    return Session(**kwargs)


# =============================================================================
# Ciclo: connect / disconnect / reconnect
# =============================================================================


def test_connect_creates_central_using_injected_transport(tmp_path, fake_transport):
    s = _make_session(tmp_path, fake_transport)

    assert s.is_connected is False
    with pytest.raises(RuntimeError):
        _ = s.central

    s.connect()
    assert s.is_connected is True
    assert s.central.transport is fake_transport


def test_disconnect_drops_central_but_does_not_close_injected_transport(
    tmp_path, fake_transport
):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    s.disconnect()

    assert s.is_connected is False
    # Transport injetado segue conectado — quem fez deve fechar.
    assert fake_transport.is_connected is True


def test_context_manager(tmp_path, fake_transport):
    s = _make_session(tmp_path, fake_transport)
    with s as session:
        assert session.is_connected is True
    assert s.is_connected is False


def test_reconnect_rejects_port_change_with_injected_transport(tmp_path, fake_transport):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    with pytest.raises(RuntimeError, match="transport injetado"):
        s.reconnect(port="COM99")


def test_connect_without_port_or_transport_fails(tmp_path):
    addr = _write_addr(tmp_path / "addr.dat")
    s = Session(line="L1", files_root=tmp_path / "out", addr_file=addr)
    with pytest.raises(RuntimeError, match="sem porta"):
        s.connect()


# =============================================================================
# Properties expõem os componentes
# =============================================================================


def test_properties_expose_components(tmp_path, fake_transport):
    s = _make_session(tmp_path, fake_transport)
    assert s.units is not None
    assert s.field.n_electrodes == 8
    assert s.results is not None
    assert s.logs is not None
    assert s.paths.line == "L1"
    assert isinstance(s.bus, EventBus)


# =============================================================================
# Pub/sub
# =============================================================================


def test_subscribe_receives_events_during_run_job(
    tmp_path, fake_transport, make_response
):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    received: list = []
    s.subscribe(received.append)

    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))

    job = Job(name="lifecycle", steps=[
        Step(step=1, task="ligar"),
        Step(step=2, task="desligar"),
    ])
    result = s.run_job(job)

    assert result.completed == 2
    assert result.aborted is False
    types = [type(e).__name__ for e in received]
    assert types[0] == "JobStarted"
    assert types[-1] == "JobFinished"
    assert {type(e) for e in received} >= {
        JobStarted, StepStarted, StepCompleted, JobFinished
    }


def test_unsubscribe_stops_delivery(tmp_path, fake_transport, make_response):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    received: list = []
    s.subscribe(received.append)
    s.unsubscribe(received.append)

    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    s.run_job(Job(name="x", steps=[Step(step=1, task="ligar")]))

    assert received == []


# =============================================================================
# run_job: base_name, results recriado, falha sem connect
# =============================================================================


def test_run_job_requires_connect(tmp_path, fake_transport):
    s = _make_session(tmp_path, fake_transport)
    with pytest.raises(RuntimeError, match="connect"):
        s.run_job(Job(name="x", steps=[]))


def test_run_job_recreates_results_with_job_name(tmp_path, fake_transport, make_response):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    initial_results = s.results
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))

    s.run_job(Job(name="meu_job", steps=[Step(step=1, task="ligar")]))

    assert s.results is not initial_results
    assert s.results.base_name == "meu_job"
    assert s.logs.base_name == "meu_job"


def test_run_job_base_name_override(tmp_path, fake_transport, make_response):
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))

    s.run_job(
        Job(name="meu_job", steps=[Step(step=1, task="ligar")]),
        base_name="custom",
    )
    assert s.results.base_name == "custom"


# =============================================================================
# Abort cooperativo
# =============================================================================


def test_abort_during_job_stops_subsequent_steps(
    tmp_path, fake_transport, make_response
):
    """Abort sinalizado durante a execução interrompe antes do próximo step."""
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))

    received: list = []

    def on_event(evt):
        received.append(evt)
        # Aborta logo após o primeiro step terminar — simula clique no UI.
        if isinstance(evt, StepCompleted) and evt.step == 1:
            s.abort()

    s.subscribe(on_event)
    result = s.run_job(Job(name="x", steps=[
        Step(step=1, task="ligar"),
        Step(step=2, task="desligar"),  # não chega a rodar
    ]))

    assert result.aborted is True
    assert result.completed == 1
    assert any(isinstance(e, JobAborted) for e in received)


def test_abort_clears_between_runs(tmp_path, fake_transport, make_response):
    """``run_job`` reseta a flag — um job seguinte parte limpo, mesmo após
    chamada órfã de ``abort()``."""
    s = _make_session(tmp_path, fake_transport)
    s.connect()
    s.abort()  # chamada fora de qualquer job — deve ser ignorada pelo próximo run.

    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    result = s.run_job(Job(name="ok", steps=[Step(step=1, task="ligar")]))
    assert result.aborted is False
    assert result.completed == 1


# =============================================================================
# Task `enderecos` recarrega Units in-place
# =============================================================================


def test_enderecos_task_reloads_units_in_place(tmp_path, fake_transport):
    addr1 = _write_addr(tmp_path / "addr.dat", channel_id=0x10)
    s = Session(
        line="L1",
        files_root=tmp_path / "out",
        addr_file=addr1,
        n_electrodes=8,
        transport=fake_transport,
    )
    s.connect()

    # Cria second.dat em paths.system
    s.paths.system.mkdir(parents=True, exist_ok=True)
    second = s.paths.system / "second.dat"
    second.write_text(
        "addr;kind;slot;channel;serial\n"
        "0x4280;channel;;1;999\n",
        encoding="utf-8",
    )

    units_obj = s.units
    assert int(units_obj.df.loc[1, "addr"]) == 0x1080

    s.run_job(Job(name="reload", steps=[
        Step(step=1, task="enderecos", params={"arquivo": "second"}),
    ]))

    # Mesma instância, conteúdo novo.
    assert s.units is units_obj
    assert int(s.units.df.loc[1, "addr"]) == 0x4280


# =============================================================================
# Re-exports públicos
# =============================================================================


def test_public_api_reexported():
    expected = {
        "Session",
        "load_job",
        "Job",
        "JobResult",
        "Step",
        "EventBus",
        "NullBus",
        "Event",
        "JobStarted",
        "StepStarted",
        "StepCompleted",
        "Progress",
        "UnitResponse",
        "MeasurementSample",
        "JobAborted",
        "JobFinished",
        "ErrorEvent",
    }
    assert expected.issubset(set(delfos.__all__))
    for name in expected:
        assert hasattr(delfos, name), f"delfos.{name} ausente"


def test_load_job_smoke_via_public_import(tmp_path):
    job_path = tmp_path / "j.json"
    job_path.write_text(
        '{"name":"t","steps":[{"step":1,"task":"ligar"}]}',
        encoding="utf-8",
    )
    job = load_job(job_path)
    assert isinstance(job, Job)
    assert job.steps[0].task == "ligar"
