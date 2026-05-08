"""Testes do delfos.storage.paths."""

from __future__ import annotations

from pathlib import Path

from delfos.storage import Paths


def test_default_files_root_is_cwd_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Paths()
    assert p.files_root == tmp_path / "files"


def test_paths_resolves_under_line(tmp_path):
    p = Paths(files_root=tmp_path, line="L1")
    assert p.data_folder == tmp_path / "L1"
    assert p.system == tmp_path / "system"
    assert p.jobs == tmp_path / "system" / "jobs"
    assert p.addr_dat == tmp_path / "system" / "addr.dat"


def test_output_creates_parent_directory(tmp_path):
    p = Paths(files_root=tmp_path, line="L1")
    out = p.output("job1")
    assert out == tmp_path / "L1" / "output" / "job1 output.txt"
    assert out.parent.exists()


def test_resistance_data_sp_sev_paths(tmp_path):
    p = Paths(files_root=tmp_path, line="L1")
    assert p.resistance("j") == tmp_path / "L1" / "res" / "j.csv"
    assert p.data("j") == tmp_path / "L1" / "data" / "j.csv"
    assert p.sp("j") == tmp_path / "L1" / "sp" / "j.csv"
    assert p.sev("j") == tmp_path / "L1" / "sev" / "j.csv"
    assert p.processed("j") == tmp_path / "L1" / "processed" / "j.dat"


def test_default_line_is_data(tmp_path):
    p = Paths(files_root=tmp_path)
    assert p.line == "data"
    assert p.data_folder == tmp_path / "data"


def test_explicit_path_object_accepted(tmp_path):
    p = Paths(files_root=Path(tmp_path) / "altroot", line="L2")
    assert p.files_root == tmp_path / "altroot"
