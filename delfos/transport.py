"""Transporte serial para comunicação com a DelfosCentralFT.

Substitui ``SB64_dash/myserial.py`` mantendo a mesma sequência de operações em
``write``: ``flush + reset_input + reset_output`` antes de cada envio, para
limpar restos de comandos anteriores. Não faz retry — quem precisa de retry é
a camada ``delfos.central``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import serial
from serial.tools import list_ports


class SerialTransport:
    """Conexão UART/USB com a Central. Use como context manager quando possível."""

    def __init__(self, port: str, *, baudrate: int = 115200, timeout: float = 0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Any = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, *, write_timeout: float = 0.1) -> None:
        if self.is_connected:
            return
        self._ser = serial.serial_for_url(
            url=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=write_timeout,
        )

    def disconnect(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def write(self, data: bytes | bytearray | Iterable[int]) -> int:
        ser = self._require_open()
        ser.flush()
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return ser.write(bytes(data))

    def read(self, n: int) -> bytes:
        ser = self._require_open()
        return ser.read(n)

    def set_timeout(self, timeout: float) -> None:
        self.timeout = timeout
        if self._ser is not None:
            self._ser.timeout = timeout

    def __enter__(self) -> SerialTransport:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    def _require_open(self) -> Any:
        if not self.is_connected:
            raise RuntimeError(f"SerialTransport({self.port!r}) is not connected")
        return self._ser


def available_ports() -> list[str]:
    """Lista portas seriais disponíveis no sistema (cross-platform).

    Usa ``serial.tools.list_ports`` para enumerar portas reais sem tentar abrir
    cada candidata — instantâneo no Windows (vs. ~25s scaneando COM1..COM256).
    """
    return [p.device for p in list_ports.comports()]
