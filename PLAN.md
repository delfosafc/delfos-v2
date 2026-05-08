# Plano de implementação — delfos

Roteiro do port do `SB64_dash/switch.py` para a biblioteca `delfos`. Cada fase
fecha com um critério de aceite verificável. Ordem importa: camadas inferiores
primeiro.

Suposições:
- `protocol.py` e `protocol.md` já estão prontos e congelados nesta etapa.
- Repo: `D:\Github\delfos`. Python 3.11+. uv como gerenciador.
- Hardware-alvo: Raspberry Pi (Linux ARM) e Windows para dev. Sem teste E2E
  obrigatório com hardware nas fases 1–8 — tudo testável com transport fake.

---

## Fase 0 — Setup do projeto

**Saídas:**
- `pyproject.toml` (uv-managed) com extras `[cli]`, `[tui]`, `[pi]`, `[dev]`.
- Layout do pacote `delfos/` com `__init__.py` em cada subpasta.
- `.gitignore` (Python + venv + files/ output).
- `ruff.toml` mínimo.
- `tests/` com smoke test do `protocol.py` migrado.
- `README.md` curto apontando para CLAUDE.md e PLAN.md.

**Critério:** `uv sync --all-extras` instala; `uv run pytest` roda 0 falhas.

---

## Fase 1 — Transporte serial

`delfos/transport.py` substitui `myserial.py`.

**Decisões:**
- Classe `SerialTransport(port, baudrate=115200, timeout=0.1)`.
- API: `connect()`, `disconnect()`, `write(data)`, `read(n)`, `set_timeout(t)`,
  `is_connected`, context manager.
- Função módulo `available_ports() -> list[str]` (cross-platform; já existe no
  `myserial.py`, copiar enxuto).
- Sem retry aqui — retry vive em `central.py` por comando.
- Sem `RPi.GPIO`.

**Saídas:**
- `transport.py` + testes com loopback (pyserial `loop://`).

**Critério:** unit tests cobrem write+read, timeout, lista de portas. Roda em
Windows e Linux.

---

## Fase 2 — Cliente da Central

`delfos/central.py`.

**Decisões:**
- Classe `Central(transport: SerialTransport, n_tries=5)`.
- Um método por comando do protocolo (todos validados via `protocol.CommandSpec`).
  - `ping(addr=BROADCAST_ADDR, multiplier=None) -> ResponseFrame`
  - `ping_central(reset_time=48) -> ResponseFrame`
  - `set_cycle(cycle: CyclePeriod) -> ResponseFrame`
  - `liga_alim_uasgs() / desliga_alim_uasgs()`
  - `current_off()`, `current_auto(corrente_ma)`, `current_cycle(corrente_ma, stack)`,
    `current_turbo(...)`, `current_change_on_fly(corrente_ma)`, `current_abort()`
  - `start_geo(var, p2=0, p3=0)`, `stop_geo(var)`
  - `read_vp(addr)`, `read_sp(addr)`, `read_fullwave(addr)` — devolvem dataclasses
    decodificadas (não bytes crus).
  - `set_electrodes(addr, p1, p2, p3, electrodes, line)` (frame MR64 quando p1≥0x55).
  - `read_resistance(addr)`, `measure_resistance(parity)`.
  - `read_current()`, `info_corrente()` (parse autônomo).
- Retry interno usa `n_tries`; cada tentativa loga via EventBus (mas tem default
  null bus pra uso headless em testes).
- Conversão ADC vira utilitário: `convert_adc(raw, const)` em módulo `_adc.py`.

**Saídas:** `central.py`, `_adc.py`, testes com transport fake (record/replay
de bytes hex).

**Critério:** todos os comandos do `switch.py` antigo têm equivalente em
`Central` cobertos por teste com transport fake. Sem `print`. Sem dependência
de pandas.

---

## Fase 3 — Modelos: Field, Units, Schema de Job

**`delfos/field.py`:**
- `Field(n_electrodes, spa_x=1, spa_y=0, ini_x=0, ini_y=0)` mantém DataFrame de
  posições. Métodos: `pos(electrode) -> (x, y)`, `redirect_electrode(from, to)`.

**`delfos/units.py`:**
- `Units.load(path)` lê `addr.dat`. Métodos: `get_channels()`, `get_switches()`,
  `ur_from_channel(ch)`, `electrodes_for_order(electrodes, order)`.
- Suporta `redirect_channel(from, to)`.

**`delfos/jobs/schema.py`:**
- `@dataclass` `Step` com `step: int`, `task: str`, `**kwargs`. Subclasses por
  task ou só validação ad-hoc — escolher na hora de codar (preferir ad-hoc com
  factory, evita explosão de classes).
- `Job` com `name: str`, `steps: list[Step]`.

**Saídas:** módulos + testes (pure-python, sem hardware).

**Critério:** carrega `SB64_dash/files/system/addr base.dat` e
`files/system/jobs/contato.json` sem erro.

---

## Fase 4 — Storage e EventBus

**`delfos/storage/paths.py`:**
- `Paths(files_root: Path, line: str)` resolve `output_path`, `debug_path`,
  `resistance_path`, `data_path`, `sp_path`, `sev_path`, `processed_path`,
  `jobs_path`, `system_path`. Cria diretórios sob demanda.
- Default `files_root = Path.cwd() / "files"`.

**`delfos/storage/results.py`:**
- `ResultsStore(paths)` com `add_resistance/save_resistance`, idem
  `resistivity/sp/sev`. Mantém DataFrames em memória.
- Cálculo de resistividade (`calculate_resistivity`) e `calculate_current_resistance`
  ficam aqui — herdados do `fileshandler.py`. **Não** entra `generate_dat` (era do
  pipeline antigo de pós-processamento; deixar pra fase futura se necessário).

**`delfos/storage/logs.py`:**
- `LogWriter(paths)` com `output(text)` / `debug(text)` / `error(text)`. Append
  + timestamp.

**`delfos/events.py`:**
- `EventBus` simples (lista de subscribers, `publish(event)` síncrono).
- Tipos: `JobStarted, StepStarted, StepCompleted, Progress, UnitResponse,
  MeasurementSample, JobAborted, JobFinished, Error`. Cada um dataclass.
- `NullBus` para uso em testes.

**Critério:** `ResultsStore` carrega/salva CSVs identicos aos do SB64_dash
(comparar com fixture). EventBus tem teste pub/sub.

---

## Fase 5 — Measurements (porting incremental)

Cada measurement é um módulo em `delfos/measurements/` que recebe
`(central, units, field, results, logs, bus, abort_event)` e expõe uma função
síncrona. Portar do `switch.py` antigo, **sem** mudar a lógica numérica:

5.1. `chamada.py` — `chamada(central, units, ciclo=None, ...)`. Substitui
     `Switch.chamada`. Emite `UnitResponse` por unidade.

5.2. `res_contato.py` — `res_contato(central, units, field, results, line=1)`.
     Substitui `Switch.res_contato`. Emite `MeasurementSample` por par.

5.3. `resistividade.py` — versão limpa de `Switch.resistivity_cicle`. Recebe
     `dipolo` (lista de 9 eletrodos) e `canais` separados. Sem fallback para
     formato antigo (loader já normalizou).

5.4. `sev.py` — `sev_cicle`.

5.5. `sp.py` — `SP_cicle`.

5.6. `fullwave.py` — leitura fullwave (extrair de `read_fullwave`). Idem
     comportamento atual: dispara dentro do `resistividade` quando `is_fullwave=True`,
     **mas** vira função autônoma reutilizável.

**Critério por arquivo:** unit tests com transport fake reproduzem trace de
bytes do SB64_dash (capturado em arquivo `.hex` de fixture). Aborts respeitam
o `abort_event`.

---

## Fase 6 — Job loader e runner

**`delfos/jobs/loader.py`:**
- `load_job(path) -> Job`. Detecta:
  - Lista raiz vs. `{"steps": [...]}` (ambos suportados).
  - `dipolo` em formato antigo `[[electrodes], [channels]]` → migra para
    `dipolo=[electrodes]` + `canais=[channels]` em memória, com
    `warnings.warn("legacy job format ...")`.
- `validate(job)` — falha cedo com mensagens claras (step duplicado, task
  desconhecida, parâmetros faltando).

**`delfos/jobs/runner.py`:**
- `JobRunner(session)` com `run(job, *, abort=None, step_stop=None)`.
- Faz dispatch por `task`:
  ```
  ligar / desligar      -> central.liga_alim_uasgs / desliga
  chamada               -> measurements.chamada
  ciclo                 -> central.set_cycle
  serial                -> session.reconnect(porta)
  resistencia           -> measurements.res_contato
  resistividade         -> measurements.resistividade
  fullwave              -> measurements.resistividade(..., is_fullwave=True)
  sev / sp              -> measurements.sev / sp
  distancias            -> session.field.reconfigure(...)
  enderecos             -> session.units.reload(...)
  eletrodos             -> session.field.set_redirects(...)
  ```
- Tasks **removidas** (rejeitadas com erro claro): `sismica`, `geofones`,
  `backup`. Loader rejeita no `validate`.
- `datFile` foi **mantida**: gera o arquivo `.dat` para inversão Res2DInv
  (port de `fileshandler.generate_dat` em `ResultsStore.save_dat`).
- Emite `JobStarted/StepStarted/Progress/StepCompleted/JobFinished`.

**Critério:** rodar `contato.json` e `teste.json` (do SB64_dash) com transport
fake produz a mesma sequência de bytes que `switch.py` antigo. Diff ≤ campos
de timing.

---

## Fase 7 — Session (API pública)

`delfos/session.py`:

```python
class Session:
    def __init__(self, *, port=None, baudrate=115200, line="data",
                 files_root=None, addr_file="addr"): ...
    def connect(self): ...
    def disconnect(self): ...
    def reconnect(self, port=None): ...
    @property
    def central(self) -> Central: ...
    @property
    def units(self) -> Units: ...
    @property
    def field(self) -> Field: ...
    @property
    def results(self) -> ResultsStore: ...
    def subscribe(self, callback): ...
    def run_job(self, job, *, step_stop=None) -> JobResult: ...
    def abort(self): ...
```

`delfos/__init__.py` re-exporta: `Session, load_job, EventBus` + tipos de
evento.

**Critério:** consumidor externo consegue:
```python
from delfos import Session, load_job
s = Session(port="COM5")
s.connect()
s.run_job(load_job("contato.json"))
```
sem importar nada de `delfos.measurements.*` ou `delfos.protocol.*` direto.

---

## Fase 8 — CLI (Typer)

`delfos/cli/__main__.py`:

```
delfos ports
delfos ping --port COM5
delfos status --port COM5
delfos chamada --port COM5 [--ciclo 54]
delfos contato --port COM5 [--linha 1]
delfos run <job.json> --port COM5 [--step-stop N]
delfos migrate-job <arquivo>     # (opcional, se quisermos depois)
```

- Cada subcomando é função Typer fina sobre `Session`.
- Saída humana via `rich` (Typer já traz). Progresso por evento → progress bar.
- `--port` opcional se houver `DELFOS_PORT` env var ou `config.toml`.

**Critério:** `uv run python -m delfos ports` lista portas; `--help` mostra
todos os subcomandos.

---

## Fase 9 — TUI (Textual)

`delfos/tui/app.py`:

Telas:
1. **Conexão:** seleção de porta, baudrate, addr_file. Botão "Conectar".
2. **Job:** dropdown de jobs em `files/system/jobs/`, preview do JSON
   (read-only), seleção de step inicial/final.
3. **Execução:** progress bar, step atual destacado, tabela de unidades
   com status (ok/falha) atualizada por `UnitResponse`, log rolando, botão
   "Abort". Tudo via subscribe ao EventBus.

Sem editar jobs pela TUI nesta fase. Boa pra remoto via SSH.

**Critério:** `uv run python -m delfos tui` abre, conecta numa porta de teste
(loopback), roda um job de fixture até o fim sem travar.

---

## Fase 10 — Plataforma Pi

`delfos/platform/pi.py`:
- `reset_board(reset_pin=4)` — só importável quando `RPi.GPIO` está disponível
  (extras `[pi]`).
- Não é chamado por nenhum measurement por padrão. Quem precisa importa.

**Critério:** `uv sync --extra pi` instala em ambiente Pi; `from delfos.platform.pi
import reset_board` funciona. Em Windows, sem `[pi]`, importar `delfos` não
quebra.

---

## Fase 11 — Testes e fixtures

- `tests/fixtures/` com:
  - `addr base.dat`, `addr_uma placa.dat` (copiar do SB64_dash).
  - `jobs/` com `contato.json`, `teste.json` (legado, para testar migração).
  - `traces/` com captures de bytes hex de execuções reais (para record/replay).
- `tests/conftest.py` com fakes: `FakeTransport(script)`, `RecordingBus()`.
- Marker `pytest -m hw` para testes que exigem hardware real (não rodam em CI).

**Critério:** `uv run pytest` verde sem hardware. Cobertura mínima razoável dos
módulos de núcleo (>70% nas camadas baixa/média).

---

## Ordem de execução sugerida

Fases 0 → 4 são lineares e independentes. Fase 5 pode ser paralelizada
(measurements são independentes entre si), mas exige Fase 4 pronta. Fases 6–9
dependem de tudo anterior.

Estimativa de blocos:
- 0+1+2: setup + transport + central client (núcleo do protocolo). Maior.
- 3+4: modelos + storage + bus. Menor.
- 5: measurements (5 arquivos similares — bom candidato a subagent-driven se
  ficar muito repetitivo).
- 6+7: job runner + Session. Médio.
- 8+9: CLI + TUI. Médio.
- 10+11: Pi + testes. Pequeno mas contínuo (cada fase já fecha com testes).

## Não fazer agora

- GUI (Dash/NiceGUI/Kivy) — fica fora deste pacote. Decisão posterior, em outro repo.
- Migração de dados antigos no disco — só on-the-fly no loader.
- Pós-processamento (`generate_dat`, SEG2) — não relevante para o objetivo
  atual de operação remota.
- Refatorar `protocol.py` ou `protocol.md` — fonte da verdade está congelada.
