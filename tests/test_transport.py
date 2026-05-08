"""Testes do SerialTransport — usam o backend ``loop://`` do pyserial (sem hardware)."""

from __future__ import annotations

import time

import pytest

from delfos.transport import SerialTransport, available_ports


def test_context_manager_connects_and_disconnects():
    t = SerialTransport("loop://", timeout=0.05)
    assert not t.is_connected
    with t:
        assert t.is_connected
    assert not t.is_connected


def test_write_then_read_roundtrip():
    with SerialTransport("loop://", timeout=0.1) as t:
        t.write(b"\x7f\x00\x01\x41\x00\x00")
        echo = t.read(6)
        assert echo == b"\x7f\x00\x01\x41\x00\x00"


def test_read_returns_empty_on_timeout():
    with SerialTransport("loop://", timeout=0.05) as t:
        # nada escrito → read deve esgotar o timeout e retornar bytes vazios
        assert t.read(4) == b""


def test_set_timeout_actually_changes_read_timeout():
    with SerialTransport("loop://", timeout=0.5) as t:
        t.set_timeout(0.05)
        assert t.timeout == 0.05
        start = time.perf_counter()
        result = t.read(10)
        elapsed = time.perf_counter() - start
        assert result == b""
        # antes era 0.5s; agora 0.05 — margem generosa contra jitter de CI
        assert elapsed < 0.4


def test_write_when_not_connected_raises():
    t = SerialTransport("loop://")
    with pytest.raises(RuntimeError, match="not connected"):
        t.write(b"\x00")


def test_read_when_not_connected_raises():
    t = SerialTransport("loop://")
    with pytest.raises(RuntimeError, match="not connected"):
        t.read(1)


def test_double_connect_is_idempotent():
    t = SerialTransport("loop://")
    t.connect()
    t.connect()
    assert t.is_connected
    t.disconnect()


def test_double_disconnect_is_idempotent():
    t = SerialTransport("loop://")
    t.connect()
    t.disconnect()
    t.disconnect()
    assert not t.is_connected


def test_available_ports_returns_list_of_strings():
    # Smoke test: deve rodar sem erro em qualquer plataforma suportada.
    result = available_ports()
    assert isinstance(result, list)
    assert all(isinstance(p, str) for p in result)
