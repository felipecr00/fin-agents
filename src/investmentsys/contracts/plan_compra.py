"""Plan de Compra Neta, asesoría fiscal CONSULTIVA y acta operativa (S11, ADR-022).

- ``PlanCompraNeta`` (``fintual/cash_flow_alloc.py``): el flujo nuevo (aportes + dividendos) va
  100 % a los activos bajo su objetivo; el contrato NO tiene dónde escribir una venta.
- ``AsesoriaFiscal`` (``fintual/tax_filter.py``): escenarios ETIQUETADOS («Costo fiscal estimado:
  $X CLP»), nunca una prohibición. El escenario por defecto es siempre "sin ventas"; toda venta
  lleva su advertencia; una venta con pérdida se reconoce como tax-loss harvesting.
- ``OverrideFiscal`` y ``ActaOperativa``: si el usuario fuerza un escenario con venta, el acta
  guarda el escenario, la ADVERTENCIA QUE CRUZÓ —literal— y los dos turnos (el que la presentó y
  el que la forzó, distintos por construcción, como en ADR-014).

El sistema nunca ejecuta: produce el plan que el usuario ejecuta en la app. Todo contrato de
este módulo lleva ``DISCLAIMER_OPERATIVO`` y rechaza cualquier otro texto en su lugar.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Fraccion,
    Ticker,
    validar_activos_unicos,
)
from investmentsys.contracts.fintual import DISCLAIMER_OPERATIVO, PlanInercia
from investmentsys.contracts.universe import UniverseVersion


def _solo_el_operativo(texto: str) -> str:
    if texto != DISCLAIMER_OPERATIVO:
        raise ValueError("el disclaimer operativo no se reescribe ni se omite")
    return texto


DisclaimerOperativo = Annotated[str, AfterValidator(_solo_el_operativo)]

ETIQUETA_COSTO_FISCAL = "Costo fiscal estimado"
_CENTAVO = 0.005


def etiqueta_costo(costo_clp: float) -> str:
    """``«Costo fiscal estimado: $1.234.567 CLP»`` (miles con punto, sin decimales)."""
    return f"{ETIQUETA_COSTO_FISCAL}: ${round(costo_clp):,} CLP".replace(",", ".")


# ------------------------------------------------------------------------ plan de compra
class CompraNeta(ContractBase):
    activo: Ticker
    monto_usd: float = Field(ge=0.0, description="Compra en US$ fraccionados; 0 = no se compra.")
    deficit_usd: float = Field(
        ge=0.0, description="Cuánto le falta para su objetivo sobre la cartera CON el flujo."
    )
    peso_objetivo: Fraccion
    peso_antes: Fraccion
    peso_despues: Fraccion

    @model_validator(mode="after")
    def _solo_bajo_objetivo(self) -> CompraNeta:
        if self.monto_usd > 0.0 and self.deficit_usd <= 0.0:
            raise ValueError(f"{self.activo}: compra sin estar bajo su objetivo")
        # El redondeo por mayor residuo puede dar a un activo hasta UN centavo sobre su déficit.
        if self.monto_usd > self.deficit_usd + 2 * _CENTAVO + TOLERANCIA_NUMERICA:
            raise ValueError(f"{self.activo}: la compra excede lo que le falta para su objetivo")
        return self


class PlanCompraNeta(ContractBase):
    universe_version: UniverseVersion
    validado: bool = Field(description="El de la cartera objetivo: solo el comité da True.")
    origen_objetivo: str = Field(min_length=1)
    valor_cartera_usd: float = Field(gt=0.0, description="Antes del flujo.")
    aporte_usd: float = Field(ge=0.0)
    dividendos_usd: float = Field(ge=0.0)
    reinversion_usd: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Producto de una venta FORZADA por el usuario (override) que se reasigna con la "
            "misma regla. 0 en todo plan por defecto: el plan nunca origina una venta."
        ),
    )
    ventas_usd: float = Field(
        default=0.0, ge=0.0, le=0.0, description="Cero ventas: aquí no cabe otra cosa."
    )
    compras: tuple[CompraNeta, ...] = Field(min_length=1)
    inercia_antes: PlanInercia
    inercia_despues: PlanInercia
    disclaimer: DisclaimerOperativo = DISCLAIMER_OPERATIVO

    @property
    def flujo_usd(self) -> float:
        return self.aporte_usd + self.dividendos_usd + self.reinversion_usd

    @model_validator(mode="after")
    def _coherencia(self) -> PlanCompraNeta:
        validar_activos_unicos(c.activo for c in self.compras)
        if self.flujo_usd <= 0.0:
            raise ValueError("un plan de compra necesita flujo nuevo (aporte o dividendos)")
        total = sum(c.monto_usd for c in self.compras)
        if abs(total - self.flujo_usd) > _CENTAVO:
            raise ValueError(f"compras: suman {total:.2f}, el flujo es {self.flujo_usd:.2f}")
        for plan, valor, que in (
            (self.inercia_antes, self.valor_cartera_usd, "inercia_antes"),
            (self.inercia_despues, self.valor_cartera_usd + self.flujo_usd, "inercia_despues"),
        ):
            if abs(plan.valor_cartera_usd - valor) > _CENTAVO:
                raise ValueError(f"{que}: calculada sobre otro valor de cartera")
            if plan.universe_version != self.universe_version:
                raise ValueError(f"{que}: sellada con otro universo")
        return self


# --------------------------------------------------------------------- asesoría fiscal
class TipoEscenario(StrEnum):
    SIN_VENTAS = "sin_ventas"
    VENDER_HASTA_BANDA = "vender_hasta_banda"
    VENDER_HASTA_OBJETIVO = "vender_hasta_objetivo"


class BaseCosto(StrEnum):
    DECLARADA = "declarada"  # costo de adquisición del usuario (config.yaml)
    COTA_SIN_COSTO = "cota_sin_costo"  # no declarado: se asume que TODA la venta es ganancia
    NO_APLICA = "no_aplica"


class SupuestosFiscales(ContractBase):
    """Supuestos DEL USUARIO (``config.yaml: fintual.tributario``): no son hechos ni asesoría."""

    tasa_marginal: Fraccion
    usd_clp: float = Field(gt=0.0)
    costo_base_usd: dict[Ticker, float] = Field(default_factory=dict)


class EscenarioFiscal(ContractBase):
    id: str = Field(min_length=1, description="P. ej. 'VOOG:vender_hasta_banda'.")
    tipo: TipoEscenario
    por_defecto: bool
    activo: Ticker | None = None
    venta_usd: float = Field(ge=0.0)
    resultado_usd: float = Field(description="Ganancia (+) o pérdida (−) estimada de la venta.")
    base_costo: BaseCosto
    costo_fiscal_clp: float = Field(ge=0.0)
    perdida_realizable_clp: float = Field(ge=0.0)
    cosecha_de_perdidas: bool = Field(
        description="Tax-loss harvesting: la venta realiza una pérdida; estrategia legítima."
    )
    etiqueta: str
    efecto: str = Field(min_length=1, description="Cómo queda el activo respecto de su banda.")
    advertencia: str | None = Field(
        default=None, description="Lo que el usuario cruza si fuerza este escenario."
    )

    @model_validator(mode="after")
    def _coherencia(self) -> EscenarioFiscal:
        if self.etiqueta != etiqueta_costo(self.costo_fiscal_clp):
            raise ValueError("etiqueta: no corresponde al costo fiscal del escenario")
        sin_venta = self.tipo is TipoEscenario.SIN_VENTAS
        if sin_venta != (self.venta_usd == 0.0) or sin_venta != (self.activo is None):
            raise ValueError("solo el escenario sin ventas va sin activo y sin venta")
        if self.por_defecto != sin_venta:
            raise ValueError("el escenario por defecto es 'sin ventas', y solo ese")
        if sin_venta == (self.advertencia is not None):
            raise ValueError("toda venta lleva su advertencia; 'sin ventas' no tiene qué advertir")
        if self.cosecha_de_perdidas != (self.resultado_usd < 0.0):
            raise ValueError("cosecha_de_perdidas: es True si y solo si la venta realiza pérdida")
        if self.resultado_usd <= 0.0 and self.costo_fiscal_clp > 0.0:
            raise ValueError("sin ganancia no hay costo fiscal")
        if self.resultado_usd >= 0.0 and self.perdida_realizable_clp > 0.0:
            raise ValueError("sin pérdida no hay pérdida realizable")
        return self


class PerdidaLatente(ContractBase):
    """Un activo con pérdida no realizada: oportunidad de tax-loss harvesting, no una orden."""

    activo: Ticker
    perdida_latente_usd: float = Field(gt=0.0)
    perdida_latente_clp: float = Field(gt=0.0)


class AsesoriaFiscal(ContractBase):
    universe_version: UniverseVersion
    supuestos: SupuestosFiscales
    escenarios: tuple[EscenarioFiscal, ...] = Field(min_length=1)
    perdidas_latentes: tuple[PerdidaLatente, ...] = ()
    disclaimer: DisclaimerOperativo = DISCLAIMER_OPERATIVO

    @model_validator(mode="after")
    def _coherencia(self) -> AsesoriaFiscal:
        ids = [e.id for e in self.escenarios]
        if len(set(ids)) != len(ids):
            raise ValueError("ids de escenario repetidos")
        if [e.por_defecto for e in self.escenarios].count(True) != 1:
            raise ValueError("debe haber exactamente un escenario por defecto (sin ventas)")
        return self

    def escenario(self, id_: str) -> EscenarioFiscal:
        for e in self.escenarios:
            if e.id == id_:
                return e
        raise KeyError(id_)


# ------------------------------------------------------------------------ acta operativa
class OverrideFiscal(ContractBase):
    """El usuario forzó una venta pese a la advertencia. Queda TODO: qué, cuándo y qué cruzó."""

    escenario: EscenarioFiscal
    advertencia_cruzada: str = Field(min_length=1)
    plan_resultante: PlanCompraNeta = Field(
        description="El producto de la venta se reasigna con la misma regla de flujos."
    )
    presentado_en: AwareDatetime
    forzado_en: AwareDatetime
    invocacion_presentacion: str = Field(min_length=1)
    invocacion_override: str = Field(min_length=1)

    @model_validator(mode="after")
    def _secuencia(self) -> OverrideFiscal:
        if self.escenario.advertencia is None:
            raise ValueError("no hay nada que forzar: el escenario no lleva advertencia")
        if self.advertencia_cruzada != self.escenario.advertencia:
            raise ValueError("advertencia_cruzada: debe ser, literal, la del escenario forzado")
        if self.invocacion_override == self.invocacion_presentacion:
            raise ValueError(
                "el override ocurrió en el mismo turno que la advertencia: el usuario no pudo "
                "verla antes de cruzarla"
            )
        if self.forzado_en < self.presentado_en:
            raise ValueError("forzado_en anterior a presentado_en")
        return self


class ActaOperativa(ContractBase):
    id: str = Field(min_length=1)
    creado_en: AwareDatetime
    run_id_comite: str | None = Field(
        default=None, description="Corrida del comité que aprobó la cartera objetivo, si la hay."
    )
    plan: PlanCompraNeta
    asesoria: AsesoriaFiscal
    overrides: tuple[OverrideFiscal, ...] = ()
    ejecutado_por_el_sistema: Literal[False] = False
    disclaimer: DisclaimerOperativo = DISCLAIMER_OPERATIVO

    @model_validator(mode="after")
    def _coherencia(self) -> ActaOperativa:
        if self.asesoria.universe_version != self.plan.universe_version:
            raise ValueError("plan y asesoría sellados con universos distintos")
        ids = {e.id for e in self.asesoria.escenarios}
        ajenos = [o.escenario.id for o in self.overrides if o.escenario.id not in ids]
        if ajenos:
            raise ValueError(f"overrides de escenarios que no son de esta acta: {ajenos}")
        return self

    def con_override(self, override: OverrideFiscal) -> ActaOperativa:
        return ActaOperativa.model_validate(
            {**self.model_dump(), "overrides": (*self.overrides, override)}
        )


__all__ = [
    "ETIQUETA_COSTO_FISCAL",
    "ActaOperativa",
    "AsesoriaFiscal",
    "BaseCosto",
    "CompraNeta",
    "EscenarioFiscal",
    "OverrideFiscal",
    "PerdidaLatente",
    "PlanCompraNeta",
    "SupuestosFiscales",
    "TipoEscenario",
    "etiqueta_costo",
]
