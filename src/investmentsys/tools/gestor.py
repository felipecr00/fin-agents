"""Operaciones del Gestor de Datos (S7) para el Director conversacional (S8).

Desde S10 (ADR-020) el Director no las ve una a una: las despacha la tool única
``gestionar_datos_y_fricciones`` (``tools/fintual.py``). Aquí siguen el código y las custodias.

Misma regla que ``nucleo.py``: aquí no hay lógica de datos. Cada tool llama al Gestor, deja el
universo vigente en el estado de sesión y, si el universo cambió, DECLARA qué resultados de la
sesión quedaron obsoletos — detectado por ``universe_version`` (ADR-012), no de memoria. Un
error de dominio no lanza: devuelve ``{"status": "error", ...}`` con el mensaje del Gestor.

ADR-023 (lienzo en blanco): el universo de la sesión puede ser el GUARDADO (sus cambios se
persisten, como siempre) o uno EFÍMERO construido en la conversación, que vive solo en el estado
de sesión. ``base_de`` decide sobre cuál opera cada cambio; con la mesa limpia, la primera alta
crea un universo efímero y ``cargar_guardado`` es la única vía para trabajar sobre el guardado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.adk.tools.tool_context import ToolContext

from investmentsys.contracts import AssetDiagnostic, Universe
from investmentsys.data import DatosInvalidosError, TiingoError
from investmentsys.data_manager import GUARDADO, Base, GestorDatos, GestorError
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_DIAGNOSTICOS_CARTERA,
    CLAVE_MARKET_VIEWS,
    CLAVE_ORIGEN_UNIVERSO,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_SOLICITUD_COMITE,
    CLAVE_SOLICITUD_NEUTRAL,
    CLAVE_UNIVERSO,
    ORIGEN_GUARDADO,
    ORIGEN_SESION,
    SIN_UNIVERSO,
    Estado,
    EstadoLegible,
    volcar,
)

UNIDAD_CAP = "US$ billones en escala larga: 1 = 10^12 dólares (un 'trillion' en inglés)"
ERRORES_DEL_GESTOR = (GestorError, TiingoError, DatosInvalidosError)

# (clave del estado, cómo llamarlo ante el usuario, qué hacer)
SELLADOS = (
    (CLAVE_QUANT_ESTIMATES, "estimaciones del Estadístico", "pídeselas de nuevo al Estadístico"),
    (CLAVE_CANDIDATOS, "carteras candidatas", "vuelve a construirlas"),
    (
        CLAVE_DIAGNOSTICOS_CARTERA,
        "diagnósticos de carteras del usuario",
        "pídele de nuevo el diagnóstico al Escéptico",
    ),
)


SOLO_LECTURA = (
    "este despliegue no admite cambios de universo (el almacén de datos es de solo lectura: "
    "{detalle}). Haz el cambio en local (make run-local o make universo) y vuelve a desplegar"
)
NEUTRAL_EXIGE_OTRO_TURNO = (
    "degradar el prior requiere confirmación explícita en un turno posterior; presenta la "
    "advertencia todo-o-nada y espera. Afecta a TODOS los activos del universo ({activos}): "
    "las capitalizaciones presentes ({con_cap}) dejan de usarse y el prior pasa a ser "
    "equiponderado, con el sesgo documentado en ADR-013. Si el usuario confirma en su "
    "siguiente mensaje, repite la operación aceptar_prior_neutral"
)


PREGUNTA_PRIOR = (
    "sin capitalización en la fuente (ETF o similar): NO entró al universo todavía. Pregunta al "
    "usuario, por este activo, en este orden: (a) [recomendada] aporta la capitalización del "
    "subyacente o índice que replica → incorporar con ticker, prior_cap y prior_metodologia; "
    "(b) AUM como proxy débil → lo mismo con prior_metodologia 'AUM: proxy débil'; (c) degradar "
    "TODO el universo a prior neutral → incorporar solo con el ticker y luego "
    "aceptar_prior_neutral (todo-o-nada, confirmación en un turno posterior). Nunca propongas tú "
    "el valor de una capitalización"
)


def es_efimera(estado: EstadoLegible) -> bool:
    return bool(estado.get(CLAVE_ORIGEN_UNIVERSO) == ORIGEN_SESION)


def base_de(estado: EstadoLegible) -> Base:
    """Sobre qué universo opera un cambio pedido en esta sesión (ADR-023)."""
    if not es_efimera(estado):
        return GUARDADO
    crudo = estado.get(CLAVE_UNIVERSO)
    return Universe.model_validate(crudo) if crudo else None


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
        base = base_de(tool_context.state)
        return self._cambiar(
            tool_context,
            lambda: self.gestor.incorporar(ticker, prior_cap, prior_metodologia, base=base),
        )

    def resolver_lista(self, tickers: list[str]) -> dict[str, Any]:
        """``resolver`` para una lista: diagnóstico por activo, los que no se resolvieron y por
        qué, y la ventana común que tendría el universo SI ENTRAN TODOS los aptos (quién la
        limita, qué stress no cubre cada uno). No modifica nada."""
        try:
            diagnosticos, rechazados, informe = self.gestor.resolver_lista(tickers)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        return {
            "status": "success",
            "activos": [_activo(d) for d in diagnosticos],
            "no_resueltos": rechazados,
            "no_aptos": [d.ticker for d in diagnosticos if not d.apto],
            "sin_cap_en_la_fuente": [d.ticker for d in diagnosticos if d.apto and not d.tiene_cap],
            "si_entran_todos": None if informe is None else informe.model_dump(mode="json"),
        }

    def incorporar_lista(self, tickers: list[str], tool_context: ToolContext) -> dict[str, Any]:
        """Alta por lista, con la misma cascada por activo: entra lo que no requiere una decisión
        del usuario; lo que no tiene cap en la fuente queda pendiente, con su pregunta."""
        try:
            resultado = self.gestor.incorporar_lista(tickers, base=base_de(tool_context.state))
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        except OSError as exc:
            return _error(GestorError(SOLO_LECTURA.format(detalle=exc)))
        extra = {
            "incorporados": list(resultado.incorporados),
            "rechazados": resultado.rechazados,
            "pendientes_de_prior": [
                {"activo": _activo(d), "que_preguntar": PREGUNTA_PRIOR}
                for d in resultado.pendientes_de_prior
            ],
            "universo_completo": not resultado.pendientes_de_prior,
        }
        if resultado.universo is None or not resultado.incorporados:
            return {
                "status": "success",
                "universe_version": (tool_context.state.get(CLAVE_UNIVERSO) or {}).get("version"),
                **extra,
                "nota": "ningún activo entró todavía: resuelve lo pendiente o lo rechazado",
            }
        nuevo = resultado.universo
        return {**self._cambiar(tool_context, lambda: nuevo), **extra}

    def cargar_guardado(self, tool_context: ToolContext) -> dict[str, Any]:
        """Carga en la sesión el universo GUARDADO del Gestor (el del modo comando), con sus
        diagnósticos. Desde aquí, las altas y bajas de la sesión se persisten en él."""
        try:
            universo = self.gestor.universo()
            tool_context.state[CLAVE_ORIGEN_UNIVERSO] = ORIGEN_GUARDADO
            obsoletos = adoptar_universo(tool_context.state, universo)
            informe = self.gestor.diagnosticar(universo)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        return {
            "status": "success",
            "universe_version": universo.version,
            "origen": "universo guardado del Gestor; los cambios de esta sesión se persisten en él",
            "universo": informe.model_dump(mode="json"),
            "activos": [_activo(d) for d in universo.diagnosticos],
            "estado_prior": informe.estado_prior.value,
            "mensaje_prior": informe.mensaje_prior,
            "resultados_obsoletos": obsoletos,
        }

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
        base = base_de(tool_context.state)
        return self._cambiar(
            tool_context,
            lambda: self.gestor.refrescar_cap(
                ticker.strip().upper(), prior_cap, prior_metodologia, base=base
            ),
        )

    def retirar(self, ticker: str, tool_context: ToolContext) -> dict[str, Any]:
        """Saca un activo del universo de trabajo. Su serie de precios se conserva en disco.

        Cambia el universo (otra ``universe_version``): ver ``resultados_obsoletos``.

        Args:
            ticker: activo que está en el universo, p. ej. "BNS".
        """
        base = base_de(tool_context.state)
        return self._cambiar(tool_context, lambda: self.gestor.retirar(ticker, base=base))

    def aceptar_prior_neutral(self, tool_context: ToolContext) -> dict[str, Any]:
        """Degrada el prior de TODO el universo a equal-weight (ADR-013). Todo o nada.

        Custodia por turnos: la primera llamada NO degrada; devuelve la advertencia que debes
        presentar. Solo una llamada en un turno POSTERIOR del usuario, sobre el mismo universo,
        ejecuta. Cambia el universo: ver ``resultados_obsoletos``.
        """
        try:
            universo = self._vigente(tool_context.state)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        estado = tool_context.state
        pendiente = estado.get(CLAVE_SOLICITUD_NEUTRAL) or {}
        advertido = pendiente.get("universe_version") == universo.version
        if not advertido or pendiente.get("invocacion") == tool_context.invocation_id:
            if not advertido:
                estado[CLAVE_SOLICITUD_NEUTRAL] = {
                    "universe_version": universo.version,
                    "invocacion": tool_context.invocation_id,
                }
            con_cap = [d.ticker for d in universo.diagnosticos if d.tiene_cap]
            return {
                "status": "rechazado",
                "tipo": "ConfirmacionPendiente",
                "motivo": NEUTRAL_EXIGE_OTRO_TURNO.format(
                    activos=", ".join(universo.activos), con_cap=", ".join(con_cap) or "ninguna"
                ),
            }
        base = base_de(estado)
        salida = self._cambiar(tool_context, lambda: self.gestor.aceptar_prior_neutral(base=base))
        if salida["status"] == "success":
            estado[CLAVE_SOLICITUD_NEUTRAL] = None
        return salida

    def diagnosticar(self, tool_context: ToolContext) -> dict[str, Any]:
        """Estado del universo vigente: activos con su diagnóstico, ventana común, cobertura
        de los stress tests, estado del prior (capitalizacion | neutral | pendiente) y
        advertencias. No modifica nada.
        """
        try:
            universo = self._vigente(tool_context.state)
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

    def _vigente(self, estado: EstadoLegible) -> Universe:
        """El universo de la sesión: el guardado se re-lee del disco (puede haber cambiado por
        ``make update-prices``); el efímero es el del estado. Mesa limpia = error de dominio."""
        base = base_de(estado)
        if isinstance(base, Universe):
            return base
        if base is None:
            raise GestorError(SIN_UNIVERSO)
        return self.gestor.universo()

    def _cambiar(self, ctx: ToolContext, operacion: Any) -> dict[str, Any]:
        try:
            nuevo: Universe = operacion()
            obsoletos = adoptar_universo(ctx.state, nuevo)
            informe = self.gestor.diagnosticar(nuevo)
        except ERRORES_DEL_GESTOR as exc:
            return _error(exc)
        except OSError as exc:  # contenedor: data/ es de solo lectura para el proceso
            return _error(GestorError(SOLO_LECTURA.format(detalle=exc)))
        return {
            "status": "success",
            "universe_version": nuevo.version,
            "activos": [_activo(d) for d in nuevo.diagnosticos],
            "estado_prior": informe.estado_prior.value,
            "mensaje_prior": informe.mensaje_prior,
            "resultados_obsoletos": obsoletos,
        }
