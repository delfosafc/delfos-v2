"""Testes do CLI Typer.

Usam ``typer.testing.CliRunner`` e monkeypatch dos pontos de criação de
``SerialTransport`` / ``available_ports`` no módulo ``delfos.cli._app`` para
isolar o CLI da camada física.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from delfos.cli import app
from delfos.protocol import Command


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_addr(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "id;end1;end2;serial;order;channel\n"
        "1;0x10;0x80;100;0;1\n"
        "2;0x20;0xff;200;1;255\n",
        encoding="utf-8",
    )
    return p


# =============================================================================
# --help / argless
# =============================================================================


def test_help_lists_all_commands(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("ports", "ping", "status", "chamada", "contato", "run"):
        assert cmd in result.stdout


def test_no_args_shows_help(runner):
    result = runner.invoke(app, [])
    # no_args_is_help=True faz Typer sair com 2 mas mostrando help
    assert result.exit_code in (0, 2)
    assert "Commands" in result.stdout or "Usage" in result.stdout


# =============================================================================
# ports
# =============================================================================


def test_ports_lists_available(runner, monkeypatch):
    monkeypatch.setattr(
        "delfos.cli._app.available_ports", lambda: ["COM5", "/dev/ttyUSB0"]
    )
    result = runner.invoke(app, ["ports"])
    assert result.exit_code == 0
    assert "COM5" in result.stdout
    assert "ttyUSB0" in result.stdout


def test_ports_empty(runner, monkeypatch):
    monkeypatch.setattr("delfos.cli._app.available_ports", lambda: [])
    result = runner.invoke(app, ["ports"])
    assert result.exit_code == 0
    assert "nenhuma" in result.stdout.lower()


# =============================================================================
# ping / status — exigem porta
# =============================================================================


def test_ping_without_port_fails(runner):
    # Sem DELFOS_PORT no env do CliRunner, deve sair com 2.
    result = runner.invoke(app, ["ping"], env={"DELFOS_PORT": ""})
    assert result.exit_code == 2
    assert "porta" in result.stdout.lower()


def _patch_serial_transport(monkeypatch, fake_transport):
    """Substitui SerialTransport nos módulos que constroem transport real
    (CLI direto, e Session) por uma factory que devolve o FakeTransport."""
    def _factory(port, *, baudrate=115200, timeout=0.1):
        fake_transport.last_port = port
        return fake_transport

    monkeypatch.setattr("delfos.cli._app.SerialTransport", _factory)
    monkeypatch.setattr("delfos.session.SerialTransport", _factory)


def test_ping_command(runner, monkeypatch, fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(app, ["ping", "--port", "COM5"])
    assert result.exit_code == 0
    assert "ack" in result.stdout
    assert fake_transport.last_port == "COM5"


def test_status_command(runner, monkeypatch, fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(app, ["status", "--port", "COM5"])
    assert result.exit_code == 0
    assert "porta" in result.stdout
    assert "COM5" in result.stdout


def test_port_via_envvar(runner, monkeypatch, fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(app, ["ping"], env={"DELFOS_PORT": "COM7"})
    assert result.exit_code == 0
    assert fake_transport.last_port == "COM7"


# =============================================================================
# run — exige addr.dat
# =============================================================================


def test_run_executes_job(
    runner, monkeypatch, tmp_path, fake_transport, make_response
):
    addr = _write_addr(tmp_path / "system" / "addr.dat")
    job_path = tmp_path / "j.json"
    job_path.write_text(
        '{"name":"smoke","steps":['
        '{"step":1,"task":"ligar"},'
        '{"step":2,"task":"desligar"}'
        ']}',
        encoding="utf-8",
    )
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(
        app,
        [
            "run",
            str(job_path),
            "--port", "COM5",
            "--line", "L1",
            "--files-root", str(tmp_path / "out"),
            "--addr-file", str(addr),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "smoke" in result.stdout
    # Confirma que os 2 frames foram enviados.
    assert len(fake_transport.writes) == 2


def test_run_step_stop(
    runner, monkeypatch, tmp_path, fake_transport, make_response
):
    addr = _write_addr(tmp_path / "system" / "addr.dat")
    job_path = tmp_path / "j.json"
    job_path.write_text(
        '{"name":"sj","steps":['
        '{"step":1,"task":"ligar"},'
        '{"step":2,"task":"desligar"}'
        ']}',
        encoding="utf-8",
    )
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(
        app,
        [
            "run",
            str(job_path),
            "--port", "COM5",
            "--step-stop", "1",
            "--line", "L1",
            "--files-root", str(tmp_path / "out"),
            "--addr-file", str(addr),
        ],
    )
    assert result.exit_code == 0
    # Apenas o primeiro step foi enviado.
    assert len(fake_transport.writes) == 1


def test_run_missing_job_file(runner, tmp_path):
    result = runner.invoke(
        app,
        ["run", str(tmp_path / "missing.json"), "--port", "COM5"],
    )
    # Argument(exists=True) faz Typer rejeitar com 2 antes de tocar serial.
    assert result.exit_code == 2


# =============================================================================
# chamada / contato — smoke (mockando measurement)
# =============================================================================


def test_chamada_command_smoke(
    runner, monkeypatch, tmp_path, fake_transport
):
    """chamada chama a função measurements.chamada — stubamos essa função
    no módulo do runner para evitar trocas reais com a Central."""
    addr = _write_addr(tmp_path / "system" / "addr.dat")
    calls: list = []
    monkeypatch.setattr(
        "delfos.jobs.runner.chamada",
        lambda *a, **kw: calls.append(("chamada", kw)),
    )
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(
        app,
        [
            "chamada",
            "--port", "COM5",
            "--ciclo", "54",
            "--line", "L1",
            "--files-root", str(tmp_path / "out"),
            "--addr-file", str(addr),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls and calls[0][1].get("ciclo") == 54


def test_contato_command_smoke(
    runner, monkeypatch, tmp_path, fake_transport
):
    addr = _write_addr(tmp_path / "system" / "addr.dat")
    calls: list = []
    monkeypatch.setattr(
        "delfos.jobs.runner.res_contato",
        lambda *a, **kw: calls.append(("res_contato", kw)),
    )
    _patch_serial_transport(monkeypatch, fake_transport)

    result = runner.invoke(
        app,
        [
            "contato",
            "--port", "COM5",
            "--linha", "2",
            "--line", "L1",
            "--files-root", str(tmp_path / "out"),
            "--addr-file", str(addr),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls and calls[0][1].get("line") == 2
