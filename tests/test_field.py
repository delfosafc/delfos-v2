"""Testes do delfos.field."""

from __future__ import annotations

from delfos.field import Field


def test_default_field_32_electrodes():
    f = Field(n_electrodes=32, spa_x=1.0)
    assert f.df.shape == (32, 2)
    assert f.df.index.tolist() == list(range(1, 33))
    # eletrodo 1 → x=0; eletrodo 32 → x=31
    assert f.pos(1) == (0.0, 0.0)
    assert f.pos(32) == (31.0, 0.0)


def test_field_with_spacing_and_offset():
    f = Field(n_electrodes=10, spa_x=2.5, ini_x=5.0)
    assert f.pos(1) == (5.0, 0.0)
    assert f.pos(10) == (27.5, 0.0)


def test_pos_unknown_electrode_returns_minus_one():
    f = Field(n_electrodes=8)
    assert f.pos(99) == (-1.0, -1.0)


def test_redirect_electrode_changes_position_lookup():
    f = Field(n_electrodes=8, spa_x=1.0)
    # eletrodo 5 redirecionado para 1 → pos(5) deve devolver pos(1)
    f.redirect_electrode(5, 1)
    assert f.pos(5) == f.pos(1)


def test_apply_redirects():
    f = Field(n_electrodes=8)
    f.set_redirects({5: 1, 6: 2})
    assert f.apply_redirects([5, 6, 7, 8]) == [1, 2, 7, 8]


def test_reconfigure_recomputes_positions():
    f = Field(n_electrodes=8, spa_x=1.0)
    assert f.pos(8) == (7.0, 0.0)
    f.reconfigure(spa_x=5.0)
    assert f.pos(8) == (35.0, 0.0)


def test_reconfigure_changes_n_electrodes():
    f = Field(n_electrodes=8)
    f.reconfigure(n_electrodes=16)
    assert f.df.shape[0] == 16
    assert f.pos(16) == (15.0, 0.0)
