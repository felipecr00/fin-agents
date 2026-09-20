"""``consultar_mesa_trabajo``: la pizarra de la sesión y el roster de la sala (S9, ADR-016).

La mesa NO es un registro aparte que cada herramienta deba acordarse de escribir: es una
PROYECCIÓN del estado de sesión, armada cada vez que se consulta a partir de los mismos
contratos sellados que leen las herramientas. Así no puede desviarse de ellas: lo que la mesa
llama obsoleto es exactamente lo que ``exigir_sello`` rechazaría, elemento por elemento.

Todo el texto lo redacta el código (ningún párrafo de un LLM entra en la tabla) y las cifras
salen de los contratos. El roster sale de la composición real del equipo: los nombres de las
herramientas y sub-agentes con los que se construyó el Director (``componer_sala``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from investmentsys.config import Config
from investmentsys.contracts import (
    CandidatePortfolios,
    CategoriaPizarra,
    DiagnosticoCartera,
    Especialista,
    ItemPizarra,
    MarketViews,
    MesaDeTrabajoState,
    OrigenRestriccion,
    QuantEstimates,
    SessionConstraints,
    Silla,
    TipoView,
    Universe,
    View,
)
from investmentsys.data_manager import DiagnosticoUniverso, GestorDatos
from investmentsys.portfolio import sesion_por_defecto
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_DIAGNOSTICOS_CARTERA,
    CLAVE_MARKET_VIEWS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES_SESION,
    EstadoLegible,
    leer_lista,
    volcar,
)
from investmentsys.tools.ficha import ATIENDE, CLAVE_ANEXO, PREFIJO_NO_VALIDADO
from investmentsys.tools.gestor import ERRORES_DEL_GESTOR, adoptar_universo

NOMBRE_TOOL = "consultar_mesa_trabajo"

REHACER = {
    CategoriaPizarra.VISTAS: "vuelve a pedirlas al analista",
    CategoriaPizarra.ESTIMACION: "pídesela de nuevo al Estadístico",
    CategoriaPizarra.CARTERAS: "vuelve a construirlas",
    CategoriaPizarra.DIAGNOSTICO: "pídeselo de nuevo al Escéptico",
    CategoriaPizarra.RESTRICCION: "vuelve a indicarlas; rigen las de config.yaml",
}
ORIGEN_DEL_LIMITE = {
    OrigenRestriccion.DEFAULT_CONFIG: "por defecto de config.yaml",
    OrigenRestriccion.AJUSTE_USUARIO: "ajuste del usuario",
}
NOTA_EXPLORATORIO = (
    "Vistas, estimaciones, carteras y diagnósticos de la mesa son EXPLORATORIOS: no pasaron "
    "por el comité. Lo obsoleto no se puede usar: las herramientas lo rechazan."
)
AVISO_OBSOLETOS = (
    "**Atención: {n} elemento(s) obsoleto(s).** Rehazlos antes de construir carteras o de "
    "convocar al comité."
)
COMO_PRESENTAR = (
    "La tabla de la {vista} (y solo esa) se anexa SOLA al final de tu respuesta: no la copies "
    "ni la reconstruyas; coméntala en una o dos frases y declara uno por uno los "
    "`resultados_obsoletos`, si los hay."
)
VISTA_MESA = "mesa"
VISTA_SALA = "sala"


class SalaIncompletaError(ValueError):
    """El equipo tiene una herramienta o sub-agente al que nadie le asignó una silla."""


def componer_sala(herramientas: Iterable[str], sub_agentes: Iterable[str]) -> tuple[Silla, ...]:
    """El roster, a partir de los nombres REALES con los que se arma el equipo.

    El Director y los sub-agentes conversan (tienen voz propia); las demás sillas son
    herramientas deterministas.
    """
    herramientas, sub_agentes = tuple(herramientas), tuple(sub_agentes)
    sin_silla = sorted(n for n in (*herramientas, *sub_agentes) if n not in ATIENDE)
    if sin_silla:
        raise SalaIncompletaError(
            f"sin silla en la sala: {sin_silla}. Asígnales un especialista en tools/mesa.py"
        )
    sillas = []
    for especialista in Especialista:
        suyas = tuple(n for n in (*sub_agentes, *herramientas) if ATIENDE[n] is especialista)
        if suyas:
            conversa = especialista is Especialista.DIRECTOR or any(n in sub_agentes for n in suyas)
            sillas.append(Silla(especialista=especialista, conversa=conversa, herramientas=suyas))
    return tuple(sillas)


# --------------------------------------------------------------------- redacción
def _pct(valor: float, decimales: int = 1) -> str:
    return f"{valor * 100:.{decimales}f} %"


def _limite(valor: float) -> str:
    return f"{valor * 100:g} %"


def _pesos(pesos: Mapping[str, float]) -> str:
    return " / ".join(f"{a} {_pct(p)}" for a, p in pesos.items())


def _universo(universo: Universe, informe: DiagnosticoUniverso | None) -> str:
    activos = ", ".join(
        f"{d.ticker} (datos desde {d.fecha_inicio_datos:%Y-%m})" for d in universo.diagnosticos
    )
    partes = [activos]
    if informe is not None:
        v = informe.ventana_comun
        partes.append(
            f"ventana común {v.inicio:%Y-%m} a {v.fin:%Y-%m} ({v.meses} meses; la limita "
            f"{informe.activo_mas_corto})"
        )
    partes.append(f"prior: {universo.estado_prior.value}")
    return "; ".join(partes)


def _view(view: View) -> str:
    q = f"{view.q_anual * 100:+g} % anual"
    if view.tipo is TipoView.ABSOLUTA:
        cuerpo = f"{view.activos[0]} {q} (retorno total)"
    else:
        largos = "+".join(a for a, c in view.coeficientes.items() if c > 0)
        cortos = "+".join(a for a, c in view.coeficientes.items() if c < 0)
        cuerpo = f"{largos} sobre {cortos} {q}"
    return f"{cuerpo}, confianza {view.confianza:g}"


def _vistas(views: MarketViews) -> str:
    if not views.views:
        return f"sin views (al {views.fecha_decision}): el posterior es el equilibrio"
    return f"{len(views.views)} al {views.fecha_decision}: " + "; ".join(map(_view, views.views))


def _estimacion(e: QuantEstimates) -> str:
    metodos = ", ".join(str(m) for m in e.covarianzas)
    return (
        f"covarianza {metodos} y retornos históricos; muestra {e.fecha_inicio_muestra} a "
        f"{e.fecha_fin_muestra}, fecha de decisión {e.fecha_decision}, régimen {e.regimen.value}"
    )


def _carteras(ronda: CandidatePortfolios) -> str:
    nombres = ", ".join(c.nombre for c in ronda.candidatos)
    recomendada = ronda.portafolio_recomendado
    return (
        f"propuesta {ronda.iteracion} ({nombres}); recomendada {recomendada.nombre}: "
        f"{_pesos(recomendada.pesos)}"
    )


def _diagnostico(d: DiagnosticoCartera) -> str:
    m = d.metricas_oos
    return (
        f"cartera del usuario {_pesos(d.pesos_evaluados)}: Sharpe OOS {m.sharpe_oos:.2f}, "
        f"caída máxima {_pct(m.max_drawdown)}, volatilidad {_pct(m.volatilidad_anualizada)}"
    )


def describir_restricciones(s: SessionConstraints) -> str:
    general = (
        f"peso por activo entre {_limite(s.peso_min.valor)} "
        f"({ORIGEN_DEL_LIMITE[s.peso_min.origen]}) y {_limite(s.peso_max.valor)} "
        f"({ORIGEN_DEL_LIMITE[s.peso_max.origen]}); sin cortos"
    )
    propios = [
        f"{a} entre {_limite(x.minimo)} y {_limite(x.maximo)} ({ORIGEN_DEL_LIMITE[x.origen]})"
        for a, x in s.limites_por_activo.items()
    ]
    return "; ".join([general, *propios])


# ------------------------------------------------------------------ construcción
def construir_mesa(
    estado: EstadoLegible,
    universo: Universe,
    config: Config,
    informe: DiagnosticoUniverso | None = None,
) -> MesaDeTrabajoState:
    """La mesa que corresponde a ``estado`` sobre ``universo``. No modifica nada."""
    vigente = universo.version

    def sellado(
        categoria: CategoriaPizarra, contenido: str, origen: Especialista, sello: str | None
    ) -> ItemPizarra:
        return ItemPizarra.sellado(categoria, contenido, origen, sello, vigente, REHACER[categoria])

    items = [
        ItemPizarra(
            categoria=CategoriaPizarra.UNIVERSO,
            contenido=_universo(universo, informe),
            origen=Especialista.GESTOR_DATOS,
            universe_version=vigente,
        )
    ]
    crudas = estado.get(CLAVE_MARKET_VIEWS)
    if crudas:
        views = MarketViews.model_validate(crudas)
        ajenas = views.activos != universo.activos  # la regla de construir_candidatos
        items.append(
            ItemPizarra(
                categoria=CategoriaPizarra.VISTAS,
                contenido=_vistas(views),
                origen=Especialista.ANALISTA,
                obsoleto=ajenas,
                que_hacer=REHACER[CategoriaPizarra.VISTAS] if ajenas else None,
            )
        )
    cruda = estado.get(CLAVE_QUANT_ESTIMATES)
    if cruda:
        e = QuantEstimates.model_validate(cruda)
        items.append(
            sellado(
                CategoriaPizarra.ESTIMACION,
                _estimacion(e),
                Especialista.ESTADISTICO,
                e.universe_version,
            )
        )
    for ronda in leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios):
        items.append(
            sellado(
                CategoriaPizarra.CARTERAS,
                _carteras(ronda),
                Especialista.CONSTRUCTOR,
                ronda.universe_version,
            )
        )
    for d in leer_lista(estado, CLAVE_DIAGNOSTICOS_CARTERA, DiagnosticoCartera):
        items.append(
            sellado(
                CategoriaPizarra.DIAGNOSTICO,
                _diagnostico(d),
                Especialista.ESCEPTICO,
                d.universe_version,
            )
        )
    cruda = estado.get(CLAVE_RESTRICCIONES_SESION)
    sesion = (
        SessionConstraints.model_validate(cruda)
        if cruda
        else sesion_por_defecto(universo, config.optimizacion)
    )
    items.append(
        sellado(
            CategoriaPizarra.RESTRICCION,
            describir_restricciones(sesion),
            Especialista.CONSTRUCTOR,
            sesion.universe_version,
        )
    )
    return MesaDeTrabajoState(
        universe_version=vigente, activos=universo.activos, items=tuple(items)
    )


# --------------------------------------------------------------------- render
def _celda(texto: str) -> str:
    return " ".join(texto.replace("|", "\\|").split())


def renderizar_mesa(mesa: MesaDeTrabajoState) -> str:
    filas = [
        f"### Mesa de trabajo (universo `{mesa.universe_version[:12]}` | "
        f"{', '.join(mesa.activos)})",
        "",
        "| Categoría | Detalle | Especialista | Estado |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for item in mesa.items:
        estado = f"**Obsoleto**: {item.que_hacer}" if item.obsoleto else item.estado
        prefijo = PREFIJO_NO_VALIDADO if item.exploratorio else ""
        filas.append(
            f"| **{item.categoria.value}** | {prefijo}{_celda(item.contenido)} | "
            f"{item.origen.value} | {_celda(estado)} |"
        )
    pie = [NOTA_EXPLORATORIO]
    if mesa.obsoletos:
        pie.insert(0, AVISO_OBSOLETOS.format(n=len(mesa.obsoletos)))
    return "\n".join([*filas, "", *pie])


def renderizar_sala(sala: Iterable[Silla]) -> str:
    filas = [
        "### En la sala",
        "",
        "| Silla | Cómo participa | Atiende |",
        "| :--- | :--- | :--- |",
    ]
    for silla in sala:
        como = "conversa (LLM)" if silla.conversa else "herramientas deterministas"
        atiende = ", ".join(f"`{h}`" for h in silla.herramientas)
        filas.append(f"| **{silla.especialista.value}** | {como} | {atiende} |")
    return "\n".join(filas)


# ----------------------------------------------------------------------- tool
@dataclass(frozen=True)
class MesaTools:
    gestor: GestorDatos
    config: Config
    sala: tuple[Silla, ...]

    def consultar_mesa_trabajo(
        self, tool_context: ToolContext, vista: str = VISTA_MESA
    ) -> dict[str, Any]:
        """La mesa de trabajo de la sesión o quién está en la sala. No calcula ni modifica nada.

        Úsala para abrir la sesión (presenta el universo) y cuando pregunten «¿qué tenemos?» o
        «muestra la mesa» (vista="mesa"), o «¿quién está en la sala?» (vista="sala"). La mesa es
        el inventario de la sesión: universo, vistas, estimaciones, carteras, diagnósticos y
        restricciones, con el especialista que puso cada elemento y si sigue vigente u obsoleto
        (elemento por elemento, por su sello de universo). La sala es el roster real del equipo.

        Args:
            vista: "mesa" (por defecto) o "sala".
        """
        if vista not in (VISTA_MESA, VISTA_SALA):
            return {
                "status": "error",
                "tipo": "ValueError",
                "mensaje": f"vista desconocida '{vista}': usa '{VISTA_MESA}' o '{VISTA_SALA}'",
            }
        try:
            universo = self.gestor.universo()
            obsoletos = adoptar_universo(tool_context.state, universo)
            informe = self.gestor.diagnosticar(universo)
        except ERRORES_DEL_GESTOR as exc:
            return {"status": "error", "tipo": type(exc).__name__, "mensaje": str(exc)}
        mesa = construir_mesa(tool_context.state, universo, self.config, informe)
        tabla = renderizar_mesa(mesa) if vista == VISTA_MESA else renderizar_sala(self.sala)
        return {
            "status": "success",
            "universe_version": mesa.universe_version,
            "mesa": volcar(mesa),
            "sala": [volcar(s) for s in self.sala],
            "universo": informe.model_dump(mode="json"),
            "resultados_obsoletos": obsoletos,
            CLAVE_ANEXO: tabla,
            "como_presentar": COMO_PRESENTAR.format(vista=vista),
        }

    def function_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.consultar_mesa_trabajo)]
