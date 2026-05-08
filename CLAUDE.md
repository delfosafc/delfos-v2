# delfos

Biblioteca Python para controle do equipamento Delfos (Central + UASGs) via porta
serial. Sucessor de `SB64_dash/switch.py`, mas redesenhada como **biblioteca
importável** com CLI e TUI como frontends finos. A interface gráfica vive fora
deste pacote — outros projetos consomem `delfos` como dependência.

Hardware-alvo: tipicamente um Raspberry Pi headless conectado por USB serial à
DelfosCentralFT, operado via SSH. Eventualmente o mesmo Pi pode rodar uma GUI
externa (touch/teclado).

## Arquitetura

Camadas, de baixo para cima. Cada camada só conhece as inferiores:

```
protocol.py        Frame build/parse, enums, CRC. Fonte da verdade do protocolo.
transport.py       pyserial wrapper (descoberta de porta, timeout, retry).
central.py         Cliente da Central — um método por comando do protocolo.
units.py           Tabela de endereços UASG (load addr.dat).
field.py           Campo geométrico de eletrodos + redirects.
storage/           Persistência (CSV via pandas) e logs.
events.py          Bus pub/sub (progresso, status, erros).
measurements/      Rotinas de alto nível (chamada, res_contato, resistividade,
                   sev, sp, fullwave). Compõem central + units + field + storage.
jobs/              Schema de Job/Step + loader (com migração on-the-fly do
                   formato antigo) + runner cancelável.
session.py         Public API. Compõe tudo. É o que consumidores importam.
config.py          Config (porta, baudrate, paths, defaults) — TOML + overrides.
platform/pi.py     Recursos só-Pi (GPIO reset). Import opcional, extras=[pi].
cli/               Typer. `python -m delfos ...`. Frontend fino sobre Session.
tui/               Textual. Mesma camada de Session que o CLI.
```

**Regras de fluxo:**
- Núcleo não imprime nem loga em stdout. Tudo passa pelo `events.EventBus`.
- Operações longas (`run_job`, medidas) são canceláveis via flag/context.
- `RPi.GPIO` só é importado se o consumidor pedir explicitamente
  (`from delfos.platform.pi import reset_board`).

## API pública

O entrypoint canônico é `delfos.Session`:

```python
from delfos import Session, load_job

session = Session(port="COM5", line="data")
session.connect()
session.subscribe(lambda evt: print(evt))    # ou usar TUI/CLI
session.run_job(load_job("contato.json"))
```

Tudo que está em `delfos.__init__.py` é estável. O resto é interno.

## Stack & ferramentas

- Python 3.11+
- Ambiente virtual via **uv** (sempre — ver regra global em `~/.claude/CLAUDE.md`).
  - `uv venv` para criar; `uv sync` se houver `uv.lock`; `uv run <cmd>` para executar.
- Núcleo: `pyserial`, `pandas`, `numpy`.
- CLI: `typer`. TUI: `textual`. Dev: `pytest`, `ruff`.
- Pi: `RPi.GPIO` em extras `[pi]`.

`pyproject.toml` define extras: `[cli]`, `[tui]`, `[pi]`, `[dev]`. Instalar tudo:
`uv sync --all-extras` (após criar o lockfile).

## Convenções

### Paths de saída

Replicam o layout do SB64_dash: `./files/<line>/{output,res,data,sp,sev,...}/`
relativo ao CWD do processo (não ao código). Configurável em `config.toml` ou via
`Session(files_root=...)`.

`addr.dat` (tabela de unidades, separador `;`) fica em `files/system/addr.dat`.
Jobs em `files/system/jobs/*.json`.

### Formato de job

```json
{
  "name": "quick32",
  "steps": [
    {"step": 1, "task": "ligar"},
    {"step": 2, "task": "chamada", "ciclo": 54},
    {"step": 3, "task": "resistencia", "linha": 1},
    {"step": 4, "task": "resistividade",
       "config": [1, 4],
       "dipolo": [2, 3, -1, -1, -1, -1, -1, -1, -1],
       "canais": [1],
       "linha": 1, "tempo": 7, "corrente": 0}
  ]
}
```

- `dipolo` é uma lista plana de 9 eletrodos (`-1` = desconectado).
- `canais` é o **único** lugar de origem dos canais ativos.
- O loader detecta o formato antigo (`dipolo: [[electrodes], [channels]]`) e
  migra em memória, emitindo um warning. Os arquivos no disco não são tocados.

### Eventos

Tipos básicos: `JobStarted`, `StepStarted`, `StepCompleted`, `Progress`,
`UnitResponse`, `MeasurementSample`, `JobAborted`, `JobFinished`, `Error`. Cada
evento é um dataclass simples; consumidores filtram por tipo.

### Comandos do protocolo

Sempre via `delfos.protocol.Command` e `build_command_frame`. **Não** montar
bytes na mão fora de `protocol.py` ou `transport.py`. **Não** modificar
`protocol.py` sem ter a mudança refletida no firmware (a doc é extraída de
`DelfosCentralFT/*.c`).

## O que ficou de fora (legado removido)

Estes recursos do `switch.py` antigo **não** vão para `delfos`:

- Sísmica completa (`sismica`, `sismica_ciclo`, `teste_geofone`, `save_seismic`,
  `seg2_*`, `calcula_serial_sismica`).
- Dropbox (todo o ramo de backup remoto).
- Geofones (`teste_geofone`, payload `geofones`).
- `cal_sensors` (envio raw `0xC4 0x40 0x21` — sem documentação).
- `RPi.GPIO` no path importado por padrão.

**Mantido e portado:** chamada, res_contato, resistividade, sev, sp, fullwave,
ligar/desligar, def_cicle, set_field, set_redirect_channel, set_redirect_electrode,
turn_current/turn_current_ciclo, set_electrodes, run_job (no formato novo),
`datFile` (geração de .dat para inversão Res2DInv via `ResultsStore.save_dat`).

## Comandos do dia a dia

```bash
# setup do venv
uv venv
uv sync --all-extras

# rodar smoke tests
uv run pytest

# CLI
uv run python -m delfos ports
uv run python -m delfos run files/system/jobs/contato.json --port COM5

# TUI
uv run python -m delfos tui

# lint
uv run ruff check .
```

## Anti-patterns

- Núcleo chamando `print` ou `logging` direto — use `EventBus`.
- Caminho hardcoded para `files/...` no código (sempre via `storage.paths`).
- Importar `RPi.GPIO` no topo de qualquer módulo do núcleo.
- Reativar sísmica/dropbox/geofones sem antes acordar uma migração explícita.
- Editar `protocol.py` para "fazer encaixar" — o firmware é a fonte da verdade.
  Se um comando novo aparecer, ele entra com `#define`/case ativo no firmware
  primeiro, depois no `protocol.py`, depois no `central.py`.
- Rodar Python fora do venv (regra global). Use `uv run` ou ative o venv.
