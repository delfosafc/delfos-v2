"""Rotinas de medida — equivalentes às tasks do JSON job.

Cada módulo expõe uma função síncrona com a mesma assinatura geral:
``(central, units, field, results, ...kwargs, *, bus=None, abort=None)``.
Suportam abort cooperativo (verificam ``abort.is_set()`` em laços).
"""

from delfos.measurements._helpers import NO_ABORT, AbortFlag
from delfos.measurements.chamada import ChamadaResult, chamada
from delfos.measurements.res_contato import res_contato
from delfos.measurements.resistividade import resistividade
from delfos.measurements.sev import sev
from delfos.measurements.sp import sp

__all__ = [
    "NO_ABORT",
    "AbortFlag",
    "ChamadaResult",
    "chamada",
    "res_contato",
    "resistividade",
    "sev",
    "sp",
]
