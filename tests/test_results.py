"""Testes do delfos.storage.results."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from delfos.storage import Paths, ResultsStore


def _store(tmp_path):
    return ResultsStore(Paths(files_root=tmp_path, line="L1"), base_name="job")


def test_add_and_save_resistance(tmp_path):
    s = _store(tmp_path)
    s.add_resistance(pd.DataFrame({
        "eletrodo1": [1], "eletrodo2": [2],
        "tensao": [10.0], "corrente": [50.0], "resistencia": [200],
    }))
    s.save_resistance()
    df = pd.read_csv(tmp_path / "L1" / "res" / "job.csv", sep=";")
    assert len(df) == 1
    assert df.loc[0, "resistencia"] == 200


def test_clear_resistance(tmp_path):
    s = _store(tmp_path)
    s.add_resistance(pd.DataFrame({"a": [1]}))
    s.clear_resistance()
    assert s.resistance.empty


def test_save_resistivity_computes_geometric_factor(tmp_path):
    """A=(0,0), B=(3,0), M=(1,0), N=(2,0): d1A=1, d1B=2, d2A=2, d2B=1.
    geofactor = 2π/(1 - 0.5 - 0.5 + 1) = 2π. Vp=1, I=1 → ρ ≈ 6.28."""
    s = _store(tmp_path)
    s.add_resistivity(pd.DataFrame({
        "Ax": [0.0], "Ay": [0.0],
        "Bx": [3.0], "By": [0.0],
        "Mx": [1.0], "My": [0.0],
        "Nx": [2.0], "Ny": [0.0],
        "Vp": [1.0], "corrente": [1.0],
        "tensao": [10.0],  # para calculate_current_resistance
    }))
    s.save_resistivity()
    df = pd.read_csv(tmp_path / "L1" / "data" / "job.csv", sep=";")
    assert df.loc[0, "resistividade"] == round(2 * math.pi, 2)
    # resistencia corrente = round(1000 * tensao / corrente) = 10000
    assert df.loc[0, "resistencia corrente"] == 10000.0


def test_save_resistivity_handles_zero_distance(tmp_path):
    """M coincidente com A → d1A=0 substituído por 0.01 (não quebra)."""
    s = _store(tmp_path)
    s.add_resistivity(pd.DataFrame({
        "Ax": [0.0], "Ay": [0.0],
        "Bx": [10.0], "By": [0.0],
        "Mx": [0.0], "My": [0.0],   # M == A
        "Nx": [5.0], "Ny": [0.0],
        "Vp": [1.0], "corrente": [1.0],
        "tensao": [10.0],
    }))
    s.save_resistivity()
    df = pd.read_csv(tmp_path / "L1" / "data" / "job.csv", sep=";")
    # apenas verifica que salvou e o valor é finito
    assert math.isfinite(df.loc[0, "resistividade"])


def test_save_empty_resistivity_produces_empty_csv(tmp_path):
    s = _store(tmp_path)
    s.save_resistivity()
    out = tmp_path / "L1" / "data" / "job.csv"
    assert out.exists()


def test_add_and_save_sp(tmp_path):
    s = _store(tmp_path)
    s.add_sp(pd.DataFrame({"X": [10], "SP1": [0.5]}))
    s.save_sp()
    df = pd.read_csv(tmp_path / "L1" / "sp" / "job.csv", sep=";")
    assert df.loc[0, "X"] == 10


def test_add_and_save_sev(tmp_path):
    s = _store(tmp_path)
    s.add_sev(pd.DataFrame({"canal": [1], "Vp": [0.1]}))
    s.save_sev()
    df = pd.read_csv(tmp_path / "L1" / "sev" / "job.csv", sep=";")
    assert df.loc[0, "canal"] == 1


def test_save_dat_generates_res2dinv_file(tmp_path):
    s = _store(tmp_path)
    s.add_resistivity(pd.DataFrame({
        "Ax": [0.0], "Ay": [0.0],
        "Bx": [3.0], "By": [0.0],
        "Mx": [1.0], "My": [0.0],
        "Nx": [2.0], "Ny": [0.0],
        "Vp": [1.0], "corrente": [1.0], "tensao": [10.0],
    }))
    s.save_dat(spa=2.5)
    out = tmp_path / "L1" / "processed" / "job.dat"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    # Header tipo 11 (Res2DInv)
    assert "job.dat" in content
    assert "\n2.5\n" in content
    assert "\n11\n" in content
    assert "Type of measurement" in content
    # Footer com 5 zeros
    assert content.rstrip().endswith("0\n0\n0\n0\n0".rstrip())


def test_save_dat_raises_when_empty(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError, match="vazio"):
        s.save_dat()


def test_concat_multiple_rows(tmp_path):
    s = _store(tmp_path)
    s.add_resistance(pd.DataFrame({"x": [1]}))
    s.add_resistance(pd.DataFrame({"x": [2]}))
    s.add_resistance(pd.DataFrame({"x": [3]}))
    assert s.resistance["x"].tolist() == [1, 2, 3]
