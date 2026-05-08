"""Conversão de jobs v1 (JSON, switch.py legado) para v2 (TOML).

Inferências feitas pelo migrador:
- Campos com valor idêntico em TODOS os steps de medida vão para ``[defaults]``.
- Step ``task: distancias`` (configura field) vira ``[field]`` no header e some
  dos steps.
- Numeração explícita ``step: N`` é descartada (v2 numera automaticamente);
  pulos não-triviais são preservados via ``step =`` explícito quando o pulo
  for maior que 1 da seq esperada.
- Aplica os renames: ``config→injecao``, ``tempo→stack``, ``corrente→corrente_ma``,
  ``linha 1/2 → "data"/"power"``, ``datFile→exportar_dat``, dipolo flat sem
  padding ``-1``.

Não usa ``tomli_w``: escreve TOML enxuto na mão. O subset gerado é restrito
o suficiente para que ``tomllib.loads`` round-trip funcione.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# v1 → v2 renames (inverso do loader)
_PARAM_RENAMES_V1_TO_V2 = {
    "config": "injecao",
    "tempo": "stack",
    "corrente": "corrente_ma",
}
_TASK_RENAMES_V1_TO_V2 = {"datFile": "exportar_dat"}
_LINHA_INT_TO_NAME = {1: "data", 2: "power"}

_MEDIDA_TASKS = frozenset({"resistividade", "fullwave", "sev", "sp", "resistencia"})
_DIPOLO_LEN = 9


def migrate_job_v1_to_v2(json_path: Path) -> str:
    """Lê um job JSON v1 e devolve a string TOML v2 equivalente."""
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        steps_raw = raw.get("steps", [])
        name = raw.get("name", json_path.stem)
    elif isinstance(raw, list):
        steps_raw = raw
        name = json_path.stem
    else:
        raise ValueError(f"Job inválido em {json_path}: esperado dict ou list.")

    field_cfg, steps_v1 = _extract_field(steps_raw)

    # Normaliza cada step: aplica migração de dipolo legado e renames de chaves.
    steps_v2: list[dict[str, Any]] = []
    for entry in steps_v1:
        step_v2 = _step_v1_to_v2(entry)
        steps_v2.append(step_v2)

    defaults = _infer_defaults(steps_v2)

    return _emit_toml(
        name=name,
        field=field_cfg,
        defaults=defaults,
        steps=steps_v2,
    )


def _extract_field(steps_raw: list[Any]) -> tuple[dict[str, Any] | None, list[Any]]:
    """Remove o primeiro step ``task: distancias`` e devolve seus params como
    o dict de ``[field]`` v2."""
    field: dict[str, Any] | None = None
    rest: list[Any] = []
    for s in steps_raw:
        if (
            field is None
            and isinstance(s, dict)
            and s.get("task") == "distancias"
        ):
            field = {k: v for k, v in s.items() if k not in ("step", "task")}
        else:
            rest.append(s)
    return field, rest


def _step_v1_to_v2(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    task = entry.get("task")
    out["task"] = _TASK_RENAMES_V1_TO_V2.get(task, task)
    if "step" in entry:
        out["__original_step"] = int(entry["step"])

    for k, v in entry.items():
        if k in ("task", "step"):
            continue
        new_key = _PARAM_RENAMES_V1_TO_V2.get(k, k)
        out[new_key] = v

    # dipolo legado [[eletrodos], [canais]] → flat eletrodos + canais separado
    dip = out.get("dipolo")
    if (
        isinstance(dip, list)
        and len(dip) == 2
        and isinstance(dip[0], list)
        and isinstance(dip[1], list)
    ):
        out["dipolo"] = list(dip[0])
        out.setdefault("canais", list(dip[1]))

    # canais escalar → lista
    if isinstance(out.get("canais"), int):
        out["canais"] = [out["canais"]]

    # dipolo: tira o padding -1 do fim
    if isinstance(out.get("dipolo"), list):
        out["dipolo"] = _strip_dipolo_padding(out["dipolo"])

    # linha int → string nomeada
    if isinstance(out.get("linha"), int) and out["linha"] in _LINHA_INT_TO_NAME:
        out["linha"] = _LINHA_INT_TO_NAME[out["linha"]]

    return out


def _strip_dipolo_padding(dipolo: list[int]) -> list[int]:
    """Remove `-1` finais (mantém `-1` no meio se houver canais não-iniciais)."""
    while dipolo and dipolo[-1] == -1:
        dipolo = dipolo[:-1]
    return dipolo


def _infer_defaults(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Campos com valor idêntico em TODOS os steps de medida viram defaults.

    `task`, `injecao`, `dipolo`, `canais` nunca vão para defaults — são
    intrínsecos a cada medida. ``ciclo`` (de step ``chamada``) também vai.
    """
    defaults: dict[str, Any] = {}
    candidate_keys = ("stack", "corrente_ma", "linha", "ganho")
    medida_steps = [s for s in steps if s.get("task") in _MEDIDA_TASKS]

    if medida_steps:
        for k in candidate_keys:
            vals = [s.get(k) for s in medida_steps if k in s]
            if len(vals) == len(medida_steps) and len(set(_freeze(v) for v in vals)) == 1:
                defaults[k] = vals[0]
        # canais comum (raríssimo variar): só vai como default se constante
        canais_vals = [tuple(s["canais"]) for s in medida_steps if "canais" in s]
        if (
            len(canais_vals) == len(medida_steps)
            and len(set(canais_vals)) == 1
        ):
            defaults["canais"] = list(canais_vals[0])

    # ciclo de chamada: se o único step `chamada` tem ciclo, sobe pro defaults.
    chamadas = [s for s in steps if s.get("task") == "chamada" and "ciclo" in s]
    if len(chamadas) == 1:
        defaults["ciclo"] = chamadas[0]["ciclo"]

    return defaults


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    return value


# =============================================================================
# Emissão TOML enxuta (sem dependência externa)
# =============================================================================


def _emit_toml(
    *,
    name: str,
    field: dict[str, Any] | None,
    defaults: dict[str, Any],
    steps: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"name = {_toml_value(name)}")

    if field:
        lines.append("")
        lines.append("[field]")
        for k, v in field.items():
            lines.append(f"{k} = {_toml_value(v)}")

    if defaults:
        lines.append("")
        lines.append("[defaults]")
        for k, v in defaults.items():
            lines.append(f"{k} = {_toml_value(v)}")

    # Steps: numeração contígua a partir de 1; só emite `step =` explícito
    # quando o número original quebrava a sequência (ex.: `task: distancias`
    # do v1 virou `[field]` no v2 e deslocou a numeração em 1).
    expected_step = 1
    for entry in steps:
        original_step = entry.pop("__original_step", None)

        # Drop chaves que viraram defaults
        emit_entry = {
            k: v for k, v in entry.items()
            if not (k in defaults and _freeze(v) == _freeze(defaults[k]))
        }

        lines.append("")
        lines.append("[[steps]]")

        # Step explícito apenas se a numeração original difere da contagem natural.
        if original_step is not None and original_step != expected_step:
            lines.append(f"step = {original_step}")
            expected_step = original_step + 1
        else:
            expected_step += 1

        # task primeiro
        if "task" in emit_entry:
            lines.append(f"task = {_toml_value(emit_entry['task'])}")
        for k, v in emit_entry.items():
            if k == "task":
                continue
            lines.append(f"{k} = {_toml_value(v)}")

    return "\n".join(lines) + "\n"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        # Escape básico: aspas duplas e backslash. TOML basic-string aceita unicode.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"Tipo não suportado para emissão TOML: {type(v).__name__}: {v!r}")
