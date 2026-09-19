"""FunctionTools de ADK sobre el Gestor de Datos (S7), para el Director conversacional (S8).

Misma regla que ``nucleo.py``: aquí no hay lógica de datos. Cada tool llama al Gestor, deja el
universo vigente en el estado de sesión y, si el universo cambió, DECLARA qué resultados de la
sesión quedaron obsoletos — detectado por ``universe_version`` (ADR-012), no de memoria. Un
error de dominio no lanza: devuelve ``{"status": "error", ...}`` con el mensaje del Gestor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from investmentsys.contracts import AssetDiagnostic, Universe
from investmentsys.data import DatosInvalidosError, TiingoError
from investmentsys.data_manager import GestorDatos, GestorError
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_DIAGNOSTICOS_CARTERA,
    CLAVE_MARKET_VIEWS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_SOLICITUD_COMITE,
    CLAVE_UNIVERSO,
    Estado,
    volcar,
)

UNIDAD_CAP = "US$ billones en escala larga: 1 = 10^12 dólares (un 'trillion' en inglés)"
ERRORES_DEL_GESTOR = (GestorError, TiingoError, DatosInvalidosError)

# (clave del estado, cómo llamarlo ante el usuario, qué hacer)
SELLADOS = (
    (CLAVE_QUANT_ESTIMATES, "estimaciones del Estadístico", "vuelve a llamar a estimar_mercado"),
    (CLAVE_CANDIDATOS, "carteras candidatas", "vuelve a construirlas"),
    (CLAVE_DIAGNOSTICOS_CARTERA, "diagnósticos de carteras del usuario", "vuelve a diagnosticar"),
)


def _error(exc: Exception) -> dict[str, Any]:
    return {"status": "error", "tipo": type(exc).__name__, "mensaje": str(exc)}


def _sellos(crudo: Any) -> set[str | None]:
    elementos = crudo if isinstance(crudo, list) else [crudo]
    return {e.get("universe_version") for e in elementos if isinstance(e, dict)}


def _prior(d: AssetDiagnostic) -> dict[str, Any]:
    return {
        "tiene_cap": d.tiene_cap,
        "cap_usd_billones": d.prior_cap,
        "unidad_cap": UNIDAD_CAP,
        "procedencia": d.prior_provenance.value if d.prior_provenance else None,
        "detalle": d.prior_fuente_detalle,
        "as_of": d.prior_as_of.isoformat() if d.prior_as_of else None,
    }


def _activo(d: AssetDiagnostic) -> dict[str, Any]:
    return {
        "ticker": d.ticker,
        "nombre": d.nombre,
        "moneda": d.moneda,
        "datos": [d.fecha_inicio_datos.isoformat(), d.fecha_fin_datos.isoformat()],
        "frecuencia": d.frecuencia.value,
        "meses_disponibles": d.meses_disponibles,
        "huecos": [h.isoformat() for h in d.huecos],
        "apto": d.apto,
        "advertencias": list(d.advertencias),
        "prior": _prior(d),
    }


def adoptar_universo(estado: Estado, nuevo: Universe) -> list[dict[str, str]]:
    """Deja ``nuevo`` como universo vigente y devuelve lo que ese cambio dejó obsoleto.

    Los resultados sellados se quedan en el estado: las herramientas los rechazan por su sello.
    Las restricciones de la sesión y la solicitud al comité se retiran, porque solo tienen
    sentido sobre el universo para el que se crearon.
    """
    previo = (estado.get(CLAVE_UNIVERSO) or {}).get("version")
    estado[CLAVE_UNIVERSO] = volcar(nuevo)
    if previo is None or previo == nuevo.version:
        return []
    obsoletos = [
        {"resultado": nombre, "que_hacer": accion}
        for clave, nombre, accion in SELLADOS
        if estado.get(clave) and _sellos(estado.get(clave)) != {nuevo.version}
    ]
    views = estado.get(CLAVE_MARKET_VIEWS)
    if views and tuple(views.get("activos", ())) != nuevo.activos:
        obsoletos.append(
            {"resultado": "views del Analista", "que_hacer": "vuelve a pedirlas al analista"}
        )
    sesion = estado.get(CLAVE_RESTRICCIONES_SESION)
    if sesion is not None:
        estado[CLAVE_RESTRICCIONES_SESION] = None
        obsoletos.append(
            {
                "resultado": "restricciones de la sesión",
                "que_hacer": "rigen de nuevo las de config.yaml sobre el universo nuevo; si el "
                "usuario las había ajustado, debe volver a indicarlas",
            }
        )
    if estado.get(CLAVE_SOLICITUD_COMITE) is not None:
        estado[CLAVE_SOLICITUD_COMITE] = None
        obsoletos.append(
            {
                "resultado": "solicitud al comité (resumen y token)",
                "que_hacer": "el token quedó invalidado: vuelve a fase='solicitar'",
            }
        )
    return obsoletos


@dataclass(frozen=True)
class GestorTools:
    gestor: GestorDatos

    def resolver(self, ticker: str) -> dict[str, Any]:
        """Diagnostica un ticker contra la fuente de mercado SIN modificar nada.

        Devuelve desde cuándo hay datos, meses disponibles, advertencias (qué limita una
        historia corta), si es apto para entrar al universo y el bloque ``prior``: si
        ``tiene_cap`` es true la fuente expone su capitalización (valor congelado y fecha); si
        es false, hay que resolver el prior con el usuario antes o después del alta.

        Args:
            ticker: símbolo del activo, p. ej. "NVDA".
        """
        try:
            return {"status": "success", "activo": _activo(self.gestor.resolver(ticker))}
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)

    def incorporar(
        self,
        ticker: str,
        tool_context: ToolContext,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
    ) -> dict[str, Any]:
        """Da de alta un activo en el universo: valida, descarga su serie y lo persiste.

        Cambia el universo (otra ``universe_version``): la respuesta lista en
        ``resultados_obsoletos`` lo que dejó de valer. Sin ``prior_cap`` se usa la
        capitalización de la fuente si existe; si no existe, el activo entra con el prior
        PENDIENTE y Black-Litterman y el comité quedan bloqueados hasta resolverlo.

        Args:
            ticker: símbolo del activo.
            prior_cap: capitalización que APORTA EL USUARIO, en US$ billones (10^12). Nunca la
                estimes tú.
            prior_metodologia: obligatoria con prior_cap: de dónde sale, en palabras del
                usuario (p. ej. "capitalización del índice subyacente" o "AUM: proxy débil").
        """
        return self._cambiar(
            tool_context, lambda: self.gestor.incorporar(ticker, prior_cap, prior_metodologia)
        )

    def refrescar_cap(
        self,
        ticker: str,
        tool_context: ToolContext,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
    ) -> dict[str, Any]:
        """Única vía para cambiar la capitalización congelada de un activo del universo.

        Sin ``prior_cap`` la toma de la fuente; con ``prior_cap`` y ``prior_metodologia``,
        registra la que aporta el usuario. Cambia el universo: ver ``resultados_obsoletos``.

        Args:
            ticker: activo que ya está en el universo.
            prior_cap: capitalización aportada por el usuario, en US$ billones (10^12).
            prior_metodologia: obligatoria con prior_cap.
        """
        return self._cambiar(
            tool_context,
            lambda: self.gestor.refrescar_cap(ticker.strip().upper(), prior_cap, prior_metodologia),
        )

    def aceptar_prior_neutral(self, tool_context: ToolContext) -> dict[str, Any]:
        """Degrada el prior de TODO el universo a equal-weight (ADR-013). Todo o nada.

        Solo tras la confirmación explícita del usuario, advertido de que afecta a todos los
        activos y del sesgo de equal-weight. Cambia el universo: ver ``resultados_obsoletos``.
        """
        return self._cambiar(tool_context, self.gestor.aceptar_prior_neutral)

    def diagnosticar(self, tool_context: ToolContext) -> dict[str, Any]:
        """Estado del universo vigente: activos con su diagnóstico, ventana común, cobertura
        de los stress tests, estado del prior (capitalizacion | neutral | pendiente) y
        advertencias. No modifica nada.
        """
        try:
            universo = self.gestor.universo()
            obsoletos = adoptar_universo(tool_context.state, universo)
            informe = self.gestor.diagnosticar(universo)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        return {
            "status": "success",
            "universo": informe.model_dump(mode="json"),
            "activos": [_activo(d) for d in universo.diagnosticos],
            "resultados_obsoletos": obsoletos,
        }

    def _cambiar(self, ctx: ToolContext, operacion: Any) -> dict[str, Any]:
        try:
            nuevo: Universe = operacion()
            obsoletos = adoptar_universo(ctx.state, nuevo)
            informe = self.gestor.diagnosticar(nuevo)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        return {
            "status": "success",
            "universe_version": nuevo.version,
            "activos": [_activo(d) for d in nuevo.diagnosticos],
            "estado_prior": informe.estado_prior.value,
            "mensaje_prior": informe.mensaje_prior,
            "resultados_obsoletos": obsoletos,
        }

    def function_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(f)
            for f in (
                self.resolver,
                self.incorporar,
                self.aceptar_prior_neutral,
                self.refrescar_cap,
                self.diagnosticar,
            )
        ]
