"""Testes dos measurements (chamada, res_contato, resistividade, sev, sp).

Cobertura: cada measurement roda com ``FakeTransport`` scriptado, reproduzindo
a sequência de bytes esperada do firmware. Sem hardware. ``time.sleep`` é
monkeypatched para zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from delfos.central import Central
from delfos.events import EventBus, MeasurementSample, UnitResponse
from delfos.field import Field
from delfos.measurements import chamada, res_contato, resistividade, sev, sp
from delfos.protocol import SOF, Command
from delfos.storage import Paths, ResultsStore
from delfos.units import Units

# =============================================================================
# Helpers
# =============================================================================


def _write_addr_dat(p: Path, *, with_channel_2: bool = False) -> Path:
    lines = [
        "addr;kind;slot;channel;serial",
        "0x1080;channel;;1;100",
    ]
    if with_channel_2:
        lines.append("0x1280;channel;;2;101")
        lines.append("0x20ff;switch;1;;200")
    else:
        lines.append("0x20ff;switch;1;;200")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _vp_frame(addr: int, vp_value: int, n_pulsos: int = 5) -> bytes:
    f = bytearray(28)
    f[0] = SOF
    f[1] = (addr >> 8) & 0xFF
    f[2] = addr & 0xFF
    f[3] = Command.ENVIA_VARIAVEIS_GEO
    f[4] = n_pulsos
    f[7] = 2  # ganho
    same = vp_value.to_bytes(4, "little", signed=True)
    f[11:15] = same
    f[15:19] = same  # idêntico → maioria
    f[19:23] = (10).to_bytes(4, "little", signed=True)
    f[23:27] = same
    return bytes(f)


def _sp_frame(addr: int, raw1: int, raw2: int, raw3: int) -> bytes:
    f = bytearray(27)
    f[0] = SOF
    f[1] = (addr >> 8) & 0xFF
    f[2] = addr & 0xFF
    f[3] = Command.ENVIA_VARIAVEIS_GEO
    f[11:15] = raw1.to_bytes(4, "little", signed=True)
    f[15:19] = raw2.to_bytes(4, "little", signed=True)
    f[19:23] = raw3.to_bytes(4, "little", signed=True)
    return bytes(f)


def _measurement_frame(tensao_raw: int, corrente_raw: int, *, count: int = 0) -> bytes:
    """Frame de 16 bytes que vem após o ACK em ciclo de corrente / pulso de
    medida. Bytes 4-7 = tensao, 8-11 = corrente, 12 = count."""
    f = bytearray(16)
    f[0] = SOF
    f[3] = Command.CDO_TRANSMISSOR_CORRENTE
    f[4:8] = tensao_raw.to_bytes(4, "little", signed=False)
    f[8:12] = corrente_raw.to_bytes(4, "little", signed=True)
    f[12] = count
    return bytes(f)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Pula time.sleep durante o teste (afeta global, mas o monkeypatch é
    revertido ao final). Necessário porque res_contato/sev/sp/_helpers fazem
    sleeps reais."""
    import time

    monkeypatch.setattr(time, "sleep", lambda *_: None)


# =============================================================================
# chamada
# =============================================================================


def test_chamada_marks_unit_failures(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))

    # ping_central: ACK
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    # ping_unit(0x1080): ACK
    fake_transport.queue(make_response(0x1080, Command.ENVIA_ENDERECO))
    # ping_unit(0x20FF): nenhuma resposta (queue esgota → reads vazios) → falha

    received: list = []
    bus = EventBus()
    bus.subscribe(received.append)

    central = Central(fake_transport, n_tries=3)
    result = chamada(central, units, bus=bus)

    assert result.failed_units == [2]
    unit_responses = [e for e in received if isinstance(e, UnitResponse)]
    assert [u.unit_id for u in unit_responses] == [1, 2]
    assert [u.success for u in unit_responses] == [True, False]


def test_chamada_sets_cycle_when_provided(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    # set_cycle ACK
    fake_transport.queue(make_response(0xFFFD, Command.SET_CYCLE_PERIOD))
    # ping_central + ambas as unidades
    fake_transport.queue(make_response(0x0000, Command.ENVIA_ENDERECO))
    fake_transport.queue(make_response(0x1080, Command.ENVIA_ENDERECO))
    fake_transport.queue(make_response(0x20FF, Command.ENVIA_ENDERECO))

    central = Central(fake_transport)
    chamada(central, units, ciclo=0x36)
    # primeiro write é o set_cycle ('B')
    assert fake_transport.writes[0][3] == 0x42


# =============================================================================
# res_contato
# =============================================================================


def test_res_contato_two_pairs(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    field = Field(n_electrodes=3, spa_x=1.0)  # pares: (1,2) e (2,3)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="res")

    # Para cada par: 2 set_electrodes (zero + on) + 1 ACK CDO + 1 measurement_frame
    for _ in range(2):
        fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
        fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
        fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
        fake_transport.queue(_measurement_frame(20000, -3000))
    # Final off + current_off
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))

    samples: list = []
    bus = EventBus()
    bus.subscribe(lambda e: samples.append(e) if isinstance(e, MeasurementSample) else None)

    central = Central(fake_transport)
    res_contato(central, units, field, results, line=1, bus=bus)

    assert len(results.resistance) == 2
    assert results.resistance.loc[0, "eletrodo1"] == 1
    assert results.resistance.loc[0, "eletrodo2"] == 2
    assert results.resistance.loc[1, "eletrodo1"] == 2
    assert results.resistance.loc[1, "eletrodo2"] == 3
    # CSV foi salvo
    saved = (tmp_path / "out" / "L1" / "res" / "res.csv").read_text(encoding="utf-8")
    assert "eletrodo1" in saved
    # Eventos de resistance emitidos
    assert len([s for s in samples if s.kind == "resistance"]) == 2


# =============================================================================
# resistividade
# =============================================================================


def test_resistividade_one_channel_succeeds(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    field = Field(n_electrodes=8, spa_x=1.0)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="rest")

    # set_electrodes_all_boards (off=False): 2 frames CONEX_ELETRODO
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    # run_current_cycle: ACK + amostra com count=0
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    fake_transport.queue(_measurement_frame(10000, -2000, count=0))
    # read_vp para canal 1 (addr=0x1080)
    fake_transport.queue(_vp_frame(addr=0x1080, vp_value=1500, n_pulsos=5))

    central = Central(fake_transport)
    failed = resistividade(
        central, units, field, results,
        electrodes=[2, 3, -1, -1, -1, -1, -1, -1, -1],
        current_elec=[1, 4],
        channels=[1],
        line=1, power_ma=100, ciclos=5, step=4,
    )
    assert failed is False
    assert len(results.resistivity) == 1
    row = results.resistivity.iloc[0]
    assert row["canal"] == 1
    assert row["n_pulsos"] == 5
    assert row["step"] == 4


def test_resistividade_returns_true_when_n_pulsos_low(
    tmp_path, fake_transport, make_response
):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    field = Field(n_electrodes=8)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="rest")

    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    fake_transport.queue(_measurement_frame(0, 0, count=0))
    # n_pulsos = 0 → retry sinalizado
    fake_transport.queue(_vp_frame(addr=0x1080, vp_value=0, n_pulsos=0))

    central = Central(fake_transport)
    failed = resistividade(
        central, units, field, results,
        electrodes=[2, 3, -1, -1, -1, -1, -1, -1, -1],
        current_elec=[1, 4], channels=[1],
    )
    assert failed is True
    assert len(results.resistivity) == 0  # nada foi salvo


# =============================================================================
# sev
# =============================================================================


def test_sev_minimal_cycle(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="sev_t")

    # current_auto + start_geo + stop_geo + current_off
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    fake_transport.queue(make_response(0xBF03, Command.INICIA_MEDE_GEOFISICA))
    fake_transport.queue(make_response(0xBF03, Command.PARA_MEDE_GEOFISICA))
    fake_transport.queue(make_response(0x0000, Command.CDO_TRANSMISSOR_CORRENTE))
    # read_vp para canal 1
    fake_transport.queue(_vp_frame(addr=0x1080, vp_value=2000, n_pulsos=4))

    central = Central(fake_transport)
    # cicle_time=2 → 2*(2-2) = 0 iterações no loop interno
    sev(central, units, results, power_ma=100, cicle_time=2, step=1)

    assert len(results.sev) == 1
    row = results.sev.iloc[0]
    assert row["n_pulsos"] == 4
    assert row["step"] == 1


# =============================================================================
# sp
# =============================================================================


def test_sp_channel_2_inverts_sign(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat", with_channel_2=True))
    field = Field(n_electrodes=8)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="sp_t")

    # set_electrodes_all_boards (off=False): 2 frames
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    # start_geo + stop_geo
    fake_transport.queue(make_response(0xBF03, Command.INICIA_MEDE_GEOFISICA))
    fake_transport.queue(make_response(0xBF03, Command.PARA_MEDE_GEOFISICA))
    # read_sp para canal 2 (addr=0x1280)
    fake_transport.queue(_sp_frame(0x1280, 100_000, 200_000, 300_000))

    central = Central(fake_transport)
    sp(central, units, field, results, eletrodo=4, channel=2, is_fullwave=False)

    assert len(results.sp) == 1
    row = results.sp.iloc[0]
    # canal 2 inverte sinais
    assert row["SP1"] < 0
    assert row["SP2"] < 0
    assert row["SP3"] < 0


def test_sp_channel_1_keeps_sign(tmp_path, fake_transport, make_response):
    units = Units.load(_write_addr_dat(tmp_path / "addr.dat"))
    field = Field(n_electrodes=8)
    paths = Paths(files_root=tmp_path / "out", line="L1")
    results = ResultsStore(paths, base_name="sp_t")

    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0x20FF, Command.CONEX_ELETRODO))
    fake_transport.queue(make_response(0xBF03, Command.INICIA_MEDE_GEOFISICA))
    fake_transport.queue(make_response(0xBF03, Command.PARA_MEDE_GEOFISICA))
    fake_transport.queue(_sp_frame(0x1080, 100_000, 200_000, 300_000))

    central = Central(fake_transport)
    sp(central, units, field, results, eletrodo=4, channel=1, is_fullwave=False)

    row = results.sp.iloc[0]
    assert row["SP1"] > 0
    assert row["SP2"] > 0
    assert row["SP3"] > 0
