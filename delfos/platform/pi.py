"""GPIO do Raspberry Pi — utilitário de reset da placa Delfos.

Não é importado por nenhum módulo do núcleo. Quem precisar de reset por
hardware faz ``from delfos.platform.pi import reset_board`` explicitamente.

Requer a extra ``[pi]`` (``RPi.GPIO``); em qualquer outra plataforma a
importação levanta ``ImportError`` com instrução de instalação.
"""

from __future__ import annotations

import time
from typing import Any

try:
    import RPi.GPIO as _GPIO  # type: ignore[import-not-found]
except (ImportError, RuntimeError) as _exc:
    # ImportError em Windows/macOS; RuntimeError pode ocorrer em Linux
    # não-ARM quando o `RPi.GPIO` está presente mas não consegue acessar /dev/gpiomem.
    _GPIO = None
    _IMPORT_ERROR: BaseException | None = _exc
else:
    _IMPORT_ERROR = None


DEFAULT_RESET_PIN = 4
DEFAULT_PULSE_SECONDS = 0.1


def reset_board(
    reset_pin: int = DEFAULT_RESET_PIN,
    *,
    pulse_seconds: float = DEFAULT_PULSE_SECONDS,
    gpio: Any = None,
) -> None:
    """Pulsa ``reset_pin`` em LOW por ``pulse_seconds`` segundos para resetar
    a Central via hardware.

    ``gpio`` permite injetar um módulo alternativo (e.g. um mock em testes).
    Sem ele, usa ``RPi.GPIO`` carregado no import — falha com mensagem útil
    quando a extra ``[pi]`` não está instalada.
    """
    g = gpio if gpio is not None else _GPIO
    if g is None:
        raise ImportError(
            "RPi.GPIO indisponível — instale a extra `[pi]` em um Raspberry Pi "
            "(`uv sync --extra pi`) ou passe `gpio=` explicitamente."
        ) from _IMPORT_ERROR

    g.setmode(g.BCM)
    g.setwarnings(False)
    g.setup(reset_pin, g.OUT)
    try:
        g.output(reset_pin, g.LOW)
        time.sleep(pulse_seconds)
        g.output(reset_pin, g.HIGH)
    finally:
        g.cleanup(reset_pin)
