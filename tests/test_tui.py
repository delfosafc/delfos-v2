"""Smoke tests da TUI Textual.

Cobertura:
- Importação e instanciação básica.
- Tela de conexão renderiza widgets esperados.
- Fluxo ponta a ponta com transport injetado: conecta, seleciona job e
  roda até ``JobFinished`` aparecer no log.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from delfos.protocol import Command
from delfos.tui import DelfosApp

# =============================================================================
# Helpers
# =============================================================================


def _write_addr(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "addr;kind;slot;channel;serial\n"
        "0x1080;channel;;1;100\n"
        "0x20ff;switch;1;;200\n",
        encoding="utf-8",
    )
    return p


def _write_job(p: Path, name: str = "smoke") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"name":"' + name + '","steps":['
        '{"step":1,"task":"ligar"},'
        '{"step":2,"task":"desligar"}'
        ']}',
        encoding="utf-8",
    )
    return p


def _arun(coro):
    """Roda coroutine no pytest síncrono — evita dep extra de pytest-asyncio."""
    return asyncio.run(coro)


# =============================================================================
# Smoke
# =============================================================================


def test_imports():
    from delfos.tui import DelfosApp, run  # noqa: F401


def test_app_instantiates():
    app = DelfosApp()
    assert app.session is None
    assert app.injected_transport is None


def test_app_with_defaults_and_transport(fake_transport):
    app = DelfosApp(
        defaults={"port": "COM5", "line": "L1"},
        injected_transport=fake_transport,
    )
    assert app.injected_transport is fake_transport


# =============================================================================
# Pilot — fluxo de conexão
# =============================================================================


def test_connection_screen_renders():
    async def _drive():
        app = DelfosApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import Input

            inputs = list(app.screen.query(Input))
            ids = {i.id for i in inputs}
            assert {"port", "line", "files_root", "addr_file"} <= ids

    _arun(_drive())


def test_full_flow_runs_job_with_fake_transport(tmp_path, fake_transport, make_response):
    """Conecta com transport injetado, seleciona job, executa e confirma
    que o JobFinished foi escrito no log."""
    addr = _write_addr(tmp_path / "files" / "system" / "addr.dat")
    _write_job(tmp_path / "files" / "system" / "jobs" / "smoke.json")
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))

    app = DelfosApp(
        defaults={
            "port": "FAKE",
            "line": "L1",
            "files_root": str(tmp_path / "files"),
            "addr_file": str(addr),
        },
        injected_transport=fake_transport,
    )

    async def _drive():
        from textual.widgets import Button, ListView, RichLog

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Tela 1: clica em Conectar (defaults já preenchem inputs).
            await pilot.click("#connect")
            await pilot.pause()
            # Tela 2: seleciona o primeiro job e executa.
            jobs_list = app.screen.query_one("#jobs_list", ListView)
            assert len(jobs_list) >= 1, "ListView vazia — jobs não foram listados"
            jobs_list.index = 0
            await pilot.pause()
            await pilot.click("#run_job")
            # Tela 3: espera o worker thread terminar.
            for _ in range(80):  # até ~4s
                await pilot.pause()
                # Pode ter saído da tela em algum caso de erro precoce.
                screen = app.screen
                if screen.__class__.__name__ != "ExecutionScreen":
                    continue
                btn = screen.query_one("#abort", Button)
                if btn.disabled:
                    break
                await asyncio.sleep(0.05)
            screen = app.screen
            assert screen.__class__.__name__ == "ExecutionScreen"
            log = screen.query_one("#log", RichLog)
            text = "\n".join(str(line) for line in log.lines)
            assert "smoke" in text
            assert "passos completados" in text or "✓" in text

    _arun(_drive())
