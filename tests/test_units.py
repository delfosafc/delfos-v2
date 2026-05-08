"""Testes do delfos.units, usando fixture de addr.dat real."""

from __future__ import annotations

from pathlib import Path

import pytest

from delfos.units import KIND_CHANNEL, KIND_SWITCH, Units

ADDR_DAT = Path(__file__).parent / "fixtures" / "addr.dat"


def test_load_real_addr_dat():
    u = Units.load(ADDR_DAT)
    df = u.df
    assert len(df) == 6
    # Endereços parseados como ints de 16 bits
    assert df.loc[1, "addr"] == 0x0080
    assert df.loc[5, "addr"] == 0x65FF
    assert df.loc[1, "kind"] == KIND_CHANNEL
    assert df.loc[5, "kind"] == KIND_SWITCH


def test_get_channels_filters_kind():
    u = Units.load(ADDR_DAT)
    ch = u.get_channels()
    # ids 1..4 são channels
    assert sorted(ch.index.tolist()) == [1, 2, 3, 4]
    assert (ch["kind"] == KIND_CHANNEL).all()


def test_get_switches_filters_and_orders():
    u = Units.load(ADDR_DAT)
    sw = u.get_switches()
    # id 5 tem slot=2, id 6 tem slot=1 → ordenado: id 6 (slot=1), id 5 (slot=2)
    assert sw.index.tolist() == [6, 5]
    assert sw["slot"].tolist() == [1, 2]


def test_addr_returns_combined_int():
    u = Units.load(ADDR_DAT)
    assert u.addr(1) == 0x0080
    assert u.addr(5) == 0x65FF


def test_ur_from_channel():
    u = Units.load(ADDR_DAT)
    ur = u.ur_from_channel(3)
    # canal 3 corresponde ao id=2 (addr=0x0280)
    assert ur.name == 2
    assert ur["addr"] == 0x0280


def test_ur_from_channel_not_found():
    u = Units.load(ADDR_DAT)
    with pytest.raises(KeyError, match="99"):
        u.ur_from_channel(99)


def test_electrodes_for_slot_first_board():
    # slot=1: subtrai 0*32 e 1, então 1..32 viram 0..31
    out = Units.electrodes_for_slot([1, 5, 32, 33], slot=1)
    assert out == [0, 4, 31, 255]  # 33 cai fora


def test_electrodes_for_slot_second_board():
    # slot=2: subtrai 1*32 e 1, então 33..64 viram 0..31
    out = Units.electrodes_for_slot([32, 33, 64, 65], slot=2)
    assert out == [255, 0, 31, 255]


def test_electrodes_for_slot_disconnected_marker():
    out = Units.electrodes_for_slot([255, 1, 255], slot=1)
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


# =============================================================================
# Migração v1 → v2 (formato legado)
# =============================================================================


def test_load_v1_format_emits_deprecation_warning(tmp_path):
    legacy = tmp_path / "addr_v1.dat"
    legacy.write_text(
        "id;end1;end2;serial;order;channel\n"
        "1;0x00;0x80;32770;0;1\n"
        "2;0x6C;0xff;65378;1;255\n",
        encoding="utf-8",
    )
    with pytest.warns(DeprecationWarning, match="schema v1"):
        u = Units.load(legacy)

    assert u.addr(1) == 0x0080
    assert u.df.loc[1, "kind"] == KIND_CHANNEL
    assert u.df.loc[1, "channel"] == 1

    assert u.addr(2) == 0x6CFF
    assert u.df.loc[2, "kind"] == KIND_SWITCH
    assert u.df.loc[2, "slot"] == 1


def test_load_unknown_schema_fails(tmp_path):
    bad = tmp_path / "weird.dat"
    bad.write_text("foo;bar\n1;2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Schema desconhecido"):
        Units.load(bad)


def test_load_v2_with_invalid_kind_fails(tmp_path):
    bad = tmp_path / "bad_kind.dat"
    bad.write_text(
        "addr;kind;slot;channel;serial\n"
        "0x0080;chanel;;1;32770\n",  # typo proposital
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="kind"):
        Units.load(bad)
