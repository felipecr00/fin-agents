"""Bitácora del comité (S11): cada hito va al estado de sesión Y a ``runs/<run_id>/bitacora.jsonl``.

- ``emitir`` valida el hito (``HitoComite``), lo añade a ``pipeline_milestones`` y escribe UNA
  línea JSON en la bitácora, con ``flush``: otra terminal la lee mientras el comité corre
  (``make bitacora``). Un disco de solo lectura (contenedor) no es un fallo: el estado basta.
- Las funciones ``detalle_*`` redactan el hito DESDE los contratos ya validados del estado. Las
  cifras que lleva un hito son las de las herramientas; ningún LLM escribe aquí.
- ``renderizar_cronologia`` es la narración del cierre: fases, rondas, vetos con su motivo y
  tiempos, en un bloque que entrega el código (ADR-017).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from investmentsys.contracts import (
    CandidatePortfolios,
    CronologiaComite,
    EventoComite,
    FaseComite,
    HitoComite,
    MarketViews,
    QuantEstimates,
    ValidationReport,
    Veredicto,
)
from investmentsys.tools.estado import Estado, EstadoLegible, agregar, leer_lista

CLAVE_HITOS = "pipeline_milestones"
ARCHIVO_BITACORA = "bitacora.jsonl"
TITULO_CRONOLOGIA = "### Cronología del comité"

Reloj = Callable[[], datetime]


def reloj_utc() -> datetime:
    return datetime.now(UTC)


def emitir(
    estado: Estado,
    carpeta: Path | None,
    reloj: Reloj,
    fase: FaseComite,
    iteracion: int,
    evento: EventoComite,
    detalle: str,
) -> HitoComite:
    """``carpeta``: ``runs/<run_id>/``; ``None`` = solo al estado (aún no hay corrida)."""
    hito = HitoComite(
        timestamp=reloj(), fase=fase, iteracion=iteracion, evento=evento, detalle=detalle
    )
    agregar(estado, CLAVE_HITOS, hito)
    if carpeta is not None:
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            with (carpeta / ARCHIVO_BITACORA).open("a", encoding="utf-8") as bitacora:
                bitacora.write(hito.model_dump_json() + "\n")
        except OSError:  # disco de solo lectura o efímero: los hitos siguen en el estado
            pass
    return hito


def leer_hitos(estado: EstadoLegible) -> tuple[HitoComite, ...]:
    return leer_lista(estado, CLAVE_HITOS, HitoComite)


def leer_bitacora(archivo: Path) -> tuple[HitoComite, ...]:
    lineas = archivo.read_text(encoding="utf-8").splitlines()
    return tuple(HitoComite.model_validate_json(linea) for linea in lineas if linea.strip())


# ------------------------------------------------------------------ redacción desde contratos
def _pct(valor: float) -> str:
    return f"{valor * 100:.1f} %"


def detalle_views(views: MarketViews | None) -> str:
    n = 0 if views is None else len(views.views)
    if n == 0:
        return "sin views: la corrida parte del prior de equilibrio."
    plural = "s" if n != 1 else ""
    return f"{n} view{plural} formalizada{plural} y validada{plural} contra el contrato."


def detalle_estimacion(estimaciones: QuantEstimates) -> str:
    return (
        f"covarianzas y retornos históricos estimados al {estimaciones.fecha_decision.isoformat()} "
        f"(muestra desde {estimaciones.fecha_inicio_muestra.isoformat()}; "
        f"régimen {estimaciones.regimen.value})."
    )


def detalle_propuesta(ronda: CandidatePortfolios) -> str:
    cartera = ronda.portafolio_recomendado
    pesos = ", ".join(f"{a} {_pct(cartera.pesos[a])}" for a in ronda.activos)
    return f"propuesta {ronda.iteracion} generada ({cartera.nombre}: {pesos})."


def detalle_veredicto(reporte: ValidationReport) -> str:
    if reporte.veredicto is Veredicto.APROBADA:
        return (
            f"APROBADA. El candidato {reporte.candidato_evaluado} cumple los "
            f"{len(reporte.criterios)} criterios de riesgo y gobernanza."
        )
    motivos = "; ".join(reporte.razones_rechazo) or "criterios incumplidos sin detalle"
    return f"VETO emitido. Motivo: {motivos}"


# ------------------------------------------------------------------------- cronología narrada
def _mmss(delta: timedelta) -> str:
    segundos = max(int(delta.total_seconds()), 0)
    return f"{segundos // 60:02d}:{segundos % 60:02d}"


def linea_con_tiempo(hito: HitoComite, inicio: datetime) -> str:
    """``+01:05`` **Escéptico (Validador)** · ronda 1: VETO…: igual en vivo que al cierre."""
    ronda = f" · ronda {hito.iteracion}" if hito.iteracion else ""
    return f"`+{_mmss(hito.timestamp - inicio)}` **{hito.fase.value}**{ronda}: {hito.detalle}"


def renderizar_cronologia(hitos: tuple[HitoComite, ...]) -> str:
    """Bloque markdown con la deliberación completa; vacío si no hubo hitos."""
    if not hitos:
        return ""
    cronologia = CronologiaComite(hitos=hitos)
    vetos = len(cronologia.vetos)
    resumen = (
        f"{cronologia.iteraciones} ronda{'s' if cronologia.iteraciones != 1 else ''} "
        f"Constructor ⇄ Escéptico, {vetos} veto{'s' if vetos != 1 else ''}, "
        f"duración total {_mmss(cronologia.duracion)} (mm:ss)."
    )
    inicio = cronologia.hitos[0].timestamp
    lineas = [
        f"{i}. {linea_con_tiempo(h, inicio)}" for i, h in enumerate(cronologia.hitos, start=1)
    ]
    return "\n".join([TITULO_CRONOLOGIA, "", resumen, "", *lineas])
