"""Testes de delfos.jobs (schema + loader)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from delfos.jobs import Job, Step, load_job

JOBS_DIR = Path(__file__).parent / "fixtures" / "jobs"
ISC50 = JOBS_DIR / "ISC50_split.json"


def test_load_dict_with_steps_wrapper(tmp_path: Path):
    p = tmp_path / "simple.json"
    p.write_text(json.dumps({
        "name": "contato",
        "steps": [
            {"step": 1, "task": "ligar"},
            {"step": 2, "task": "chamada", "ciclo": 54},
        ],
    }), encoding="utf-8")
    job = load_job(p)
    assert isinstance(job, Job)
    assert job.name == "contato"
    assert len(job.steps) == 2
    assert job.steps[0] == Step(step=1, task="ligar", params={})
    assert job.steps[1].params == {"ciclo": 54}


def test_load_list_format(tmp_path: Path):
    p = tmp_path / "lista.json"
    p.write_text(json.dumps([
        {"step": 1, "task": "ligar"},
        {"step": 2, "task": "desligar"},
    ]), encoding="utf-8")
    job = load_job(p)
    assert job.name == "lista"
    assert [s.task for s in job.steps] == ["ligar", "desligar"]


def test_legacy_dipolo_is_migrated(tmp_path: Path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps([
        {
            "step": 1,
            "task": "resistividade",
            "dipolo": [[1, 4, -1, -1, -1, -1, -1, -1, -1], [1]],
            "tempo": 7,
        },
    ]), encoding="utf-8")
    with pytest.warns(DeprecationWarning, match="legado"):
        job = load_job(p)
    step = job.steps[0]
    assert step.params["dipolo"] == [1, 4, -1, -1, -1, -1, -1, -1, -1]
    assert step.params["canais"] == [1]


def test_legacy_dipolo_respects_existing_canais(tmp_path: Path):
    """Quando o step já tem 'canais' explícito (caso real do ISC50_split), a
    migração preserva o valor do disco em vez de sobrescrever com dipolo[1]."""
    p = tmp_path / "redundant.json"
    p.write_text(json.dumps([
        {
            "step": 1,
            "task": "fullwave",
            "dipolo": [[1, 4], [1, 3]],
            "canais": [1, 3, 5],  # canal real é este, não dipolo[1]
            "tempo": 10,
        },
    ]), encoding="utf-8")
    with pytest.warns(DeprecationWarning):
        job = load_job(p)
    assert job.steps[0].params["canais"] == [1, 3, 5]


def test_no_warning_when_dipolo_is_already_flat(tmp_path: Path):
    import warnings
    p = tmp_path / "novo.json"
    p.write_text(json.dumps([
        {
            "step": 1,
            "task": "resistividade",
            "dipolo": [1, 4, -1, -1, -1, -1, -1, -1, -1],
            "canais": [1],
        },
    ]), encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # qualquer warning vira exceção
        job = load_job(p)
    assert job.steps[0].params["dipolo"] == [1, 4, -1, -1, -1, -1, -1, -1, -1]


def test_invalid_root_type_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps("just a string"), encoding="utf-8")
    with pytest.raises(ValueError, match="dict ou list"):
        load_job(p)


def test_step_without_task_raises(tmp_path: Path):
    p = tmp_path / "incompleto.json"
    p.write_text(json.dumps([{"step": 1}]), encoding="utf-8")
    with pytest.raises(ValueError, match="'step'/'task'"):
        load_job(p)


def test_load_real_isc50():
    """ISC50_split.json é um job real do user em formato legado — deve carregar
    com sucesso e a migração deve manter o ``canais`` original.

    O warning de migração é verificado em ``test_legacy_dipolo_is_migrated``;
    aqui foco é só na estrutura (Python deduplica DeprecationWarnings por
    location, então o warning pode não sair quando outros testes já o emitiram).
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        job = load_job(ISC50)

    assert job.name == "ISC50_split"
    assert len(job.steps) > 0
    fullwaves = [s for s in job.steps if s.task == "fullwave"]
    assert len(fullwaves) > 0
    sample = fullwaves[0]
    # após migração, dipolo deve ser uma lista plana de ints (não lista de listas)
    assert isinstance(sample.params["dipolo"], list)
    assert all(isinstance(x, int) for x in sample.params["dipolo"])
    assert "canais" in sample.params
