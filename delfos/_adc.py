"""Constantes e helper de conversão ADC.

Os fatores foram extraídos de ``SB64_dash/switch.py`` e refletem o
escalonamento do firmware da DelfosCentralFT.
"""

from __future__ import annotations

# Tensão "geral" — usada em InfCorrenteTransm e leituras de res_contato.
ADC_TENSAO = 1000 / (1 << 16)

# Corrente (shunt) — sempre signed, leitura via canal de 28 bits.
ADC_CORRENTE = 1200 / (1 << 28)

# VP / SP — leitura via ENVIA_VARIAVEIS_GEO, 26 bits assinados.
ADC_VP = 1200 / (1 << 26)
ADC_SP = 1200 / (1 << 26)

# Variância de VP — 28 bits assinados.
ADC_VARVP = 1200 / (1 << 28)


def convert_adc(raw: int, const: float = ADC_TENSAO) -> float:
    """Converte um valor cru do ADC pelo fator informado, arredondando a 2 casas."""
    return round(raw * const, 2)
