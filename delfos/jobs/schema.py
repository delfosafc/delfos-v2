"""Schema de Job/Step.

``Step`` é um dataclass mínimo com ``step`` (índice), ``task`` (nome da
operação) e ``params`` (kwargs específicos da task). Validação por task fica
no ``runner`` — aqui só descrevemos a forma.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    step: int
    task: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    steps: list[Step]
    name: str = "unnamed"
