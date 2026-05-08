"""Carregador de jobs.

Suporta dois formatos:

**v2 (TOML, recomendado)** — schema enxuto com `[defaults]`, dipolo flat
sem padding, naming alinhado ao hardware:

    name = "ISC32F"

    [field]
    eletrodos = 32
    spa_x = 1
    ini_x = 1

    [defaults]
    ciclo = 54
    stack = 7
    corrente_ma = 50
    linha = "data"
    canais = [1]

    [[steps]]
    task = "ligar"

    [[steps]]
    task = "fullwave"
    injecao = [2, 3]
    dipolo = [1, 4]

**v1 (JSON, depreciado)** — formato legado do switch.py SB64_dash:

    {"steps": [
        {"step": 4, "task": "fullwave", "config": [2,3],
         "dipolo": [[1,4,-1,-1,-1,-1,-1,-1,-1], [1]],
         "canais": [1], "tempo": 7, "corrente": 50, "linha": 1}
    ]}

O loader detecta pela extensão (``.toml`` ou ``.json``); ambos produzem o
mesmo ``Job`` interno. v1 emite ``DeprecationWarning``.

Renames v2 → chaves internas (mantidas para compatibilidade do runner):

    injecao → config
    dipolo (flat, sem padding) → dipolo (com padding -1 até 9)
    stack → tempo
    corrente_ma → corrente
    linha "data"/"power" → linha 1/2
    task "exportar_dat" → "datFile"
"""

from __future__ import annotations

import json
import tomllib
import warnings
from pathlib import Path
from typing import Any

from delfos.jobs.schema import Job, Step

KNOWN_TASKS = frozenset({
    "ligar", "desligar", "chamada", "ciclo", "serial",
    "resistencia", "resistividade", "fullwave",
    "sev", "sp", "distancias", "enderecos", "eletrodos",
    "datFile",
})

REMOVED_TASKS = frozenset({"sismica", "geofones", "backup"})

# Mapeamento de aliases v2 → nome interno.
_TASK_ALIASES = {"exportar_dat": "datFile"}
_PARAM_ALIASES = {
    "injecao": "config",
    "stack": "tempo",
    "corrente_ma": "corrente",
}
_LINHA_NAMES = {"data": 1, "power": 2}

DIPOLO_LEN = 9  # tamanho fixo que o protocolo MR64 espera


def load_job(path: str | Path) -> Job:
    """Carrega um job de TOML (v2) ou JSON (v1).

    Detecta o formato pela extensão. JSON emite ``DeprecationWarning``
    direcionando para o TOML v2.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".toml":
        return _load_toml_v2(p)
    if ext == ".json":
        return _load_json_v1(p)
    raise ValueError(
        f"Extensão não suportada: {ext}. Use .toml (v2) ou .json (v1 legado)."
    )


# =============================================================================
# v2 — TOML
# =============================================================================


def _load_toml_v2(path: Path) -> Job:
    with path.open("rb") as f:
        data = tomllib.load(f)

    name = data.get("name", path.stem)
    field_cfg = data.get("field")
    defaults = data.get("defaults", {})
    steps_raw = data.get("steps", [])
    if not isinstance(steps_raw, list):
        raise ValueError(
            f"`steps` em {path} deve ser uma lista, recebeu {type(steps_raw).__name__}"
        )

    next_step = 1
    steps: list[Step] = []
    for entry in steps_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"step inválido (esperado tabela): {entry!r}")
        task_raw = entry.get("task")
        if not task_raw:
            raise ValueError(f"step sem `task`: {entry!r}")
        task = _TASK_ALIASES.get(str(task_raw), str(task_raw))
        _validate_task(task)

        explicit_step = entry.get("step")
        if explicit_step is not None:
            next_step = int(explicit_step)
        step_num = next_step
        next_step += 1

        # merge defaults | step (step vence). Aplica a todos os tasks; steps
        # que não consomem alguma chave (ex.: `ligar` ignorando `stack`) não
        # se importam — measurements e runner leem só o que precisam.
        merged: dict[str, Any] = {}
        merged.update(defaults)
        merged.update({k: v for k, v in entry.items() if k not in ("task", "step")})

        params = _normalize_v2_params(merged)
        steps.append(Step(step=step_num, task=task, params=params))

    return Job(name=name, steps=steps, field=field_cfg)


def _normalize_v2_params(params: dict[str, Any]) -> dict[str, Any]:
    """Aplica renames v2 → chaves internas e normalizações (dipolo, canais, linha)."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        out[_PARAM_ALIASES.get(k, k)] = v

    # linha: "data"/"power" → 1/2 (aceita int direto também)
    if "linha" in out and isinstance(out["linha"], str):
        name = out["linha"].lower()
        if name not in _LINHA_NAMES:
            raise ValueError(
                f"`linha` deve ser 'data' ou 'power' (ou int 1/2); recebeu {out['linha']!r}"
            )
        out["linha"] = _LINHA_NAMES[name]

    # dipolo: lista variável → lista fixa de 9 com -1 padding
    if "dipolo" in out and isinstance(out["dipolo"], list):
        out["dipolo"] = _pad_dipolo(out["dipolo"])

    # canais escalar → lista
    if "canais" in out and isinstance(out["canais"], int):
        out["canais"] = [out["canais"]]

    return out


def _pad_dipolo(dipolo: list[int]) -> list[int]:
    if len(dipolo) > DIPOLO_LEN:
        raise ValueError(
            f"`dipolo` tem {len(dipolo)} eletrodos; máximo é {DIPOLO_LEN}"
        )
    return list(dipolo) + [-1] * (DIPOLO_LEN - len(dipolo))


# =============================================================================
# v1 — JSON (legado)
# =============================================================================


def _load_json_v1(path: Path) -> Job:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        steps_data = raw.get("steps", [])
        name = raw.get("name", path.stem)
    elif isinstance(raw, list):
        steps_data = raw
        name = path.stem
    else:
        raise ValueError(
            f"Job inválido em {path}: esperado dict ou list, recebeu {type(raw).__name__}"
        )

    if not isinstance(steps_data, list):
        raise ValueError(f"campo 'steps' em {path} não é lista")

    steps: list[Step] = []
    saw_legacy_dipolo = False
    for entry in steps_data:
        if not isinstance(entry, dict):
            raise ValueError(f"step inválido (esperado dict): {entry!r}")
        if "step" not in entry or "task" not in entry:
            raise ValueError(f"step sem 'step'/'task': {entry!r}")
        task = str(entry["task"])
        _validate_task(task)
        params = {k: v for k, v in entry.items() if k not in ("step", "task")}
        params, migrated = _migrate_legacy_dipolo(params)
        saw_legacy_dipolo |= migrated
        if "canais" in params and isinstance(params["canais"], int):
            params["canais"] = [params["canais"]]
        steps.append(Step(step=int(entry["step"]), task=task, params=params))

    warnings.warn(
        f"Job {path.name}: formato JSON v1 está depreciado — "
        "use TOML v2 (`delfos migrate-job <arquivo.json>`).",
        DeprecationWarning,
        stacklevel=3,
    )
    if saw_legacy_dipolo:
        warnings.warn(
            f"Job {path.name}: dipolo no formato legado [[eletrodos],[canais]] "
            "foi migrado em memória.",
            DeprecationWarning,
            stacklevel=3,
        )

    return Job(name=name, steps=steps)


# =============================================================================
# Comuns
# =============================================================================


def _validate_task(task: str) -> None:
    if task in REMOVED_TASKS:
        raise ValueError(
            f"task '{task}' foi removida em delfos (era usada no SB64_dash legado). "
            f"Remova o step ou use uma task suportada."
        )
    if task not in KNOWN_TASKS:
        raise ValueError(
            f"task desconhecida: '{task}'. Tasks suportadas: {sorted(KNOWN_TASKS)}"
        )


def _migrate_legacy_dipolo(
    params: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    dip = params.get("dipolo")
    if dip is None:
        return params, False
    if not isinstance(dip, list) or len(dip) == 0:
        return params, False
    if (
        len(dip) == 2
        and isinstance(dip[0], list)
        and isinstance(dip[1], list)
    ):
        new_params = dict(params)
        new_params["dipolo"] = dip[0]
        new_params.setdefault("canais", dip[1])
        return new_params, True
    return params, False
