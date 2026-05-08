"""Testes do delfos.protocol — equivalente ao _smoke_tests() do módulo, em pytest."""

from __future__ import annotations

import pytest

from delfos.protocol import (
    BROADCAST_ADDR,
    COMMAND_FRAME_SIZE_MR64,
    SOF,
    Command,
    CyclePeriod,
    ResponseCode,
    ResponseFrame,
    StatusGeral,
    SystemState,
    addr_join,
    addr_split,
    build_command_frame,
    crc16_ccitt,
    is_grupo_sismica,
)


def test_crc16_known_vector():
    # Vector clássico CCITT-FALSE: crc16("123456789") == 0x29B1
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_crc16_empty():
    assert crc16_ccitt(b"") == 0xFFFF


def test_build_envia_endereco():
    f = build_command_frame(addr=0x0001, cmd=Command.ENVIA_ENDERECO)
    # Frame UASG = 7 bytes (SOF + ADDH + ADDL + CMD + P1 + P2 + P3).
    assert f == bytes([0x7F, 0x00, 0x01, 0x41, 0x00, 0x00, 0x00])


def test_build_set_cycle_broadcast():
    f = build_command_frame(
        addr=BROADCAST_ADDR,
        cmd=Command.SET_CYCLE_PERIOD,
        p1=CyclePeriod.CYCLE_8S_PULSE_2S,
    )
    assert f == bytes([0x7F, 0xFF, 0xFD, 0x42, 0x31, 0x00, 0x00])


def test_build_rejects_invalid_p1():
    with pytest.raises(ValueError, match="SET_CYCLE_PERIOD"):
        build_command_frame(addr=0, cmd=Command.SET_CYCLE_PERIOD, p1=0x33)


def test_build_mr64_frame():
    f = build_command_frame(
        addr=0x0010,
        cmd=Command.CONEX_ELETRODO,
        p1=0x55,
        p2=0x00,
        p3=0x01,
        extras=bytes(11),
    )
    assert len(f) == COMMAND_FRAME_SIZE_MR64
    assert f[3] == 0x52  # opcode
    assert f[4] == 0x55  # sub-comando MR64


def test_build_mr64_requires_11_byte_extras():
    with pytest.raises(ValueError, match="11 bytes"):
        build_command_frame(
            addr=0x0010,
            cmd=Command.CONEX_ELETRODO,
            p1=0x55,
            extras=bytes(5),
        )


def test_build_rejects_extras_on_short_frame():
    with pytest.raises(ValueError, match="MR64"):
        build_command_frame(addr=0, cmd=Command.ENVIA_ENDERECO, extras=bytes(11))


def test_build_rejects_addr_out_of_range():
    with pytest.raises(ValueError, match="0xFFFF"):
        build_command_frame(addr=0x10000, cmd=Command.ENVIA_ENDERECO)


def test_response_frame_parse_ack():
    raw = bytes(
        [
            SOF,  # 0
            0x00,
            0x01,  # 1-2 addr
            Command.PING_CENTRAL,  # 3 cmd
            0x00,
            0x00,
            0x00,
            0x00,  # 4-7 payload
            0x00,  # 8 StatusCorrente
            StatusGeral.CORRENTE_IP_ON,  # 9
            0x00,  # 10 StatusGeral1
            0x14,  # 11 sw_version
            SystemState.IDLE,  # 12
            ResponseCode.CENTRAL_RESPONDE,  # 13
            0x00,
            0x00,  # 14-15 pad
        ]
    )
    resp = ResponseFrame.parse(raw)
    assert resp.addr == 0x0001
    assert resp.cmd_enum == Command.PING_CENTRAL
    assert resp.is_ack
    assert resp.system_state == SystemState.IDLE
    assert StatusGeral.CORRENTE_IP_ON in resp.status_geral
    assert resp.error == ResponseCode.CENTRAL_RESPONDE


def test_response_frame_rejects_short():
    with pytest.raises(ValueError, match="16 bytes"):
        ResponseFrame.parse(bytes(15))


def test_response_frame_rejects_bad_sof():
    bad = bytearray(16)
    bad[0] = 0x00
    with pytest.raises(ValueError, match="SOF"):
        ResponseFrame.parse(bytes(bad))


def test_is_grupo_sismica():
    assert is_grupo_sismica(SystemState.MEDINDO_MASW_13)
    assert is_grupo_sismica(0xB7)
    assert not is_grupo_sismica(SystemState.IDLE)


def test_addr_split_join_roundtrip():
    assert addr_split(0xABCD) == (0xAB, 0xCD)
    assert addr_join(0xAB, 0xCD) == 0xABCD
