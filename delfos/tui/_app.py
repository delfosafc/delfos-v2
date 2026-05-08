"""TUI Textual — três telas: conexão, seleção de job, execução.

A execução do ``Job`` roda em uma thread (via ``@work(thread=True)``); os
eventos do ``EventBus`` chegam nessa thread e são re-postados na thread do
event loop com ``app.call_from_thread`` antes de tocar widgets.

Para testes, ``DelfosApp(injected_transport=...)`` permite rodar contra um
transport fake — Session usa esse objeto em vez de abrir uma porta real.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Static,
)

from delfos import (
    ErrorEvent,
    JobAborted,
    JobFinished,
    JobStarted,
    MeasurementSample,
    Progress,
    Session,
    StepCompleted,
    StepStarted,
    UnitResponse,
    load_job,
)
from delfos.transport import available_ports

# =============================================================================
# Tela 1 — Conexão
# =============================================================================


class ConnectionScreen(Screen):
    """Coleta porta/line/files-root/addr-file e cria a ``Session``."""

    DEFAULT_CSS = """
    ConnectionScreen { align: center middle; }
    #form { width: 60; padding: 1 2; border: round $primary; }
    Label { padding-top: 1; }
    Input { width: 100%; }
    #status { padding: 1 0; min-height: 1; }
    Button { margin: 1 1 0 0; }
    """

    def __init__(self, defaults: dict[str, Any] | None = None):
        super().__init__()
        self._defaults = defaults or {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="form"):
            yield Label("[b]Conectar à Central[/b]")
            yield Label("Porta:")
            yield Input(
                value=self._defaults.get("port", ""), id="port", placeholder="COM5"
            )
            yield Label("Line (subpasta de saída):")
            yield Input(value=self._defaults.get("line", "data"), id="line")
            yield Label("Files root (vazio = ./files):")
            yield Input(value=self._defaults.get("files_root", ""), id="files_root")
            yield Label("Addr file (vazio = <files>/system/addr.dat):")
            yield Input(value=self._defaults.get("addr_file", ""), id="addr_file")
            yield Static("", id="status")
            with Horizontal():
                yield Button("Listar portas", id="list_ports")
                yield Button("Conectar", id="connect", variant="primary")
                yield Button("Sair", id="quit_app")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "list_ports":
            self._show_ports()
        elif bid == "connect":
            self._try_connect()
        elif bid == "quit_app":
            self.app.exit()

    def _show_ports(self) -> None:
        ports = available_ports()
        msg = ", ".join(ports) if ports else "nenhuma porta encontrada"
        self.query_one("#status", Static).update(f"[b]portas:[/b] {msg}")

    def _try_connect(self) -> None:
        port = self.query_one("#port", Input).value.strip()
        line = self.query_one("#line", Input).value.strip() or "data"
        files_root_raw = self.query_one("#files_root", Input).value.strip()
        addr_file_raw = self.query_one("#addr_file", Input).value.strip()

        # Sem transport injetado, porta é obrigatória.
        if not port and self.app.injected_transport is None:
            self.query_one("#status", Static).update("[red]porta vazia[/red]")
            return

        files_root = Path(files_root_raw) if files_root_raw else None
        addr_file = Path(addr_file_raw) if addr_file_raw else None
        try:
            session = Session(
                port=port or None,
                line=line,
                files_root=files_root,
                addr_file=addr_file,
                transport=self.app.injected_transport,
            )
            session.connect()
        except Exception as exc:  # noqa: BLE001 — qualquer erro vai pra UI
            self.query_one("#status", Static).update(f"[red]falhou:[/] {exc}")
            return
        self.app.session = session
        self.app.push_screen(JobSelectScreen())


# =============================================================================
# Tela 2 — Seleção de job
# =============================================================================


class JobSelectScreen(Screen):
    """Lista jobs em ``paths.jobs``, mostra preview do JSON e dispara execução."""

    DEFAULT_CSS = """
    JobSelectScreen { layout: vertical; }
    #body { height: 1fr; }
    #left { width: 40%; padding: 1; border-right: solid $primary; }
    #right { width: 1fr; padding: 1; }
    #preview { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("[b]Jobs disponíveis[/b]")
                yield ListView(id="jobs_list")
                yield Label("Step stop (vazio = até o fim):")
                yield Input(id="step_stop", placeholder="ex.: 3")
                with Horizontal():
                    yield Button("Voltar", id="back")
                    yield Button("Executar", id="run_job", variant="primary")
            with Vertical(id="right"):
                yield Label("[b]Preview[/b]")
                yield Static("(selecione um job)", id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_jobs()

    def _refresh_jobs(self) -> None:
        lv = self.query_one("#jobs_list", ListView)
        lv.clear()
        jobs_dir = self.app.session.paths.jobs
        if not jobs_dir.exists():
            return
        for f in sorted(jobs_dir.glob("*.json")):
            # IDs textual: precisam casar [a-zA-Z][a-zA-Z0-9_-]*
            safe_id = "job-" + "".join(
                c if c.isalnum() or c in "-_" else "_" for c in f.stem
            )
            item = ListItem(Label(f.name), id=safe_id)
            item.data_path = f  # type: ignore[attr-defined]
            lv.append(item)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None:
            return
        path: Path = item.data_path  # type: ignore[attr-defined]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            text = f"erro lendo: {exc}"
        self.query_one("#preview", Static).update(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "back":
            self.app.pop_screen()
        elif bid == "run_job":
            self._launch_job()

    def _launch_job(self) -> None:
        lv = self.query_one("#jobs_list", ListView)
        item = lv.highlighted_child
        if item is None:
            self.query_one("#preview", Static).update("[yellow]nenhum job selecionado[/]")
            return
        path: Path = item.data_path  # type: ignore[attr-defined]
        ss_raw = self.query_one("#step_stop", Input).value.strip()
        try:
            step_stop = int(ss_raw) if ss_raw else None
        except ValueError:
            self.query_one("#preview", Static).update("[red]step stop inválido[/]")
            return
        try:
            job = load_job(path)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#preview", Static).update(f"[red]erro carregando job:[/] {exc}")
            return
        self.app.push_screen(ExecutionScreen(job=job, step_stop=step_stop))


# =============================================================================
# Tela 3 — Execução
# =============================================================================


class ExecutionScreen(Screen):
    """Roda o ``Job`` em thread, mostra progresso e log; permite abortar."""

    DEFAULT_CSS = """
    ExecutionScreen { layout: vertical; }
    #progress { margin: 1 2; }
    #log { height: 1fr; margin: 0 2; border: round $primary; }
    #buttons { height: 3; padding: 0 2; }
    Button { margin-right: 1; }
    """

    def __init__(self, job, step_stop: int | None = None):
        super().__init__()
        self._job = job
        self._step_stop = step_stop
        self._finished = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ProgressBar(id="progress", total=max(len(self._job.steps), 1))
        yield RichLog(id="log", markup=True, wrap=True)
        with Horizontal(id="buttons"):
            yield Button("Abortar", id="abort", variant="error")
            yield Button("Voltar", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self.app.session.subscribe(self._on_event)
        self._run_job_worker()

    @work(thread=True, exclusive=True, name="job_runner")
    def _run_job_worker(self) -> None:
        try:
            self.app.session.run_job(self._job, step_stop=self._step_stop)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._write_log, f"[red]erro:[/] {exc}")
        self.app.call_from_thread(self._mark_finished)

    def _on_event(self, evt) -> None:
        # Subscriber roda na thread do worker — re-route pra UI.
        self.app.call_from_thread(self._dispatch_event, evt)

    def _dispatch_event(self, evt) -> None:
        log = self.query_one("#log", RichLog)
        bar = self.query_one("#progress", ProgressBar)
        if isinstance(evt, JobStarted):
            log.write(f"[bold]▶ {evt.job_name}[/] ({evt.n_steps} passos)")
            bar.update(total=max(evt.n_steps, 1), progress=0)
        elif isinstance(evt, StepStarted):
            log.write(f"[cyan]→[/] step {evt.step} [{evt.task}]")
        elif isinstance(evt, StepCompleted):
            log.write(f"  [green]✓[/] step {evt.step}")
        elif isinstance(evt, Progress):
            bar.update(progress=evt.current)
        elif isinstance(evt, UnitResponse):
            mark = "[green]✓[/]" if evt.success else "[red]✗[/]"
            log.write(f"    {mark} unit {evt.unit_id} {evt.detail}")
        elif isinstance(evt, MeasurementSample):
            log.write(f"    [dim]{evt.kind}[/] {evt.data}")
        elif isinstance(evt, JobAborted):
            log.write(f"[yellow]⚠ abortado no step {evt.step}[/] ({evt.reason})")
        elif isinstance(evt, JobFinished):
            log.write(
                f"[bold green]✓ {evt.job_name}[/] "
                f"({evt.n_steps_completed} passos completados)"
            )
        elif isinstance(evt, ErrorEvent):
            log.write(f"[red]erro:[/] {evt.message} {evt.detail}")

    def _write_log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def _mark_finished(self) -> None:
        self._finished = True
        # Pode já ter saído da tela quando o worker termina — suprime no-match.
        with contextlib.suppress(Exception):
            self.query_one("#abort", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "abort":
            self.app.session.abort()
            self._write_log("[yellow]abort solicitado…[/]")
        elif bid == "back":
            if not self._finished:
                self.app.session.abort()
            self.app.session.unsubscribe(self._on_event)
            self.app.pop_screen()


# =============================================================================
# App principal + entrypoint
# =============================================================================


class DelfosApp(App):
    TITLE = "delfos"
    SUB_TITLE = "controle do equipamento Delfos"

    BINDINGS = [
        ("ctrl+c", "quit", "Sair"),
    ]

    def __init__(
        self,
        *,
        defaults: dict[str, Any] | None = None,
        injected_transport: Any = None,
    ):
        super().__init__()
        self._defaults = defaults or {}
        self.injected_transport = injected_transport
        self.session: Session | None = None

    def on_mount(self) -> None:
        self.push_screen(ConnectionScreen(defaults=self._defaults))


def run(
    *,
    port: str | None = None,
    line: str = "data",
    files_root: Path | None = None,
    addr_file: Path | None = None,
) -> None:
    """Entrypoint executável da TUI. Pré-popula a tela de conexão."""
    defaults: dict[str, Any] = {"line": line}
    if port:
        defaults["port"] = port
    if files_root:
        defaults["files_root"] = str(files_root)
    if addr_file:
        defaults["addr_file"] = str(addr_file)
    DelfosApp(defaults=defaults).run()
