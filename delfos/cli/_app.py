"""App Typer com os subcomandos do CLI.

Cada comando é uma função fina sobre ``Session`` (ou diretamente sobre
``Central`` quando o comando não precisa de ``addr.dat`` carregada). Saída
humana via ``rich``. ``--port`` aceita ``DELFOS_PORT`` como fallback.

Comandos:
    ports                          lista portas seriais
    ping     [--port]              ping na Central (não exige addr.dat)
    status   [--port]              ping detalhado (firmware, estado, status)
    chamada  [--port --ciclo ...]  chamada em todas UASGs
    contato  [--port --linha ...]  resistência de contato
    run JOB  [--port --step-stop]  executa job JSON
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from delfos import (
    JobAborted,
    JobFinished,
    JobStarted,
    Progress,
    Session,
    StepStarted,
    UnitResponse,
    load_job,
)
from delfos.central import Central
from delfos.transport import SerialTransport, available_ports

app = typer.Typer(
    name="delfos",
    help="CLI para o equipamento Delfos (Central + UASGs) via porta serial.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# ----------------------------------------------------------------------- options
# Singletons module-level — Typer exige instâncias de Option/Argument como
# default; usar factories dispararia B008 do bugbear em cada subcomando.

PORT_OPT = typer.Option(
    None,
    "--port",
    "-p",
    envvar="DELFOS_PORT",
    help="Porta serial (ex.: COM5, /dev/ttyUSB0). Lê DELFOS_PORT se omitido.",
)
LINE_OPT = typer.Option(
    "data", "--line", "-l", help="Subpasta de saída em files/<line>/."
)
FILES_OPT = typer.Option(
    None,
    "--files-root",
    help="Raiz de files/. Default: ./files relativo ao CWD.",
)
ADDR_OPT = typer.Option(
    None,
    "--addr-file",
    help="Caminho do addr.dat. Default: <files-root>/system/addr.dat.",
)
JOB_ARG = typer.Argument(..., exists=True, dir_okay=False, help="Caminho do .json.")
CICLO_OPT = typer.Option(None, "--ciclo", help="Multiplicador do PLL.")
LINHA_OPT = typer.Option(1, "--linha", help="Linha do dipolo (1=data, 2=power).")
STEP_STOP_OPT = typer.Option(
    None, "--step-stop", help="Para após este step (inclusive)."
)


# ------------------------------------------------------------------- helpers


def _require_port(port: str | None) -> str:
    if port is None:
        console.print(
            "[red]erro:[/] porta não informada. "
            "Use --port ou defina DELFOS_PORT."
        )
        raise typer.Exit(code=2)
    return port


def _make_session(
    *,
    port: str,
    line: str,
    files_root: Path | None,
    addr_file: Path | None,
) -> Session:
    return Session(
        port=port,
        line=line,
        files_root=files_root,
        addr_file=addr_file,
    )


# =============================================================================
# Comandos sem addr.dat
# =============================================================================


@app.command(help="Lista portas seriais disponíveis.")
def ports() -> None:
    found = available_ports()
    if not found:
        console.print("[yellow]nenhuma porta encontrada[/]")
        return
    table = Table(title="Portas seriais")
    table.add_column("#", justify="right")
    table.add_column("porta")
    for i, p in enumerate(found, start=1):
        table.add_row(str(i), p)
    console.print(table)


@app.command(help="Ping curto na Central — confirma comunicação.")
def ping(port: str = PORT_OPT) -> None:
    port_ = _require_port(port)
    transport = SerialTransport(port_)
    transport.connect()
    try:
        central = Central(transport)
        resp = central.ping_central()
    finally:
        transport.disconnect()
    state = resp.system_state.name if resp.system_state else f"raw={resp.system_state_raw}"
    err = resp.error.name if resp.error else f"raw={resp.error_raw}"
    color = "green" if resp.is_ack else "yellow"
    console.print(f"[{color}]ack[/] state={state} error={err} sw=0x{resp.sw_version:02x}")


@app.command(help="Status detalhado da Central (ping com mais campos).")
def status(port: str = PORT_OPT) -> None:
    port_ = _require_port(port)
    transport = SerialTransport(port_)
    transport.connect()
    try:
        central = Central(transport)
        resp = central.ping_central()
    finally:
        transport.disconnect()
    table = Table(show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("porta", port_)
    table.add_row("ack", "sim" if resp.is_ack else "não")
    table.add_row("sw_version", f"0x{resp.sw_version:02x}")
    table.add_row(
        "system_state",
        resp.system_state.name if resp.system_state else f"raw={resp.system_state_raw}",
    )
    table.add_row("error", resp.error.name if resp.error else f"raw={resp.error_raw}")
    table.add_row("status_geral", repr(resp.status_geral))
    table.add_row("status_geral1", repr(resp.status_geral1))
    console.print(table)


# =============================================================================
# Comandos sobre Session (precisam de addr.dat)
# =============================================================================


def _run_inline_job(
    session: Session,
    *,
    job_name: str,
    steps: list[dict],
) -> None:
    """Roda um job montado in-process via Session, com feedback rich."""
    from delfos import Job, Step

    job = Job(
        name=job_name,
        steps=[Step(step=s["step"], task=s["task"], params=s.get("params", {})) for s in steps],
    )
    _attach_progress(session)
    result = session.run_job(job)
    _print_result(result)


def _attach_progress(session: Session) -> None:
    """Inscreve subscriber simples que loga eventos relevantes."""

    def on_event(evt) -> None:
        if isinstance(evt, JobStarted):
            console.print(f"[bold]▶ job '{evt.job_name}'[/] ({evt.n_steps} passos)")
        elif isinstance(evt, StepStarted):
            console.print(f"  [cyan]→[/] step {evt.step} [{evt.task}]")
        elif isinstance(evt, Progress):
            console.print(f"  [dim]{evt.current}/{evt.total} ({evt.percent}%)[/]")
        elif isinstance(evt, UnitResponse):
            mark = "[green]✓[/]" if evt.success else "[red]✗[/]"
            console.print(f"    {mark} unit {evt.unit_id} {evt.detail}")
        elif isinstance(evt, JobAborted):
            console.print(f"[yellow]⚠ abortado no step {evt.step}[/] ({evt.reason})")
        elif isinstance(evt, JobFinished):
            console.print(
                f"[bold green]✓ job '{evt.job_name}'[/] "
                f"({evt.n_steps_completed} steps completados)"
            )

    session.subscribe(on_event)


def _print_result(result) -> None:
    if result.aborted:
        raise typer.Exit(code=1)


@app.command(help="Chamada em todas as UASGs.")
def chamada(
    port: str = PORT_OPT,
    ciclo: int | None = CICLO_OPT,
    line: str = LINE_OPT,
    files_root: Path | None = FILES_OPT,
    addr_file: Path | None = ADDR_OPT,
) -> None:
    port_ = _require_port(port)
    session = _make_session(
        port=port_, line=line, files_root=files_root, addr_file=addr_file
    )
    with session:
        params = {"ciclo": ciclo} if ciclo is not None else {}
        _run_inline_job(
            session,
            job_name="chamada",
            steps=[{"step": 1, "task": "chamada", "params": params}],
        )


@app.command(help="Resistência de contato.")
def contato(
    port: str = PORT_OPT,
    linha: int = LINHA_OPT,
    line: str = LINE_OPT,
    files_root: Path | None = FILES_OPT,
    addr_file: Path | None = ADDR_OPT,
) -> None:
    port_ = _require_port(port)
    session = _make_session(
        port=port_, line=line, files_root=files_root, addr_file=addr_file
    )
    with session:
        _run_inline_job(
            session,
            job_name="contato",
            steps=[{"step": 1, "task": "resistencia", "params": {"linha": linha}}],
        )
        session.results.save_resistance()


@app.command(help="Executa um job JSON.")
def run(
    job_path: Path = JOB_ARG,
    port: str = PORT_OPT,
    step_stop: int | None = STEP_STOP_OPT,
    line: str = LINE_OPT,
    files_root: Path | None = FILES_OPT,
    addr_file: Path | None = ADDR_OPT,
) -> None:
    port_ = _require_port(port)
    job = load_job(job_path)
    session = _make_session(
        port=port_, line=line, files_root=files_root, addr_file=addr_file
    )
    with session:
        _attach_progress(session)
        result = session.run_job(job, step_stop=step_stop)
    if result.aborted:
        raise typer.Exit(code=1)


@app.command(help="Abre a interface de terminal (TUI Textual).")
def tui(
    port: str = PORT_OPT,
    line: str = LINE_OPT,
    files_root: Path | None = FILES_OPT,
    addr_file: Path | None = ADDR_OPT,
) -> None:
    # Import lazy: textual é extra opcional `[tui]`, e a inicialização é cara.
    from delfos.tui import run as run_tui

    run_tui(port=port, line=line, files_root=files_root, addr_file=addr_file)
