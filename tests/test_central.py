"""Testes da camada delfos.central usando FakeTransport (sem hardware)."""

from __future__ import annotations

import numpy as np
import pytest

from delfos.central import (
    Central,
    ContactResistanceReading,
    CurrentReading,
    FullwaveReading,
    ProtocolError,
    SpReading,
    VpReading,
)
from delfos.protocol import (
    BROADCAST_ADDR,
    SOF,
    Command,
    CurrentCycleType,
    CyclePeriod,
    GeoVariable,
)

# Testes simples — eco de comando ---------------------------------------------


def test_ping_central(fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    c = Central(fake_transport)
    resp = c.ping_central(reset_time=48)
    assert resp.is_ack
    assert fake_transport.writes[0] == bytes([SOF, 0x00, 0x00, 0x41, 48, 0, 0])


def test_ping_unit(fake_transport, make_response):
    fake_transport.queue(make_response(0x0010, Command.ENVIA_ENDERECO))
    c = Central(fake_transport)
    resp = c.ping_unit(0x0010)
    assert resp.addr == 0x0010
    assert fake_transport.writes[0] == bytes([SOF, 0x00, 0x10, 0x41, 0, 0, 0])


def test_set_cycle_broadcast(fake_transport, make_response):
    fake_transport.queue(make_response(BROADCAST_ADDR, Command.SET_CYCLE_PERIOD))
    c = Central(fake_transport)
    c.set_cycle(CyclePeriod.CYCLE_8S_PULSE_2S)
    sent = fake_transport.writes[0]
    assert sent == bytes([SOF, 0xFF, 0xFD, 0x42, 0x31, 0x00, 0x00])


def test_liga_e_desliga_alim_uasgs(fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.LIGA_ALIM_UASGS))
    fake_transport.queue(make_response(0x0000, Command.DESLIGA_ALIM_UASGS))
    c = Central(fake_transport)
    c.liga_alim_uasgs()
    c.desliga_alim_uasgs()
    assert fake_transport.writes[0][3] == 0x4B
    assert fake_transport.writes[1][3] == 0x59


def test_current_off_and_auto(fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    c = Central(fake_transport)
    c.current_off()
    c.current_auto(corrente_ma=500)  # 500mA → 50 décimas
    sent_off = fake_transport.writes[0]
    sent_auto = fake_transport.writes[1]
    assert sent_off[3:6] == bytes([0x55, 0x30, 0x00])  # P1=DESLIGA
    assert sent_auto[3:6] == bytes([0x55, 0x33, 50])  # P1=AUTO_AJUSTE, P2=50


def test_current_auto_caps_at_1000ma(fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    c = Central(fake_transport)
    c.current_auto(corrente_ma=2500)  # > 1000mA, deve cortar em 100 décimas
    assert fake_transport.writes[0][5] == 100


def test_current_sequence_start(fake_transport, make_response):
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    c = Central(fake_transport)
    c.current_sequence_start(pwm=20, cycle_type=CurrentCycleType.UASGI_PULSOS_POS_NEG)
    sent = fake_transport.writes[0]
    assert sent[3:7] == bytes([0x55, 0x34, 20, 1])


def test_start_and_stop_geo(fake_transport, make_response):
    fake_transport.queue(make_response(0xBF03, Command.INICIA_MEDE_GEOFISICA))
    fake_transport.queue(make_response(0xBF03, Command.PARA_MEDE_GEOFISICA))
    c = Central(fake_transport)
    c.start_geo(GeoVariable.VP)
    c.stop_geo(GeoVariable.VP)
    assert fake_transport.writes[0][1:4] == bytes([0xBF, 0x03, 0x45])
    assert fake_transport.writes[1][1:4] == bytes([0xBF, 0x03, 0x46])


def test_clear_electrodes_broadcast(fake_transport, make_response):
    fake_transport.queue(make_response(BROADCAST_ADDR, Command.CONEX_ELETRODO))
    c = Central(fake_transport)
    c.clear_electrodes(BROADCAST_ADDR)
    sent = fake_transport.writes[0]
    assert sent == bytes([SOF, 0xFF, 0xFD, 0x52, 0x30, 0x30, 0x30])


def test_set_electrodes_mr64(fake_transport, make_response):
    fake_transport.queue(make_response(0x0010, Command.CONEX_ELETRODO))
    c = Central(fake_transport)
    electrodes = [3, 6,        # I+, I-
                  1, 2, 4, 5, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]  # S0..S8
    c.set_electrodes(addr=0x0010, electrodes=electrodes, line=1)
    sent = fake_transport.writes[0]
    # Frame MR64 = 19 bytes (7 header + 11 extras + 1 pad final)
    assert len(sent) == 19
    assert sent[0:4] == bytes([SOF, 0x00, 0x10, 0x52])
    assert sent[4] == 0xAA  # sub-comando "conecta"
    assert sent[5] == 3     # I+
    assert sent[6] == 6     # I-
    # S0..S8 + line + vago
    assert sent[7:16] == bytes([1, 2, 4, 5, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    assert sent[16] == 1    # line
    assert sent[17] == 0    # vago1
    assert sent[18] == 0    # pad final


def test_set_electrodes_validates_count():
    c = Central(fake_transport_unused := type("F", (), {})())  # noqa: F841
    with pytest.raises(ValueError, match="11 itens"):
        c.set_electrodes(addr=0, electrodes=[1, 2, 3], line=1)


def test_set_electrodes_validates_line():
    c = Central(type("F", (), {})())
    with pytest.raises(ValueError, match="line=8"):
        c.set_electrodes(addr=0, electrodes=[0] * 11, line=8)


def test_measure_contact_resistance_par_e_impar(fake_transport, make_response):
    fake_transport.queue(make_response(0xBF01, Command.RESIST_CONTATO))
    fake_transport.queue(make_response(0xBF00, Command.RESIST_CONTATO))
    c = Central(fake_transport)
    c.measure_contact_resistance(even=True)
    c.measure_contact_resistance(even=False)
    assert fake_transport.writes[0][1:3] == bytes([0xBF, 0x01])
    assert fake_transport.writes[1][1:3] == bytes([0xBF, 0x00])


def test_read_contact_resistance(fake_transport, make_response):
    payload = (123).to_bytes(2, "little") + b"\x00\x00"  # 4 bytes payload
    fake_transport.queue(
        make_response(0x0010, Command.ENVIA_RES_CONTATO, payload=payload)
    )
    c = Central(fake_transport)
    reading = c.read_contact_resistance(addr=0x0010)
    assert isinstance(reading, ContactResistanceReading)
    assert reading.resistencia == 246  # 123 × 2


# Testes com retry ------------------------------------------------------------


def test_retry_when_echo_does_not_match(fake_transport, make_response):
    # Primeira leitura: vazia (timeout). Segunda: válida.
    fake_transport.queue(b"")
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    c = Central(fake_transport, n_tries=3)
    resp = c.ping_central(reset_time=48)
    assert resp.is_ack
    assert len(fake_transport.writes) == 2  # repetiu a vez que falhou


def test_protocol_error_after_exhausting_tries(fake_transport, make_response):
    for _ in range(5):
        fake_transport.queue(b"")
    c = Central(fake_transport, n_tries=3)
    with pytest.raises(ProtocolError, match="3 tentativas"):
        c.ping_central()
    assert len(fake_transport.writes) == 3


# read_current / read_vp / read_sp / read_fullwave ----------------------------


def test_read_current(fake_transport, make_response):
    # Bytes 4-7 = tensão raw little-endian; 8-11 = corrente raw little-endian
    tensao_raw = 65000
    corrente_raw = -100000
    payload = tensao_raw.to_bytes(4, "little", signed=False)
    fake = bytearray(make_response(0x0000, Command.INF_CORRENTE_TRANSM, payload=payload[:4]))
    # corrente_raw em bytes 8-11
    fake[8:12] = corrente_raw.to_bytes(4, "little", signed=True)
    fake_transport.queue(bytes(fake))
    c = Central(fake_transport)
    reading = c.read_current()
    assert isinstance(reading, CurrentReading)
    assert reading.tensao_raw == tensao_raw
    assert reading.corrente_raw == corrente_raw
    assert reading.tensao > 0
    assert reading.corrente > 0


def test_read_vp_decodes_majority_vote(fake_transport, make_response):
    # Frame VP: 28 bytes. n_pulsos no byte 4, ganho no byte 7.
    # vp0 = bytes 11-14, vp1 = 15-18, vp2 = 23-26 (todos signed little-endian)
    # varvp = 19-22.
    f = bytearray(28)
    f[0] = SOF
    f[1] = 0x00  # ADDH (eco do addr=0x0010)
    f[2] = 0x10  # ADDL
    f[3] = Command.ENVIA_VARIAVEIS_GEO
    f[4] = 7   # n_pulsos
    f[7] = 3   # ganho
    same_vp = (1000).to_bytes(4, "little", signed=True)
    f[11:15] = same_vp
    f[15:19] = same_vp           # vp1 igual → maioria com 2
    f[19:23] = (50).to_bytes(4, "little", signed=True)
    f[23:27] = (9999).to_bytes(4, "little", signed=True)  # outlier
    fake_transport.queue(bytes(f))
    c = Central(fake_transport)
    reading = c.read_vp(addr=0x0010)
    assert isinstance(reading, VpReading)
    assert reading.vp_raw == 1000
    assert reading.n_pulsos == 7
    assert reading.ganho == 3


def test_read_sp(fake_transport, make_response):
    f = bytearray(27)
    f[0] = SOF
    f[1] = 0x00
    f[2] = 0x10
    f[3] = Command.ENVIA_VARIAVEIS_GEO
    # Valores grandes o bastante para sobreviver ao arredondamento
    # (ADC_SP = 1200/2^26 ≈ 1.79e-5, então raw precisa ser > ~28000 para 0.5).
    f[11:15] = (100_000).to_bytes(4, "little", signed=True)
    f[15:19] = (200_000).to_bytes(4, "little", signed=True)
    f[19:23] = (300_000).to_bytes(4, "little", signed=True)
    fake_transport.queue(bytes(f))
    c = Central(fake_transport)
    reading = c.read_sp(addr=0x0010)
    assert isinstance(reading, SpReading)
    assert reading.sp1 > 0
    assert reading.sp2 > reading.sp1
    assert reading.sp3 > reading.sp2


def test_read_fullwave(fake_transport, make_response):
    samples = np.array([1, -2, 3, -4, 5], dtype=np.int32)
    payload = samples.tobytes()  # 5 * 4 = 20 bytes
    tamanho_frame = len(payload) + 16  # convenção do firmware

    header = bytearray(13)
    header[0] = SOF
    header[1] = 0x00
    header[2] = 0x10
    header[3] = Command.ENVIA_VARIAVEIS_GEO
    header[11:13] = tamanho_frame.to_bytes(2, "little", signed=False)

    fake_transport.queue(bytes(header))   # cabeçalho
    fake_transport.queue(payload)         # corpo

    c = Central(fake_transport)
    reading = c.read_fullwave(addr=0x0010)
    assert isinstance(reading, FullwaveReading)
    assert reading.samples.tolist() == [1, -2, 3, -4, 5]


# run_current_cycle -----------------------------------------------------------


def test_measure_contact_resistance_pulse(fake_transport, make_response):
    # ACK do CDO_TRANSMISSOR_CORRENTE
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    # Frame de medida (segundo read, sem echo check)
    f = bytearray(16)
    f[0] = SOF
    f[3] = Command.CDO_TRANSMISSOR_CORRENTE
    f[4:8] = (50000).to_bytes(4, "little", signed=False)
    f[8:12] = (-1500).to_bytes(4, "little", signed=True)
    fake_transport.queue(bytes(f))

    from delfos.central import Central
    c = Central(fake_transport)
    reading = c.measure_contact_resistance_pulse(current_pwm=10)
    assert reading.tensao_raw == 50000
    assert reading.corrente_raw == -1500
    # ACK enviado: 0x55 P1=0x31 P2=10 P3=0
    sent = fake_transport.writes[0]
    assert sent[3:7] == bytes([0x55, 0x31, 10, 0])


def test_run_current_cycle_terminates_on_count_zero(fake_transport, make_response):
    # Resposta ao comando "U"
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    # Amostras subsequentes: count 3, 2, 1, 0
    for count in [3, 2, 1, 0]:
        f = bytearray(16)
        f[0] = SOF
        f[3] = Command.CDO_TRANSMISSOR_CORRENTE
        f[4:8] = (10000).to_bytes(4, "little", signed=False)
        f[8:12] = (-2000).to_bytes(4, "little", signed=True)
        f[12] = count
        fake_transport.queue(bytes(f))
    c = Central(fake_transport)
    result = c.run_current_cycle(corrente_ma=200, stack=5)
    assert result.erro is False
    assert result.tensao > 0
    assert result.corrente > 0
