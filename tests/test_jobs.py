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


def test_no_legacy_dipolo_warning_when_already_flat(tmp_path: Path):
    """JSON v1 sempre emite DeprecationWarning de formato. Aqui garantimos que
    NÃO emite o warning específico de dipolo legado quando o dipolo já vem flat."""
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
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        job = load_job(p)
    legacy_dipolo_warnings = [
        w for w in caught if "dipolo no formato legado" in str(w.message)
    ]
    assert legacy_dipolo_warnings == []
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


# =============================================================================
# Schema v2 — TOML
# =============================================================================


def test_v2_loads_minimal_toml(tmp_path: Path):
    p = tmp_path / "minimal.toml"
    p.write_text(
        'name = "smoke"\n\n'
        '[[steps]]\ntask = "ligar"\n\n'
        '[[steps]]\ntask = "desligar"\n',
        encoding="utf-8",
    )
    job = load_job(p)
    assert job.name == "smoke"
    assert [s.task for s in job.steps] == ["ligar", "desligar"]
    assert [s.step for s in job.steps] == [1, 2]
    assert job.field is None


def test_v2_field_header(tmp_path: Path):
    p = tmp_path / "with_field.toml"
    p.write_text(
        'name = "f"\n\n'
        '[field]\neletrodos = 32\nspa_x = 1\nini_x = 1\n\n'
        '[[steps]]\ntask = "ligar"\n',
        encoding="utf-8",
    )
    job = load_job(p)
    assert job.field == {"eletrodos": 32, "spa_x": 1, "ini_x": 1}


def test_v2_defaults_merge_into_steps(tmp_path: Path):
    p = tmp_path / "defaults.toml"
    p.write_text(
        'name = "d"\n\n'
        '[defaults]\nstack = 7\ncorrente_ma = 50\nlinha = "data"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [2, 5]\ndipolo = [3, 4]\ncorrente_ma = 80\n',
        encoding="utf-8",
    )
    job = load_job(p)
    s0, s1 = job.steps
    assert s0.params["tempo"] == 7  # stack → tempo
    assert s0.params["corrente"] == 50  # corrente_ma → corrente
    assert s0.params["linha"] == 1  # "data" → 1
    # override no step 2
    assert s1.params["corrente"] == 80
    assert s1.params["tempo"] == 7  # ainda do default


def test_v2_dipolo_pads_to_9(tmp_path: Path):
    p = tmp_path / "dipolo.toml"
    p.write_text(
        'name = "d"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\ncanais = [1]\n',
        encoding="utf-8",
    )
    job = load_job(p)
    # dipolo de 2 ints é estendido para 9 com -1
    assert job.steps[0].params["dipolo"] == [2, 3, -1, -1, -1, -1, -1, -1, -1]
    # config (renomeado de injecao)
    assert job.steps[0].params["config"] == [1, 4]


def test_v2_dipolo_too_long_fails(tmp_path: Path):
    p = tmp_path / "long.toml"
    p.write_text(
        'name = "long"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 2]\n'
        'dipolo = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]\ncanais = [1]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dipolo"):
        load_job(p)


def test_v2_explicit_step_resets_numbering(tmp_path: Path):
    p = tmp_path / "renum.toml"
    p.write_text(
        'name = "renum"\n\n'
        '[[steps]]\ntask = "ligar"\n\n'
        '[[steps]]\ntask = "chamada"\n\n'
        '[[steps]]\nstep = 10\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [2, 5]\ndipolo = [3, 4]\n',
        encoding="utf-8",
    )
    job = load_job(p)
    assert [s.step for s in job.steps] == [1, 2, 10, 11]


def test_v2_linha_string_or_int(tmp_path: Path):
    p = tmp_path / "linha.toml"
    p.write_text(
        'name = "l"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\nlinha = "power"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [2, 5]\ndipolo = [3, 4]\nlinha = 1\n',
        encoding="utf-8",
    )
    job = load_job(p)
    assert job.steps[0].params["linha"] == 2  # "power" → 2
    assert job.steps[1].params["linha"] == 1


def test_v2_linha_invalid_fails(tmp_path: Path):
    p = tmp_path / "bad_linha.toml"
    p.write_text(
        'name = "bad"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\nlinha = "wrong"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="linha"):
        load_job(p)


def test_v2_task_alias_exportar_dat(tmp_path: Path):
    p = tmp_path / "exp.toml"
    p.write_text(
        'name = "exp"\n\n[[steps]]\ntask = "exportar_dat"\nspa = 2.5\n',
        encoding="utf-8",
    )
    job = load_job(p)
    # alias é resolvido para o nome interno legado
    assert job.steps[0].task == "datFile"


def test_v2_canais_scalar_to_list(tmp_path: Path):
    p = tmp_path / "scalar.toml"
    p.write_text(
        'name = "s"\n\n'
        '[[steps]]\ntask = "fullwave"\ninjecao = [1, 4]\ndipolo = [2, 3]\ncanais = 1\n',
        encoding="utf-8",
    )
    job = load_job(p)
    assert job.steps[0].params["canais"] == [1]


def test_unknown_extension_raises(tmp_path: Path):
    p = tmp_path / "x.yaml"
    p.write_text("name: foo", encoding="utf-8")
    with pytest.raises(ValueError, match="Extensão"):
        load_job(p)


# =============================================================================
# migrate-job (v1 → v2)
# =============================================================================


def test_migrate_extracts_field_from_distancias(tmp_path: Path):
    from delfos.jobs.migrate import migrate_job_v1_to_v2

    src = tmp_path / "src.json"
    src.write_text(json.dumps({
        "name": "M",
        "steps": [
            {"step": 1, "task": "ligar"},
            {"step": 2, "task": "distancias", "eletrodos": 32, "spa_x": 1, "ini_x": 1},
        ],
    }), encoding="utf-8")
    out = migrate_job_v1_to_v2(src)
    assert "[field]" in out
    assert "eletrodos = 32" in out
    # task `distancias` foi removida dos steps
    assert 'task = "distancias"' not in out


def test_migrate_extracts_constant_defaults(tmp_path: Path):
    from delfos.jobs.migrate import migrate_job_v1_to_v2

    src = tmp_path / "src.json"
    src.write_text(json.dumps([
        {"step": 1, "task": "ligar"},
        {
            "step": 2, "task": "fullwave",
            "config": [1, 4], "dipolo": [[2, 3, -1, -1, -1, -1, -1, -1, -1], [1]],
            "canais": [1], "tempo": 7, "corrente": 50, "linha": 1,
        },
        {
            "step": 3, "task": "fullwave",
            "config": [2, 5], "dipolo": [[3, 4, -1, -1, -1, -1, -1, -1, -1], [1]],
            "canais": [1], "tempo": 7, "corrente": 50, "linha": 1,
        },
    ]), encoding="utf-8")
    out = migrate_job_v1_to_v2(src)
    # campos constantes em todas as medidas viram defaults
    assert "[defaults]" in out
    assert "stack = 7" in out
    assert "corrente_ma = 50" in out
    assert 'linha = "data"' in out
    # e somem dos steps individuais
    stack_lines = [ln for ln in out.splitlines() if ln.startswith("stack")]
    corrente_lines = [ln for ln in out.splitlines() if ln.startswith("corrente_ma")]
    assert len(stack_lines) == 1
    assert len(corrente_lines) == 1


def test_migrate_preserves_step_jump_after_field_extraction(tmp_path: Path):
    """Quando `task: distancias` sai dos steps, a numeração natural cai 1 a
    menos que a original. O migrador insere `step = N` no primeiro step de
    medida pra manter rastreabilidade."""
    from delfos.jobs.migrate import migrate_job_v1_to_v2

    src = tmp_path / "src.json"
    src.write_text(json.dumps({
        "steps": [
            {"step": 1, "task": "ligar"},
            {"step": 2, "task": "chamada", "ciclo": 54},
            {"step": 3, "task": "distancias", "eletrodos": 32, "spa_x": 1, "ini_x": 1},
            {
                "step": 4, "task": "fullwave",
                "config": [1, 4], "dipolo": [[2, 3, -1, -1, -1, -1, -1, -1, -1], [1]],
                "canais": [1], "tempo": 7, "corrente": 50, "linha": 1,
            },
        ],
    }), encoding="utf-8")
    out = migrate_job_v1_to_v2(src)
    # Sem ajuste: ligar=1, chamada=2, fullwave seria auto-numerado para 3.
    # Com ajuste: emite `step = 4` explícito no primeiro fullwave.
    assert "step = 4" in out


def test_migrate_round_trip_loads(tmp_path: Path):
    """O TOML produzido pelo migrador é carregável pelo load_job."""
    from delfos.jobs.migrate import migrate_job_v1_to_v2

    src = tmp_path / "src.json"
    src.write_text(json.dumps([
        {"step": 1, "task": "ligar"},
        {"step": 2, "task": "chamada", "ciclo": 54},
        {
            "step": 3, "task": "fullwave",
            "config": [1, 4], "dipolo": [[2, 3, -1, -1, -1, -1, -1, -1, -1], [1]],
            "canais": [1], "tempo": 7, "corrente": 50, "linha": 1,
        },
    ]), encoding="utf-8")
    out = src.with_suffix(".toml")
    out.write_text(migrate_job_v1_to_v2(src), encoding="utf-8")
    job = load_job(out)
    assert [s.task for s in job.steps] == ["ligar", "chamada", "fullwave"]
    fw = job.steps[2]
    assert fw.params["config"] == [1, 4]
    assert fw.params["dipolo"][:2] == [2, 3]
    assert fw.params["tempo"] == 7
