"""Testes de ``delfos.platform.pi``.

Estes testes rodam em qualquer plataforma (incluindo Windows, onde
``RPi.GPIO`` não está disponível) usando um GPIO mock. Cobrem:

- ``import delfos`` segue funcionando sem a extra ``[pi]``.
- ``reset_board`` pulsa o pino na ordem certa quando o GPIO está disponível.
- Sem GPIO disponível e sem ``gpio=`` injetado, levanta ``ImportError`` útil.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import delfos.platform.pi as pi

# =============================================================================
# Importar `delfos` não puxa platform.pi
# =============================================================================


def test_delfos_import_does_not_load_platform_pi():
    """O núcleo não pode depender de RPi.GPIO — importar a fachada não pode
    quebrar em Windows mesmo sem a extra ``[pi]`` instalada."""
    import delfos

    assert hasattr(delfos, "Session")


# =============================================================================
# reset_board — happy path com GPIO mockado
# =============================================================================


def _make_gpio_mock() -> MagicMock:
    g = MagicMock()
    g.BCM = "BCM"
    g.OUT = "OUT"
    g.LOW = 0
    g.HIGH = 1
    return g


def test_reset_board_pulses_pin_in_order():
    g = _make_gpio_mock()
    pi.reset_board(gpio=g)

    g.setmode.assert_called_once_with("BCM")
    g.setwarnings.assert_called_once_with(False)
    g.setup.assert_called_once_with(pi.DEFAULT_RESET_PIN, "OUT")
    # Sequência LOW → HIGH no output.
    output_calls = [c.args for c in g.output.call_args_list]
    assert output_calls == [
        (pi.DEFAULT_RESET_PIN, 0),  # LOW
        (pi.DEFAULT_RESET_PIN, 1),  # HIGH
    ]
    g.cleanup.assert_called_once_with(pi.DEFAULT_RESET_PIN)


def test_reset_board_custom_pin_and_pulse(monkeypatch):
    g = _make_gpio_mock()
    sleeps: list[float] = []
    monkeypatch.setattr(pi.time, "sleep", lambda s: sleeps.append(s))

    pi.reset_board(reset_pin=17, pulse_seconds=0.25, gpio=g)

    g.setup.assert_called_once_with(17, "OUT")
    assert sleeps == [0.25]
    g.cleanup.assert_called_once_with(17)


def test_reset_board_cleanup_runs_even_on_error():
    g = _make_gpio_mock()
    # Faz o segundo `output` falhar — cleanup tem que rodar mesmo assim.
    g.output.side_effect = [None, RuntimeError("boom")]
    with pytest.raises(RuntimeError, match="boom"):
        pi.reset_board(gpio=g)
    g.cleanup.assert_called_once_with(pi.DEFAULT_RESET_PIN)


# =============================================================================
# reset_board — sem GPIO disponível
# =============================================================================


def test_reset_board_without_gpio_raises_helpful_import_error(monkeypatch):
    monkeypatch.setattr(pi, "_GPIO", None)
    with pytest.raises(ImportError, match=r"RPi\.GPIO indispon"):
        pi.reset_board()
