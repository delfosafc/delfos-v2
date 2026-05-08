"""Parity tests contra capturas de campo do firmware atual.

Cada run em ``tests/fixtures/parity/runs/<id>/`` carrega:
- ``debug.txt`` — log com pares TX/RX por linha
- ``result.csv`` — saída CSV de resistividade
- ``job.json`` — JSON do job que foi executado

O addr.dat é compartilhado em ``tests/fixtures/parity/addr.dat``. Marker
``parity`` permite rodar separado se necessário.

Cobertura por run:
1. **TX byte-a-byte** — ``ReplayTransport(strict=True)`` falha no primeiro
   write que divergir do gravado.
2. **CSV numérico** — ``session.results.resistivity`` produzido bate com
   ``result.csv`` de campo (tolerância 1e-6 nos floats).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from delfos import Session, load_job
from tests._parity import ReplayTransport, parse_debug_file

PARITY_DIR = Path(__file__).parent / "fixtures" / "parity"
ADDR_PATH = PARITY_DIR / "addr.dat"
RUNS_DIR = PARITY_DIR / "runs"


def _run_ids() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        p.name for p in RUNS_DIR.iterdir()
        if p.is_dir() and (p / "debug.txt").exists() and (p / "job.json").exists()
    )


@pytest.fixture(params=_run_ids(), ids=lambda x: x)
def run_dir(request) -> Path:
    return RUNS_DIR / request.param


@pytest.mark.parity
def test_parity_tx_and_csv(tmp_path, run_dir):
    """TX byte-a-byte + CSV numérico contra o run gravado."""
    debug_path = run_dir / "debug.txt"
    csv_path = run_dir / "result.csv"
    job_path = run_dir / "job.json"
    expected_df = pd.read_csv(csv_path, sep=";")

    events = parse_debug_file(debug_path)
    events = _trim_to_job_start(events)
    transport = ReplayTransport(events, strict=True)

    session = Session(
        line="parity",
        files_root=tmp_path,
        addr_file=ADDR_PATH,
        n_electrodes=64,
        spa_x=1.0,
        n_tries=5,
        transport=transport,
    )
    session.connect()
    job = load_job(job_path)

    result = session.run_job(job, base_name=run_dir.name)
    assert result.aborted is False, "job foi abortado durante o replay"
    assert transport.mismatches == [], (
        f"{len(transport.mismatches)} mismatches de TX:\n"
        + "\n".join("  " + m.short() for m in transport.mismatches[:10])
    )

    actual_df = session.results.resistivity
    assert not actual_df.empty, "ResultsStore.resistivity ficou vazio"
    _assert_resistivity_matches(actual_df, expected_df)


# Opcode do primeiro frame de qualquer job (LIGA_ALIM_UASGS broadcast).
_JOB_START_PREFIX = bytes.fromhex("7f00004b")


def _trim_to_job_start(events):
    """Isola a seção do log que corresponde ao job rodado.

    Cada execução de job começa com ``LIGA_ALIM_UASGS`` (``7f00004b…``).
    Quando o operador encadeia múltiplas tentativas (ex.: aborta uma e
    re-roda), o debug.txt acumula várias seções. Escolhemos a mais longa,
    presumindo que é o run completo que produziu o CSV de saída.

    Eventos de inicialização que aparecem antes do primeiro LIGA (ex.: um
    SET_CYCLE de origem desconhecida em alguns runs) também são descartados.
    """
    starts = [
        i for i, ev in enumerate(events)
        if ev.kind == "tx_rx" and ev.tx.startswith(_JOB_START_PREFIX)
    ]
    if not starts:
        return events
    if len(starts) == 1:
        return events[starts[0]:]
    bounds = starts + [len(events)]
    sections = [events[bounds[i]:bounds[i + 1]] for i in range(len(starts))]
    return max(sections, key=len)


# Colunas geométricas absolutas: dependem do `ini_x` do field, que varia
# entre runs por convenções históricas do switch.py legado. Como
# `resistividade` é invariante a translação (usa só diferenças entre
# eletrodos), podemos ignorar essas colunas e ainda validar a parte
# numérica que importa.
_POSITION_COLUMNS = {"Ax", "Ay", "Bx", "By", "Mx", "My", "Nx", "Ny"}


def _assert_resistivity_matches(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """Aplica as transformações que ``ResultsStore.save_resistivity`` faria
    e compara com o CSV de campo (tolerância 1e-6 nos floats), ignorando
    colunas de posição absoluta."""
    from delfos.storage.results import ResultsStore

    actual = ResultsStore._calculate_current_resistance(actual)  # noqa: SLF001
    actual = ResultsStore._calculate_resistivity(actual)  # noqa: SLF001

    assert len(actual) == len(expected), (
        f"contagem de linhas difere: delfos={len(actual)} legado={len(expected)}"
    )

    common = sorted(set(actual.columns) & set(expected.columns) - _POSITION_COLUMNS)
    assert "resistividade" in common, "coluna resistividade ausente no resultado"

    numeric_cols = [c for c in common if pd.api.types.is_numeric_dtype(expected[c])]
    for col in numeric_cols:
        a = actual[col].reset_index(drop=True)
        e = expected[col].reset_index(drop=True)
        if a.dtype.kind in "fc" or e.dtype.kind in "fc":
            pd.testing.assert_series_equal(
                a.astype(float), e.astype(float),
                check_names=False, atol=1e-6, rtol=1e-6,
                obj=f"coluna '{col}'",
            )
        else:
            pd.testing.assert_series_equal(
                a, e, check_names=False, check_dtype=False,
                obj=f"coluna '{col}'",
            )
