"""``MesaDeTrabajoState``: la pizarra de la sesión, inspeccionable por el usuario (S9, ADR-016).

Responde «¿qué tenemos hasta ahora?» sin que el Director improvise: qué hay sobre la mesa
(universo, vistas, estimaciones, carteras, diagnósticos, restricciones), qué especialista lo
puso y si sigue vigente. La obsolescencia es POR ELEMENTO: cada ``ItemPizarra`` lleva su propio
sello y la mesa exige que ``obsoleto`` diga exactamente lo que dirían las herramientas
(``sello != universe_version`` de la mesa, la misma regla de ADR-012). Una mesa que llame
vigente a algo que una herramienta rechazaría no valida.

``Silla`` es el roster («¿quién está en la sala?»): un especialista y las herramientas que de
verdad atiende en el equipo que está corriendo.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from investmentsys.contracts.common import ContractBase, Ticker, validar_activos_unicos
from investmentsys.contracts.universe import UniverseVersion


class Especialista(StrEnum):
    """Las sillas de la sala. El valor es el nombre con el que se le atribuye ante el usuario."""

    DIRECTOR = "Director"
    GESTOR_DATOS = "Gestor de Datos"
    ANALISTA = "Analista de Mercado"
    ESTADISTICO = "Estadístico"
    CONSTRUCTOR = "Constructor de Carteras"
    ESCEPTICO = "Escéptico"
    COMITE = "Comité formal"


class CategoriaPizarra(StrEnum):
    UNIVERSO = "Universo"
    VISTAS = "Vistas"
    ESTIMACION = "Estimación"
    CARTERAS = "Carteras"
    DIAGNOSTICO = "Diagnóstico"
    RESTRICCION = "Restricción"


class ItemPizarra(ContractBase):
    categoria: CategoriaPizarra
    contenido: str = Field(min_length=1, description="Descripción legible; la redacta el código.")
    origen: Especialista = Field(description="Especialista que puso el elemento en la mesa.")
    universe_version: UniverseVersion | None = Field(
        default=None,
        description=(
            "Sello del Universe sobre el que se produjo el elemento. None solo para lo que no "
            "se sella por versión (las vistas se atan a la lista de activos, no a las caps)."
        ),
    )
    obsoleto: bool = Field(
        default=False, description="True si un cambio de universo lo dejó sin valor."
    )
    que_hacer: str | None = Field(
        default=None, description="Cómo rehacerlo; obligatorio si está obsoleto, y solo entonces."
    )

    @model_validator(mode="after")
    def _obsoleto_dice_que_hacer(self) -> ItemPizarra:
        if self.obsoleto != (self.que_hacer is not None):
            raise ValueError("que_hacer acompaña a un elemento obsoleto, y solo a uno obsoleto")
        return self

    @classmethod
    def sellado(
        cls,
        categoria: CategoriaPizarra,
        contenido: str,
        origen: Especialista,
        sello: str | None,
        vigente: str,
        que_hacer: str,
    ) -> ItemPizarra:
        """Un elemento con sello propio: queda obsoleto si no es el del universo ``vigente``.

        Sin sello también es obsoleto: es la regla de ``exigir_sello`` (ADR-012).
        """
        obsoleto = sello != vigente
        return cls(
            categoria=categoria,
            contenido=contenido,
            origen=origen,
            universe_version=sello,
            obsoleto=obsoleto,
            que_hacer=que_hacer if obsoleto else None,
        )

    @property
    def estado(self) -> str:
        return "Obsoleto" if self.obsoleto else "Vigente"


class MesaDeTrabajoState(ContractBase):
    universe_version: UniverseVersion = Field(description="Sello del universo vigente.")
    activos: tuple[Ticker, ...] = Field(min_length=1)
    items: tuple[ItemPizarra, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherencia(self) -> MesaDeTrabajoState:
        validar_activos_unicos(self.activos)
        universos = [i for i in self.items if i.categoria is CategoriaPizarra.UNIVERSO]
        if len(universos) != 1 or universos[0].universe_version != self.universe_version:
            raise ValueError("la mesa tiene exactamente un Universo: el vigente, con su sello")
        for i, item in enumerate(self.items):
            if item.universe_version is None:
                continue
            if item.obsoleto != (item.universe_version != self.universe_version):
                raise ValueError(
                    f"items[{i}] ({item.categoria.value}): 'obsoleto' contradice a su sello "
                    f"({item.universe_version[:12]}… frente al vigente "
                    f"{self.universe_version[:12]}…)"
                )
        return self

    @property
    def obsoletos(self) -> tuple[ItemPizarra, ...]:
        return tuple(i for i in self.items if i.obsoleto)


class Silla(ContractBase):
    """Una silla del roster: quién es, cómo participa y qué herramientas atiende de verdad."""

    especialista: Especialista
    conversa: bool = Field(
        description="True: sub-agente con voz propia (LLM). False: herramientas deterministas."
    )
    herramientas: tuple[str, ...] = Field(min_length=1)
