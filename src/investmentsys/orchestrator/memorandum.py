"""Orden Preparatoria de Sesión (S9): el memorándum que el usuario revisa antes del comité.

Lo redacta el código desde el ``ResumenComite`` —el mismo contrato que queda en el acta como
evidencia de lo aprobado—, con el lenguaje de la propuesta v2 §6.1: parámetros fijados, qué hará
el comité y solicitud de confirmación. Es una revisión de orden, no un peaje: el usuario ve
exactamente con qué se va a sesionar.
"""

from __future__ import annotations

from investmentsys.contracts import EstadoPrior, ResumenComite
from investmentsys.tools.mesa import describir_restricciones

TITULO = "### Orden Preparatoria de Sesión — Comité formal"
PREGUNTA = "¿Confirmas la convocatoria formal para iniciar la deliberación?"
QUE_HARA = (
    "**Qué hará el comité.** El Analista emite las views de la corrida (recibe tu material y "
    "las views de partida CITADOS, sin verificar; sin ellos opina desde su conocimiento general "
    "con confianza topada); el Estadístico estima covarianzas y retornos; el Constructor propone "
    "y el Escéptico valida con poder de veto, hasta {max_iteraciones} iteraciones; el Secretario "
    "levanta el acta en `runs/` con esta orden y tu confirmación. Solo una cartera aprobada ahí "
    "es una recomendación."
)


def _prior(resumen: ResumenComite) -> str:
    if resumen.estado_prior is EstadoPrior.NEUTRAL:
        return "neutral equiponderado, aceptado para TODO el universo (sesgo documentado)"
    procedencias = ", ".join(f"{a} ({p.value})" for a, p in resumen.procedencias_prior.items())
    return f"equilibrio por capitalización; procedencia de cada cap: {procedencias}"


def renderizar_memorandum(resumen: ResumenComite, max_iteraciones: int) -> str:
    datos = ", ".join(f"{a} desde {f:%Y-%m}" for a, f in resumen.inicio_datos.items())
    fecha = resumen.fecha_decision.isoformat() if resumen.fecha_decision else "último cierre"
    views = resumen.views_de_partida.views if resumen.views_de_partida else ()
    material = (
        f"{len(resumen.material_usuario)} caracteres, citados y sin verificar"
        if resumen.material_usuario
        else "ninguno"
    )
    return "\n".join(
        [
            TITULO,
            "",
            "Comité listo para sesionar. Parámetros fijados:",
            f"- **Universo:** {', '.join(resumen.activos)} "
            f"(sello `{resumen.universe_version[:12]}`)",
            f"- **Datos:** {datos}",
            f"- **Prior:** {_prior(resumen)}",
            f"- **Restricciones:** {describir_restricciones(resumen.restricciones)}",
            f"- **Fecha de decisión:** {fecha}",
            f"- **Views de partida:** {len(views)} (exploratorias, solo como material citado)",
            f"- **Material del usuario:** {material}",
            "",
            QUE_HARA.format(max_iteraciones=max_iteraciones),
            "",
            "La orden vale una vez, para tu siguiente mensaje, y caduca si cambia cualquiera de "
            f"estos parámetros. {PREGUNTA}",
        ]
    )
