"""Carregador de jobs JSON com migração on-the-fly do formato legado.

Aceita dois invólucros:
- ``{"steps": [...]}`` (formato com wrapper, usado em jobs simples)
- ``[...]`` (lista plana de steps)

Migra dipolo legado em memória:
- Antigo: ``"dipolo": [[eletrodos], [canais]]``
- Novo:   ``"dipolo": [eletrodos]`` + ``"canais": [...]``

Quando ``canais`` já existe no step legado, ele é preservado (jobs reais
costumam ter os dois campos redundantes — o ``canais`` do disco é a fonte).

Valida o nome da task contra ``KNOWN_TASKS``; tasks legadas removidas
(sismica, geofones, backup, datFile) são rejeitadas com mensagem específica.
"""

from __future__ import annotations

import json
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


def load_job(path: str | Path) -> Job:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        steps_data = raw.get("steps", [])
        name = raw.get("name", p.stem)
    elif isinstance(raw, list):
        steps_data = raw
        name = p.stem
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
        # ``canais`` aceita escalar no formato legado (``"canais": 1``);
        # normaliza para lista — measurements iteram sobre a lista.
        if "canais" in params and isinstance(params["canais"], int):
            params["canais"] = [params["canais"]]
        steps.append(
            Step(step=int(entry["step"]), task=task, params=params)
        )

    if saw_legacy_dipolo:
        warnings.warn(
            f"Job {p.name}: dipolo no formato legado [[eletrodos],[canais]] "
            "foi migrado em memória. Considere reescrever para "
            "`dipolo: [eletrodos]` + `canais: [...]`.",
            DeprecationWarning,
            stacklevel=2,
        )

    return Job(name=name, steps=steps)


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
    # Formato legado: dipolo é uma lista de DUAS listas (eletrodos + canais).
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
