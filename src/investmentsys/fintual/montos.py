"""Pesos → montos fraccionados en US$ (S10). Fintual compra fracciones: el monto es exacto.

Redondeo por MAYOR RESIDUO sobre centavos enteros: cada monto queda con ``decimales`` cifras y
la suma es EXACTAMENTE el valor de la cartera (un redondeo independiente por activo puede
perder o inventar centavos). Determinista: los empates se resuelven por orden de ticker.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from investmentsys.contracts.common import validar_suma


def montos_fraccionados(
    pesos: Mapping[str, float], valor_usd: float, decimales: int
) -> dict[str, float]:
    """Monto en US$ de cada activo; suman ``valor_usd`` redondeado a ``decimales``."""
    if valor_usd <= 0.0:
        raise ValueError(f"valor_usd debe ser positivo, no {valor_usd}")
    negativos = sorted(a for a, p in pesos.items() if p < 0.0)
    if negativos:
        raise ValueError(f"pesos negativos: {negativos}")
    validar_suma(pesos, 1.0, "pesos")
    escala = 10**decimales
    total = round(valor_usd * escala)
    exactos = {a: p * total for a, p in pesos.items()}
    unidades = {a: math.floor(x) for a, x in exactos.items()}
    sobrante = total - sum(unidades.values())
    por_residuo = sorted(pesos, key=lambda a: (-(exactos[a] - unidades[a]), a))
    for activo in por_residuo[:sobrante]:
        unidades[activo] += 1
    return {a: unidades[a] / escala for a in pesos}
