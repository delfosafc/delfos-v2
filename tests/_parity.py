"""Helpers internos do test_parity — parser de debug.txt e ReplayTransport.

Não fazem parte do pacote ``delfos``: existem só para sustentar comparações
ponto-a-ponto contra capturas reais do switch.py legado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class ReplayEvent:
    kind: Literal["tx_rx", "rx_only"]
    tx: bytes
    rx: bytes
    line_no: int  # 1-based, para mensagens de erro


# =============================================================================
# Parser do debug.txt
# =============================================================================

_TS = r"\d\d:\d\d:\d\d"
_TX_RX = re.compile(rf"^{_TS} - ([0-9a-fA-F]*) -\s*([0-9a-fA-F]*)\s*$")
_RECEBIDO = re.compile(rf"^{_TS} - recebido - ([0-9a-fA-F]*)\s*mA\s*$")


def parse_debug_file(path: Path) -> list[ReplayEvent]:
    """Lê um ``<run> debug.txt`` e devolve a sequência de eventos serial.

    Eventos extraídos:
    - ``tx_rx``: linha ``HH:MM:SS - <tx> - <rx>`` — par write/read.
    - ``rx_only``: linha ``HH:MM:SS - recebido - <rx> mA`` — frame autônomo
      do firmware (durante ciclo de corrente).

    Linhas auxiliares (``passo``, ``eletrodos``, ``corrente``, ``X V - Y mA``)
    são ignoradas — não tocam a porta serial.
    """
    events: list[ReplayEvent] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line:
            continue

        m = _RECEBIDO.match(line)
        if m:
            rx = bytes.fromhex(m.group(1))
            events.append(ReplayEvent("rx_only", b"", rx, i))
            continue

        m = _TX_RX.match(line)
        if m:
            tx_hex, rx_hex = m.group(1), m.group(2)
            if not tx_hex:
                # linha sem tx (ex.: " - 0x... - ..." vazio) — improvável, pula.
                continue
            events.append(
                ReplayEvent(
                    "tx_rx",
                    bytes.fromhex(tx_hex),
                    bytes.fromhex(rx_hex),
                    i,
                )
            )
            continue
        # linhas auxiliares: passo, eletrodos, corrente, "X V - Y mA",
        # "(volts) V - (amps) mA", linhas vazias de eco etc. — ignorar.

    return events


# =============================================================================
# ReplayTransport — devolve RX gravados e valida TX byte-a-byte
# =============================================================================


@dataclass
class TXMismatch:
    """Diferença entre TX produzido pelo delfos e o gravado em campo."""

    index: int
    line_no: int
    expected: bytes
    actual: bytes

    def short(self) -> str:
        return (
            f"#{self.index} (linha {self.line_no} do debug.txt): "
            f"esperado {self.expected.hex()}, obtido {self.actual.hex()}"
        )


class ReplayTransport:
    """Transporte fake que serve a sequência ``events`` de um run real.

    Compatibilidade com ``SerialTransport``: ``write/read/set_timeout``,
    propriedade ``is_connected`` e atributo ``timeout``. Cada ``write``
    é casado com o próximo evento ``tx_rx`` da sequência; em modo strict
    (default) qualquer divergência levanta ``AssertionError``.
    """

    def __init__(self, events: list[ReplayEvent], *, strict: bool = True):
        self._events = events
        self._cursor = 0
        self._strict = strict
        self._read_buf = b""
        self.writes: list[bytes] = []
        self.mismatches: list[TXMismatch] = []
        self.timeout = 0.1
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, **_: object) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def set_timeout(self, t: float) -> None:
        self.timeout = t

    # --------------------------------------------------------------- writes

    def write(self, data) -> int:
        if not self._connected:
            raise RuntimeError("ReplayTransport not connected")
        b = bytes(data)
        self.writes.append(b)

        # Drena rx_only que precedem o próximo tx — frames autônomos.
        self._drain_rx_only()

        if self._cursor >= len(self._events):
            raise AssertionError(
                f"ReplayTransport: write além do fim da gravação "
                f"(cursor={self._cursor}/{len(self._events)}, tx={b.hex()})"
            )
        ev = self._events[self._cursor]
        if ev.kind != "tx_rx":  # defensive — _drain_rx_only já consumiu rx_only.
            raise AssertionError(
                f"ReplayTransport: esperava tx_rx no cursor {self._cursor}, "
                f"recebeu {ev.kind}"
            )

        if b != ev.tx:
            mismatch = TXMismatch(
                index=self._cursor, line_no=ev.line_no,
                expected=ev.tx, actual=b,
            )
            self.mismatches.append(mismatch)
            if self._strict:
                raise AssertionError(
                    f"TX mismatch — {mismatch.short()}\n"
                    f"  Total mismatches: {len(self.mismatches)}"
                )

        self._read_buf += ev.rx
        self._cursor += 1
        return len(b)

    # ---------------------------------------------------------------- reads

    def read(self, n: int) -> bytes:
        if not self._connected:
            raise RuntimeError("ReplayTransport not connected")
        if not self._read_buf:
            self._drain_rx_only()
        head, self._read_buf = self._read_buf[:n], self._read_buf[n:]
        return head

    # -------------------------------------------------------------- helpers

    def _drain_rx_only(self) -> None:
        while (
            self._cursor < len(self._events)
            and self._events[self._cursor].kind == "rx_only"
        ):
            self._read_buf += self._events[self._cursor].rx
            self._cursor += 1

    def remaining(self) -> int:
        return len(self._events) - self._cursor
