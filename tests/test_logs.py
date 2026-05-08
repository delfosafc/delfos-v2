"""Testes do delfos.storage.logs."""

from __future__ import annotations

import re

from delfos.storage import LogWriter, Paths


def test_writes_output_with_timestamp(tmp_path):
    log = LogWriter(Paths(files_root=tmp_path, line="L1"), base_name="job")
    log.output("hello")
    text = (tmp_path / "L1" / "output" / "job output.txt").read_text(encoding="utf-8")
    assert re.match(r"^\d{2}:\d{2}:\d{2} - hello\n$", text)


def test_writes_debug_and_error_to_separate_files(tmp_path):
    log = LogWriter(Paths(files_root=tmp_path, line="L1"), base_name="job")
    log.debug("dbg")
    log.error("err")
    assert (tmp_path / "L1" / "output" / "job debug.txt").exists()
    assert (tmp_path / "L1" / "output" / "job error.txt").exists()


def test_appends_multiple_lines(tmp_path):
    log = LogWriter(Paths(files_root=tmp_path, line="L1"), base_name="job")
    log.output("linha 1")
    log.output("linha 2")
    text = (tmp_path / "L1" / "output" / "job output.txt").read_text(encoding="utf-8")
    assert text.count("\n") == 2
    assert "linha 1" in text
    assert "linha 2" in text
