"""Fixtures compartilhadas — FakeTransport e helper de respostas válidas."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from delfos.protocol import SOF, ResponseCode


class FakeTransport:
    """Transporte fake compatível com SerialTransport para testes.

    Modo de uso: enfileire respostas em ``responses`` antes de chamar Central.
    Cada ``write`` é registrado em ``writes``; cada ``read`` consome a próxima
    resposta da fila.
    """

    def __init__(self, responses: list[bytes] | None = None, *, timeout: float = 0.1):
        self.writes: list[bytes] = []
        self.responses: list[bytes] = list(responses or [])
        self.timeout = timeout
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, **_: object) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def write(self, data: bytes | bytearray | Iterable[int]) -> int:
        if not self._connected:
            raise RuntimeError("FakeTransport not connected")
        b = bytes(data)
        self.writes.append(b)
        return len(b)

    def read(self, n: int) -> bytes:
        if not self._connected:
            raise RuntimeError("FakeTransport not connected")
        if not self.responses:
            return b""
        head = self.responses.pop(0)
        # respeita o tamanho pedido — se a resposta enfileirada é menor, devolve
        # o que tem (simula timeout); se é maior, devolve só os primeiros n bytes.
        return head[:n]

    def queue(self, response: bytes) -> None:
        self.responses.append(response)

    def set_timeout(self, timeout: float) -> None:
        self.timeout = timeout


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def make_response():
    """Fixture-factory: monta um frame de resposta válido (16 bytes default).

    Usage::

        fake_transport.queue(make_response(0x0010, Command.PING_CENTRAL))
    """

    def _make(
        addr: int,
        cmd: int,
        *,
        payload: bytes = bytes(4),
        status_geral: int = 0,
        status_geral1: int = 0,
        state: int = 0,
        error: int = ResponseCode.CENTRAL_RESPONDE,
        pad_to: int = 16,
    ) -> bytes:
        addh = (addr >> 8) & 0xFF
        addl = addr & 0xFF
        f = bytearray()
        f.append(SOF)
        f.append(addh)
        f.append(addl)
        f.append(int(cmd))
        f += bytes(payload[:4])
        if len(payload) < 4:
            f += bytes(4 - len(payload))
        f.append(0)              # 8: StatusCorrente
        f.append(status_geral)   # 9
        f.append(status_geral1)  # 10
        f.append(0x14)           # 11: sw_version
        f.append(state)          # 12: SystemState
        f.append(error)          # 13: ResponseCode
        f.append(0)              # 14: pad
        f.append(0)              # 15: pad
        while len(f) < pad_to:
            f.append(0)
        return bytes(f)

    return _make
