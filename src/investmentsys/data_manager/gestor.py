"""Gestor de Datos: valida activos contra la fuente y mantiene el universo vigente (S7).

Determinista y sin LLM. Regla dura: ningún número sobre un activo no validado — aquí nace cada
``AssetDiagnostic`` y aquí se congelan las capitalizaciones del prior (ADR-013). Las caps solo
cambian por ``refrescar_cap``; todo cambio de input queda en el historial con la versión del
universo antes y después.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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
from investmentsys.data_manager.fuente import FuenteActivos, MetadataActivo, TickerInexistenteError
from investmentsys.portfolio.prior import mensaje_estado_prior
from investmentsys.risk.cobertura import Cobertura, advertencias_de_cobertura, cobertura_escenario

MONEDA_SOPORTADA = "USD"


class GestorError(ValueError):
    """Error de dominio del Gestor: el mensaje dice qué pasó y qué hacer."""


class TickerNoResueltoError(GestorError):
    """Ticker inexistente, sin datos o en una moneda no soportada."""


class ActivoNoAptoError(GestorError):
    """El activo existe pero no cumple los mínimos para entrar al universo."""


class UniversoDesincronizadoError(GestorError):
    """Los diagnósticos del universo no corresponden a las series en disco."""


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
    ) -> Universe:
        """Valida, descarga y persiste ``ticker``; devuelve el universo nuevo.

        Sin ``prior_cap`` y sin cap en la fuente, el activo entra con el prior PENDIENTE: BL
        queda no disponible hasta que llegue la cap (``refrescar_cap``) o se acepte degradar
        TODO el universo a prior neutral (``aceptar_neutral=True``).
        """
        ticker = ticker.strip().upper()
        actual = self.universo()
        if ticker in actual.activos:
            raise GestorError(f"{ticker} ya está en el universo; para su cap usa refrescar_cap")
        diagnostico, serie = self._resolver(ticker)
        if not diagnostico.apto:
            raise ActivoNoAptoError(f"{ticker} no es apto: {'; '.join(diagnostico.advertencias)}")
        self._exigir_sanidad(ticker, serie)
        vigente = self.provider().precios(list(actual.activos))
        if serie.index[-1] != vigente.index[-1]:
            raise GestorError(
                f"{ticker} llega a {serie.index[-1]:%Y-%m} y el almacén a "
                f"{vigente.index[-1]:%Y-%m}: ejecuta make update-prices antes de incorporar"
            )
        if prior_cap is not None:
            diagnostico = self._con_cap_de_usuario(diagnostico, prior_cap, prior_metodologia)
        elif prior_metodologia is not None:
            raise GestorError("prior_metodologia sin prior_cap: falta el valor de la cap")

        marca = self.reloj().strftime(FORMATO_MARCA)
        escribir_series_atomico(
            serie.to_frame(ticker), self.directorio_series, self.config.datos.actualizacion, marca
        )
        nuevo = self._armar(
            (*actual.diagnosticos, diagnostico),
            {**actual.origenes, ticker: OrigenActivo.AGREGADO_EN_SESION},
            actual.prior_neutral_aceptado or aceptar_neutral,
        )
        self._persistir(nuevo, actual, "incorporar", ticker, None, diagnostico)
        return nuevo

    def refrescar_cap(
        self,
        ticker: str,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
    ) -> Universe:
        """ÚNICA vía para cambiar una cap congelada: de la fuente, o la que aporte el usuario."""
        actual = self.universo()
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
        self._persistir(nuevo, actual, "refrescar_cap", ticker, antes, despues)
        return nuevo

    def aceptar_prior_neutral(self) -> Universe:
        """Confirmación explícita de degradar TODO el prior a equal-weight (ADR-013)."""
        actual = self.universo()
        if not actual.sin_cap:
            raise GestorError("todas las caps están presentes: no hay nada que degradar")
        nuevo = self._armar(actual.diagnosticos, actual.origenes, True)
        self._persistir(nuevo, actual, "aceptar_prior_neutral", None, None, None)
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

    # ---------------------------------------------------------------- interno
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
