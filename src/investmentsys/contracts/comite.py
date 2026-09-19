"""Gate del comité formal (S8, ADR-014): qué se le presentó al usuario y qué aprobó.

``ResumenComite`` es lo que el Director muestra ANTES de correr; ``SolicitudComite`` lo guarda
en la sesión junto al token de un solo uso; ``AprobacionComite`` es lo que queda en el acta
(``RunState.aprobacion``): el resumen presentado y las dos invocaciones —la que lo presentó y
la que lo confirmó—, que son por construcción turnos distintos del usuario.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, model_validator

from investmentsys.contracts.common import ContractBase, Ticker, validar_mismo_universo
from investmentsys.contracts.session import SessionConstraints
from investmentsys.contracts.universe import EstadoPrior, PriorProvenance, UniverseVersion
from investmentsys.contracts.views import MarketViews


class ResumenComite(ContractBase):
    """Lo que el usuario aprueba: con qué universo, prior, restricciones y material se corre."""

    universe_version: UniverseVersion
    activos: tuple[Ticker, ...] = Field(min_length=1)
    inicio_datos: dict[Ticker, date] = Field(description="Primer precio de cada activo.")
    estado_prior: EstadoPrior
    procedencias_prior: dict[Ticker, PriorProvenance]
    restricciones: SessionConstraints
    fecha_decision: date | None = Field(
        default=None, description="None = el último cierre disponible al correr."
    )
    views_de_partida: MarketViews | None = Field(
        default=None,
        description=(
            "Views exploratorias ya conversadas, si las hay. El Analista del comité las recibe "
            "como material citado y emite las suyas: las del acta son las que él valide."
        ),
    )
    material_usuario: str | None = Field(
        default=None, description="Material citado, no verificado, que recibirá el Analista."
    )

    @model_validator(mode="after")
    def _coherencia(self) -> ResumenComite:
        validar_mismo_universo(self.inicio_datos, self.activos, "inicio_datos")
        validar_mismo_universo(self.procedencias_prior, self.activos, "procedencias_prior")
        if self.estado_prior is EstadoPrior.PENDIENTE:
            raise ValueError("un comité no se resume con el prior pendiente: resuélvelo antes")
        neutrales = {p is PriorProvenance.NEUTRAL for p in self.procedencias_prior.values()}
        if neutrales != {self.estado_prior is EstadoPrior.NEUTRAL}:
            raise ValueError("procedencias_prior: neutral es todo-o-nada (ADR-013)")
        if self.restricciones.universe_version != self.universe_version:
            raise ValueError("restricciones: selladas con otro universo")
        if self.views_de_partida is not None and self.views_de_partida.activos != self.activos:
            raise ValueError("views_de_partida: de otro universo")
        return self


class SolicitudComite(ContractBase):
    """Estado de sesión entre ``solicitar`` y ``ejecutar``. El token vale una sola vez."""

    token: str = Field(min_length=1)
    resumen: ResumenComite
    solicitado_en: datetime
    invocacion: str = Field(min_length=1, description="invocation_id del turno que solicitó.")


class AprobacionComite(ContractBase):
    """Evidencia auditable en el acta: qué se presentó y en qué turno se confirmó."""

    resumen: ResumenComite
    solicitado_en: datetime
    confirmado_en: datetime
    invocacion_solicitud: str = Field(min_length=1)
    invocacion_confirmacion: str = Field(min_length=1)

    @model_validator(mode="after")
    def _secuencia(self) -> AprobacionComite:
        if self.invocacion_confirmacion == self.invocacion_solicitud:
            raise ValueError(
                "la confirmación ocurrió en el mismo turno que la solicitud: el usuario no "
                "pudo ver el resumen antes de aprobarlo"
            )
        if self.confirmado_en < self.solicitado_en:
            raise ValueError("confirmado_en anterior a solicitado_en")
        return self
