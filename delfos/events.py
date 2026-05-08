"""EventBus + tipos de evento.

O núcleo do delfos não imprime nada — emite eventos pelo ``EventBus``. CLI,
TUI e GUIs externas se inscrevem para reagir (progresso, log de unidade,
amostras, abort, etc.).

Bus síncrono e simples — entrega na thread que publica.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Tipos de evento (todos imutáveis)
# =============================================================================


@dataclass(frozen=True)
class JobStarted:
    job_name: str
    n_steps: int


@dataclass(frozen=True)
class StepStarted:
    step: int
    task: str


@dataclass(frozen=True)
class StepCompleted:
    step: int
    task: str


@dataclass(frozen=True)
class Progress:
    current: int
    total: int

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round(100 * self.current / self.total, 1)


@dataclass(frozen=True)
class UnitResponse:
    unit_id: int
    success: bool
    detail: str = ""


@dataclass(frozen=True)
class MeasurementSample:
    """Uma amostra produzida durante uma medida.

    ``kind`` identifica o tipo (ex.: ``"resistance"``, ``"vp"``, ``"sp"``,
    ``"current_cycle"``). ``data`` é livre — cada consumidor decide o que
    extrair.
    """

    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobAborted:
    step: int
    reason: str = ""


@dataclass(frozen=True)
class JobFinished:
    job_name: str
    n_steps_completed: int


@dataclass(frozen=True)
class ErrorEvent:
    """Erro recuperável dentro de um job. Não interrompe — só sinaliza."""

    message: str
    detail: str = ""


# Alias prático para type hints
Event = (
    JobStarted
    | StepStarted
    | StepCompleted
    | Progress
    | UnitResponse
    | MeasurementSample
    | JobAborted
    | JobFinished
    | ErrorEvent
)


# =============================================================================
# Bus
# =============================================================================


class EventBus:
    """Pub/sub síncrono. Subscribers recebem na ordem de inscrição."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        # idempotente — sumir com callback que nunca esteve inscrito é OK.
        with contextlib.suppress(ValueError):
            self._subscribers.remove(callback)

    def publish(self, event: Event) -> None:
        for sub in list(self._subscribers):  # cópia: subscribers podem se desinscrever
            sub(event)


class NullBus(EventBus):
    """EventBus no-op. Útil em testes e em uso headless sem subscribers."""

    def publish(self, event: Event) -> None:  # noqa: ARG002
        return
