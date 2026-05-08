"""Testes do delfos.units, usando fixture de addr.dat real."""

from __future__ import annotations

from pathlib import Path

import pytest

from delfos.units import Units

ADDR_DAT = Path(__file__).parent / "fixtures" / "addr.dat"


def test_load_real_addr_dat():
    u = Units.load(ADDR_DAT)
    df = u.df
    assert len(df) == 6
    # Hex strings devem ter virado int.
    assert df.loc[1, "end1"] == 0x00
    assert df.loc[1, "end2"] == 0x80
    assert df.loc[5, "end1"] == 0x65
    assert df.loc[5, "end2"] == 0xFF


def test_get_channels_filters_order_zero():
    u = Units.load(ADDR_DAT)
    ch = u.get_channels()
    # ids 1..4 são canais (order=0); 5 e 6 são switches.
    assert sorted(ch.index.tolist()) == [1, 2, 3, 4]
    assert (ch["order"] == 0).all()


def test_get_switches_filters_and_orders():
    u = Units.load(ADDR_DAT)
    sw = u.get_switches()
    # ids 5 e 6 com order=2 e 1 respectivamente → ordenado por order: id 6, id 5
    assert sw.index.tolist() == [6, 5]
    assert sw["order"].tolist() == [1, 2]


def test_addr_returns_combined_int():
    u = Units.load(ADDR_DAT)
    assert u.addr(1) == 0x0080
    assert u.addr(5) == 0x65FF


def test_ur_from_channel():
    u = Units.load(ADDR_DAT)
    ur = u.ur_from_channel(3)
    # canal 3 corresponde ao id=2 (end1=0x02, end2=0x80)
    assert ur.name == 2
    assert ur["end1"] == 0x02


def test_ur_from_channel_not_found():
    u = Units.load(ADDR_DAT)
    with pytest.raises(KeyError, match="99"):
        u.ur_from_channel(99)


def test_electrodes_for_order_first_board():
    # order=1: subtrai 0*32 e 1, então 1..32 viram 0..31
    out = Units.electrodes_for_order([1, 5, 32, 33], order=1)
    assert out == [0, 4, 31, 255]  # 33 cai fora


def test_electrodes_for_order_second_board():
    # order=2: subtrai 1*32 e 1, então 33..64 viram 0..31
    out = Units.electrodes_for_order([32, 33, 64, 65], order=2)
    assert out == [255, 0, 31, 255]


def test_electrodes_for_order_disconnected_marker():
    # 255 (não conectado) deve passar para fora do range → continua 255
    out = Units.electrodes_for_order([255, 1, 255], order=1)
    assert out == [255, 0, 255]


def test_get_redirected_no_op_without_redirects():
    u = Units.load(ADDR_DAT)
    e = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    out_e, out_c = u.get_redirected(e, [1, 3])
    assert out_e is e
    assert out_c == [1, 3]


def test_get_redirected_remaps_channel():
    u = Units.load(ADDR_DAT)
    u.redirect_channel(1, 3)
    e = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    out_e, out_c = u.get_redirected(e, [1])
    # canal 1 → 3: dipolo (e[0], e[1]) = (10, 20) vai para posições (2, 3)
    assert out_c == [3]
    assert out_e[2] == 10
    assert out_e[3] == 20
    # demais posições ficam em -1
    assert out_e[0] == -1
    assert out_e[8] == -1
