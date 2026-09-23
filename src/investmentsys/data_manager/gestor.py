"""Gestor de Datos: valida activos contra la fuente y mantiene el universo vigente (S7).

Determinista y sin LLM. Regla dura: ningún número sobre un activo no validado — aquí nace cada
``AssetDiagnostic`` y aquí se congelan las capitalizaciones del prior (ADR-013). Las caps solo
cambian por ``refrescar_cap``; todo cambio de input queda en el historial con la versión del
universo antes y después.

Dos clases de universo (ADR-023, lienzo en blanco):
- el GUARDADO (``data/universo.json``, versionado): el del modo comando, dev y prod. Toda
  operación con ``base=GUARDADO`` (el valor por defecto) lo lee del disco y lo persiste, como
  siempre;
- el de una SESIÓN efímera: ``base`` es el universo que trae la sesión (``None`` = mesa limpia).
  La operación devuelve el universo nuevo y NO toca ``universo.json`` ni su historial. Las series
  descargadas quedan en ``data/series/`` como caché, salvo las de un activo del universo
  guardado, que NUNCA se sobrescriben desde una sesión: se reutilizan con su diagnóstico y su
  cap congelada (solo ``make update-prices`` las cambia, con sus barreras de ADR-011).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pandas as pd
from pydantic import BaseModel, ConfigDict

from investmentsys.config import RAIZ_PROYECTO, Config
from investmentsys.contracts import (
    AssetDiagnostic,
    EstadoPrior,
    Frecuencia,
    OrigenActivo,
    PriorProvenance,
    Universe,
)
from investmentsys.data import DatosInvalidosError, SeriesPriceProvider
from investmentsys.data.actualizacion import (
    FORMATO_MARCA,
    escribir_series_atomico,
    validar_sanidad,
)
from investmentsys.data.series_provider import ruta_serie
from investmentsys.data_manager.fuente import (
    CierreDiario,
    Dividendo,
    FuenteActivos,
    MetadataActivo,
    TickerInexistenteError,
)
from investmentsys.portfolio.prior import mensaje_estado_prior
from investmentsys.risk.cobertura import Cobertura, advertencias_de_cobertura, cobertura_escenario

MONEDA_SOPORTADA = "USD"
SIN_UNIVERSO_EN_SESION = (
    "no hay universo configurado en la sesión: primero define con qué activos trabajar (una "
    "lista de tickers) o carga el universo guardado"
)


class GestorError(ValueError):
    """Error de dominio del Gestor: el mensaje dice qué pasó y qué hacer."""


class TickerNoResueltoError(GestorError):
    """Ticker inexistente, sin datos o en una moneda no soportada."""


class ActivoNoAptoError(GestorError):
    """El activo existe pero no cumple los mínimos para entrar al universo."""


class UniversoDesincronizadoError(GestorError):
    """Los diagnósticos del universo no corresponden a las series en disco."""


class _Guardado:
    """Centinela: la operación trabaja sobre el universo persistido y lo persiste."""

    def __repr__(self) -> str:
        return "GUARDADO"


GUARDADO: Final = _Guardado()
Base = Universe | None | _Guardado
"""Sobre qué universo opera un cambio: ``GUARDADO``, el de una sesión, o ``None`` (mesa limpia)."""


class _Informe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VentanaComun(_Informe):
    inicio: date
    fin: date
    meses: int


class CoberturaStress(_Informe):
    escenario: str
    completa: tuple[str, ...]
    parcial: tuple[str, ...]
    ninguna: tuple[str, ...]


class DiagnosticoUniverso(_Informe):
    universe_version: str
    ventana_comun: VentanaComun
    activo_mas_corto: str
    stress: tuple[CoberturaStress, ...]
    estado_prior: EstadoPrior
    sin_cap: tuple[str, ...]
    mensaje_prior: str
    advertencias: tuple[str, ...]


@dataclass(frozen=True)
class ResultadoLista:
    """Alta por lista: qué entró, qué espera una decisión del usuario y qué se rechazó."""

    universo: Universe | None
    incorporados: tuple[str, ...]
    pendientes_de_prior: tuple[AssetDiagnostic, ...]
    rechazados: dict[str, str]


@dataclass(frozen=True)
class GestorDatos:
    config: Config
    fuente: FuenteActivos | None = None
    raiz: Path = RAIZ_PROYECTO
    reloj: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    # ------------------------------------------------------------------ rutas
    @property
    def directorio_series(self) -> Path:
        return self.raiz / self.config.datos.directorio_series

    @property
    def ruta_universo(self) -> Path:
        return self.raiz / self.config.datos.gestor.ruta_universo

    @property
    def ruta_historial(self) -> Path:
        return self.raiz / self.config.datos.gestor.ruta_historial

    def provider(self) -> SeriesPriceProvider:
        return SeriesPriceProvider(self.directorio_series)

    # --------------------------------------------------------------- universo
    def universo(self) -> Universe:
        """El universo vigente, verificado contra las series en disco."""
        if not self.ruta_universo.is_file():
            raise GestorError(
                f"no hay universo en {self.ruta_universo}: siémbralo con scripts/migrar_series.py"
            )
        universo = Universe.model_validate_json(self.ruta_universo.read_text(encoding="utf-8"))
        for d in universo.diagnosticos:
            serie = self._serie_local(d.ticker)
            if (_fecha(serie.index[0]), _fecha(serie.index[-1]), len(serie)) != (
                d.fecha_inicio_datos,
                d.fecha_fin_datos,
                d.meses_disponibles,
            ):
                raise UniversoDesincronizadoError(
                    f"{d.ticker}: el diagnóstico ({d.fecha_inicio_datos} → {d.fecha_fin_datos}) no "
                    "corresponde a su serie en disco: ejecuta make update-prices (que "
                    "re-diagnostica) antes de calcular nada"
                )
        return universo

    def resolver(self, ticker: str) -> AssetDiagnostic:
        """Diagnóstico de ``ticker`` contra la fuente; no modifica nada."""
        return self._resolver(ticker)[0]

    def incorporar(
        self,
        ticker: str,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
        *,
        aceptar_neutral: bool = False,
        base: Base = GUARDADO,
    ) -> Universe:
        """Valida, descarga y (si ``base`` es el guardado) persiste ``ticker``; devuelve el
        universo nuevo.

        Sin ``prior_cap`` y sin cap en la fuente, el activo entra con el prior PENDIENTE: BL
        queda no disponible hasta que llegue la cap (``refrescar_cap``) o se acepte degradar
        TODO el universo a prior neutral (``aceptar_neutral=True``).
        """
        ticker = ticker.strip().upper()
        actual = self._actual(base)
        if actual is not None and ticker in actual.activos:
            raise GestorError(f"{ticker} ya está en el universo; para su cap usa refrescar_cap")
        del_guardado = None if isinstance(base, _Guardado) else self._del_guardado(ticker)
        if del_guardado is not None:
            # Sesión efímera + activo del universo guardado: su serie y su cap congelada son
            # las validadas; desde una sesión no se re-descargan ni se sobrescriben.
            diagnostico, serie = del_guardado, self._serie_local(ticker)
        else:
            diagnostico, serie = self._resolver(ticker)
        if not diagnostico.apto:
            raise ActivoNoAptoError(f"{ticker} no es apto: {'; '.join(diagnostico.advertencias)}")
        if del_guardado is None:
            self._exigir_sanidad(ticker, serie)
        if actual is not None:
            vigente = self.provider().precios(list(actual.activos))
            if serie.index[-1] != vigente.index[-1]:
                raise GestorError(
                    f"{ticker} llega a {serie.index[-1]:%Y-%m} y los datos del universo a "
                    f"{vigente.index[-1]:%Y-%m}: ejecuta make update-prices antes de incorporar"
                )
        if prior_cap is not None:
            diagnostico = self._con_cap_de_usuario(diagnostico, prior_cap, prior_metodologia)
        elif prior_metodologia is not None:
            raise GestorError("prior_metodologia sin prior_cap: falta el valor de la cap")

        if del_guardado is None:
            # Si ya hay un archivo de este ticker, es CACHÉ de un activo que no está en el
            # universo guardado (un retiro, una sesión anterior): se reemplaza sin respaldo. Los
            # respaldos protegen las series del guardado, y dos altas en el mismo segundo (un
            # lote) chocarían en la carpeta de respaldo.
            ruta_serie(self.directorio_series, ticker).unlink(missing_ok=True)
            marca = self.reloj().strftime(FORMATO_MARCA)
            escribir_series_atomico(
                serie.to_frame(ticker),
                self.directorio_series,
                self.config.datos.actualizacion,
                marca,
            )
        previos = actual.diagnosticos if actual is not None else ()
        origenes = dict(actual.origenes) if actual is not None else {}
        nuevo = self._armar(
            (*previos, diagnostico),
            {**origenes, ticker: OrigenActivo.AGREGADO_EN_SESION},
            (actual is not None and actual.prior_neutral_aceptado) or aceptar_neutral,
        )
        self._persistir_si(base, nuevo, actual, "incorporar", ticker, None, diagnostico)
        return nuevo

    def resolver_lista(
        self, tickers: list[str]
    ) -> tuple[tuple[AssetDiagnostic, ...], dict[str, str], DiagnosticoUniverso | None]:
        """Diagnóstico de cada ticker (sin modificar nada), por qué no se resolvió el que falle,
        y el informe agregado —ventana común, quién la limita— si entraran TODOS los aptos."""
        diagnosticos, rechazados = [], {}
        for ticker in _sin_repetir(tickers):
            try:
                diagnosticos.append(self.resolver(ticker))
            except GestorError as exc:
                rechazados[ticker] = str(exc)
        aptos = tuple(d for d in diagnosticos if d.apto)
        informe = None
        if aptos:
            origenes = {d.ticker: OrigenActivo.AGREGADO_EN_SESION for d in aptos}
            informe = self.diagnosticar(Universe.crear(aptos, origenes, False))
        return tuple(diagnosticos), rechazados, informe

    def incorporar_lista(self, tickers: list[str], *, base: Base = GUARDADO) -> ResultadoLista:
        """Alta por lista con la MISMA cascada por activo (ADR-013): entra lo que no necesita
        una decisión del usuario; un activo sin cap en la fuente NO entra aquí: queda pendiente
        de que el usuario resuelva su prior (cap del subyacente, AUM como proxy, o neutral)."""
        actual = self._actual(base)
        incorporados: list[str] = []
        pendientes: list[AssetDiagnostic] = []
        rechazados: dict[str, str] = {}
        for ticker in _sin_repetir(tickers):
            sesion: Base = GUARDADO if isinstance(base, _Guardado) else actual
            try:
                if actual is not None and ticker in actual.activos:
                    raise GestorError(f"{ticker} ya está en el universo")
                previo = None if isinstance(base, _Guardado) else self._del_guardado(ticker)
                diagnostico = previo or self.resolver(ticker)
                if diagnostico.apto and not diagnostico.tiene_cap:
                    pendientes.append(diagnostico)
                    continue
                actual = self.incorporar(ticker, base=sesion)
                incorporados.append(ticker)
            except GestorError as exc:
                rechazados[ticker] = str(exc)
        return ResultadoLista(actual, tuple(incorporados), tuple(pendientes), rechazados)

    def refrescar_cap(
        self,
        ticker: str,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
        *,
        base: Base = GUARDADO,
    ) -> Universe:
        """ÚNICA vía para cambiar una cap congelada: de la fuente, o la que aporte el usuario."""
        actual = self._exigir_actual(base)
        if ticker not in actual.activos:
            raise GestorError(f"{ticker} no está en el universo {list(actual.activos)}")
        antes = actual.diagnostico(ticker)
        if prior_cap is not None:
            despues = self._con_cap_de_usuario(antes, prior_cap, prior_metodologia)
        else:
            cap = self._fuente().capitalizacion(ticker)
            if cap is None:
                raise GestorError(
                    f"{ticker}: la fuente no expone su capitalización con calidad; apórtala con "
                    "prior_cap y prior_metodologia (para ETFs: capitalización del subyacente, "
                    "no AUM)"
                )
            despues = antes.model_copy(
                update={
                    "prior_cap": cap.valor_usd / self.config.datos.gestor.usd_por_unidad_cap,
                    "prior_provenance": PriorProvenance.FUENTE,
                    "prior_fuente_detalle": cap.detalle,
                    "prior_as_of": cap.as_of,
                }
            )
        despues = AssetDiagnostic.model_validate(despues.model_dump())
        nuevo = self._armar(
            tuple(despues if d.ticker == ticker else d for d in actual.diagnosticos),
            actual.origenes,
            actual.prior_neutral_aceptado,
        )
        self._persistir_si(base, nuevo, actual, "refrescar_cap", ticker, antes, despues)
        return nuevo

    def retirar(self, ticker: str, *, base: Base = GUARDADO) -> Universe:
        """Saca ``ticker`` del universo. Su serie se queda en disco como caché: no se borra."""
        ticker = ticker.strip().upper()
        actual = self._exigir_actual(base)
        if ticker not in actual.activos:
            raise GestorError(f"{ticker} no está en el universo {list(actual.activos)}")
        if len(actual.activos) == 1:
            raise GestorError(f"{ticker} es el único activo: un universo no puede quedar vacío")
        antes = actual.diagnostico(ticker)
        nuevo = self._armar(
            tuple(d for d in actual.diagnosticos if d.ticker != ticker),
            {a: o for a, o in actual.origenes.items() if a != ticker},
            actual.prior_neutral_aceptado,
        )
        self._persistir_si(base, nuevo, actual, "retirar", ticker, antes, None)
        return nuevo

    def aceptar_prior_neutral(self, *, base: Base = GUARDADO) -> Universe:
        """Confirmación explícita de degradar TODO el prior a equal-weight (ADR-013)."""
        actual = self._exigir_actual(base)
        if not actual.sin_cap:
            raise GestorError("todas las caps están presentes: no hay nada que degradar")
        nuevo = self._armar(actual.diagnosticos, actual.origenes, True)
        self._persistir_si(base, nuevo, actual, "aceptar_prior_neutral", None, None, None)
        return nuevo

    def sincronizar(self) -> Universe:
        """Re-diagnostica cada activo con su serie en disco (tras ``make update-prices``)."""
        actual = Universe.model_validate_json(self.ruta_universo.read_text(encoding="utf-8"))
        diagnosticos = tuple(
            self._diagnosticar_serie(d.ticker, d.nombre, d.moneda, self._serie_local(d.ticker), d)
            for d in actual.diagnosticos
        )
        nuevo = self._armar(diagnosticos, actual.origenes, actual.prior_neutral_aceptado)
        if nuevo.version != actual.version:
            self._persistir(nuevo, actual, "sincronizar", None, None, None)
        return nuevo

    def sembrar(self, metadatos: dict[str, MetadataActivo]) -> Universe:
        """Universo inicial desde ``config.portafolio`` y las caps pinneadas (migración S7)."""
        prior = self.config.prior_equilibrio
        diagnosticos = []
        for ticker in self.config.portafolio.activos:
            base = self._diagnosticar_serie(
                ticker, metadatos[ticker].nombre, MONEDA_SOPORTADA, self._serie_local(ticker), None
            )
            diagnosticos.append(
                base.model_copy(
                    update={
                        "prior_cap": prior.capitalizacion_usd_billones[ticker],
                        "prior_provenance": PriorProvenance.USUARIO,
                        "prior_fuente_detalle": prior.metodologia,
                        "prior_as_of": prior.as_of,
                    }
                )
            )
        nuevo = self._armar(
            tuple(diagnosticos),
            dict.fromkeys(self.config.portafolio.activos, OrigenActivo.CONFIG_INICIAL),
            False,
        )
        self._persistir(nuevo, None, "sembrar", None, None, None)
        return nuevo

    def diagnosticar(self, universo: Universe | None = None) -> DiagnosticoUniverso:
        universo = universo or self.universo()
        ds = universo.diagnosticos
        inicio = max(d.fecha_inicio_datos for d in ds)
        fin = min(d.fecha_fin_datos for d in ds)
        corto = min(ds, key=lambda d: d.meses_disponibles)
        stress = []
        for e in self.config.validacion.escenarios_stress:
            por = {
                c: [d.ticker for d in ds if cobertura_escenario(d.fecha_inicio_datos, e) is c]
                for c in Cobertura
            }
            stress.append(
                CoberturaStress(
                    escenario=e.nombre,
                    completa=tuple(por[Cobertura.COMPLETA]),
                    parcial=tuple(por[Cobertura.PARCIAL]),
                    ninguna=tuple(por[Cobertura.NINGUNA]),
                )
            )
        return DiagnosticoUniverso(
            universe_version=universo.version,
            ventana_comun=VentanaComun(
                inicio=inicio, fin=fin, meses=len(pd.date_range(inicio, fin, freq="ME"))
            ),
            activo_mas_corto=corto.ticker,
            stress=tuple(stress),
            estado_prior=universo.estado_prior,
            sin_cap=universo.sin_cap,
            mensaje_prior=mensaje_estado_prior(universo),
            advertencias=tuple(f"{d.ticker}: {a}" for d in ds for a in d.advertencias),
        )

    # ------------------------------------------- datos diarios de la fuente (S10)
    def dividendos(
        self, universo: Universe | None = None, activos: tuple[str, ...] | None = None
    ) -> dict[str, tuple[Dividendo, ...]]:
        """Ex-dividendos recientes de los ``activos`` (por defecto, todo el universo).

        Solo historia: no se proyecta ninguna fecha futura.
        """
        universo = universo or self.universo()
        dias = self.config.fintual.dias_historia_dividendos
        desde = self.reloj().date() - timedelta(days=dias)
        fuente = self._fuente()
        return {a: fuente.dividendos(a, desde) for a in self._del_universo(universo, activos)}

    def cierres(
        self, universo: Universe | None = None, activos: tuple[str, ...] | None = None
    ) -> dict[str, CierreDiario | None]:
        """Último cierre (crudo y ajustado) de los ``activos``, según la fuente."""
        universo = universo or self.universo()
        fuente = self._fuente()
        return {a: fuente.ultimo_cierre(a) for a in self._del_universo(universo, activos)}

    @staticmethod
    def _del_universo(universo: Universe, activos: tuple[str, ...] | None) -> tuple[str, ...]:
        pedidos = activos if activos is not None else universo.activos
        ajenos = sorted(set(pedidos) - set(universo.activos))
        if ajenos:
            raise GestorError(f"fuera del universo vigente: {ajenos}")
        return pedidos

    # ---------------------------------------------------------------- interno
    def _actual(self, base: Base) -> Universe | None:
        return self.universo() if isinstance(base, _Guardado) else base

    def _exigir_actual(self, base: Base) -> Universe:
        actual = self._actual(base)
        if actual is None:
            raise GestorError(SIN_UNIVERSO_EN_SESION)
        return actual

    def _del_guardado(self, ticker: str) -> AssetDiagnostic | None:
        """El diagnóstico de ``ticker`` en el universo guardado, si está allí (y hay guardado)."""
        try:
            guardado = self.universo()
        except GestorError:
            return None
        return guardado.diagnostico(ticker) if ticker in guardado.activos else None

    def _persistir_si(
        self,
        base: Base,
        nuevo: Universe,
        anterior: Universe | None,
        accion: str,
        ticker: str | None,
        antes: AssetDiagnostic | None,
        despues: AssetDiagnostic | None,
    ) -> None:
        if isinstance(base, _Guardado):
            self._persistir(nuevo, anterior, accion, ticker, antes, despues)

    def _fuente(self) -> FuenteActivos:
        if self.fuente is None:
            raise GestorError("esta operación necesita una fuente de mercado (Tiingo)")
        return self.fuente

    def _resolver(self, ticker: str) -> tuple[AssetDiagnostic, pd.Series[float]]:
        ticker = ticker.strip().upper()
        fuente = self._fuente()
        try:
            meta = fuente.metadata(ticker)
        except TickerInexistenteError as exc:
            raise TickerNoResueltoError(f"ticker inexistente: {exc}") from exc
        if meta.bolsa not in self.config.datos.gestor.bolsas_usd:
            raise TickerNoResueltoError(
                f"{ticker}: moneda no soportada (cotiza en '{meta.bolsa}'; solo se admiten bolsas "
                f"en USD: {list(self.config.datos.gestor.bolsas_usd)})"
            )
        try:
            serie = fuente.serie_mensual(ticker).dropna()
        except DatosInvalidosError as exc:
            raise TickerNoResueltoError(f"{ticker}: sin datos utilizables: {exc}") from exc
        if serie.empty:
            raise TickerNoResueltoError(f"{ticker}: sin datos de precio en la fuente")
        diagnostico = self._diagnosticar_serie(ticker, meta.nombre, MONEDA_SOPORTADA, serie, None)
        cap = fuente.capitalizacion(ticker)
        if cap is not None:
            diagnostico = diagnostico.model_copy(
                update={
                    "prior_cap": cap.valor_usd / self.config.datos.gestor.usd_por_unidad_cap,
                    "prior_provenance": PriorProvenance.FUENTE,
                    "prior_fuente_detalle": cap.detalle,
                    "prior_as_of": cap.as_of,
                }
            )
        return AssetDiagnostic.model_validate(diagnostico.model_dump()), serie

    def _diagnosticar_serie(
        self,
        ticker: str,
        nombre: str,
        moneda: str,
        serie: pd.Series[float],
        previo: AssetDiagnostic | None,
    ) -> AssetDiagnostic:
        inicio, meses = _fecha(serie.index[0]), len(serie)
        minimo = self.config.datos.gestor.meses_minimos_apto
        avisos = list(
            advertencias_de_cobertura(
                inicio,
                meses,
                self.config.validacion.escenarios_stress,
                self.config.datos.ventana_covarianza_meses,
            )
        )
        apto = meses >= minimo
        if not apto:
            avisos.insert(0, f"solo {meses} meses de historia; se exigen al menos {minimo}")
        return AssetDiagnostic(
            ticker=ticker,
            nombre=nombre,
            moneda=moneda,
            fecha_inicio_datos=inicio,
            fecha_fin_datos=_fecha(serie.index[-1]),
            frecuencia=Frecuencia.MENSUAL,
            meses_disponibles=meses,
            advertencias=tuple(avisos),
            apto=apto,
            prior_cap=previo.prior_cap if previo else None,
            prior_provenance=previo.prior_provenance if previo else None,
            prior_fuente_detalle=previo.prior_fuente_detalle if previo else None,
            prior_as_of=previo.prior_as_of if previo else None,
        )

    def _con_cap_de_usuario(
        self, diagnostico: AssetDiagnostic, cap: float, metodologia: str | None
    ) -> AssetDiagnostic:
        if not metodologia or not metodologia.strip():
            raise GestorError(
                f"{diagnostico.ticker}: una cap aportada por el usuario exige prior_metodologia "
                "(p. ej. 'capitalización del índice subyacente' o 'AUM: proxy débil')"
            )
        if cap <= 0:
            raise GestorError(f"{diagnostico.ticker}: prior_cap debe ser > 0 (US$ billones, 10^12)")
        return diagnostico.model_copy(
            update={
                "prior_cap": cap,
                "prior_provenance": PriorProvenance.USUARIO,
                "prior_fuente_detalle": metodologia.strip(),
                "prior_as_of": self.reloj().date(),
            }
        )

    def _exigir_sanidad(self, ticker: str, serie: pd.Series[float]) -> None:
        reglas = self.config.datos.actualizacion
        # Un activo nuevo puede empezar tarde: eso lo advierte el diagnóstico, no lo veta.
        reglas = reglas.model_copy(
            update={"activos_inicio_tardio": (*reglas.activos_inicio_tardio, ticker)}
        )
        problemas = validar_sanidad(
            serie.to_frame(ticker), reglas, self.config.datos.tiingo.fecha_inicio
        )
        if problemas:
            detalle = "; ".join(f"{p.regla} {p.mes or ''}: {p.detalle}" for p in problemas)
            raise ActivoNoAptoError(f"{ticker} no pasa la sanidad de datos: {detalle}")

    def _serie_local(self, ticker: str) -> pd.Series[float]:
        return SeriesPriceProvider(self.directorio_series, [ticker]).precios()[ticker]

    @staticmethod
    def _armar(
        diagnosticos: tuple[AssetDiagnostic, ...],
        origenes: dict[str, OrigenActivo],
        neutral_aceptado: bool,
    ) -> Universe:
        # La aceptación de neutral caduca sola cuando llega la última cap: deja de ser necesaria.
        falta_cap = any(not d.tiene_cap for d in diagnosticos)
        return Universe.crear(diagnosticos, origenes, neutral_aceptado and falta_cap)

    def _persistir(
        self,
        nuevo: Universe,
        anterior: Universe | None,
        accion: str,
        ticker: str | None,
        antes: AssetDiagnostic | None,
        despues: AssetDiagnostic | None,
    ) -> None:
        _escribir_atomico(self.ruta_universo, nuevo.model_dump_json(indent=2) + "\n")
        entrada: dict[str, Any] = {
            "marca": self.reloj().isoformat(),
            "accion": accion,
            "ticker": ticker,
            "prior_antes": _bloque_prior(antes),
            "prior_despues": _bloque_prior(despues),
            "estado_prior": nuevo.estado_prior.value,
            "version_antes": anterior.version if anterior else None,
            "version_despues": nuevo.version,
        }
        self.ruta_historial.parent.mkdir(parents=True, exist_ok=True)
        with self.ruta_historial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False, sort_keys=True) + "\n")


def _sin_repetir(tickers: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))


def _bloque_prior(d: AssetDiagnostic | None) -> dict[str, Any] | None:
    if d is None or not d.tiene_cap:
        return None
    return {
        "cap": d.prior_cap,
        "procedencia": d.prior_provenance.value if d.prior_provenance else None,
        "detalle": d.prior_fuente_detalle,
        "as_of": d.prior_as_of.isoformat() if d.prior_as_of else None,
    }


def _fecha(marca: Any) -> date:
    fecha: date = pd.Timestamp(marca).date()
    return fecha


def _escribir_atomico(destino: Path, texto: str) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, nombre = tempfile.mkstemp(
        dir=destino.parent, prefix=f".{destino.stem}_", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(nombre, destino)
    finally:
        Path(nombre).unlink(missing_ok=True)
