"""Contratos de S9 (ADR-016): la mesa no puede contradecir a los sellos de sus elementos."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    CategoriaPizarra,
    Especialista,
    ItemPizarra,
    MesaDeTrabajoState,
    Silla,
)

VIGENTE = "a" * 64
ANTERIOR = "b" * 64
ACTIVOS = ("VOOG", "BNS")


def _universo(sello: str = VIGENTE) -> ItemPizarra:
    return ItemPizarra(
        categoria=CategoriaPizarra.UNIVERSO,
        contenido="VOOG, BNS",
        origen=Especialista.GESTOR_DATOS,
        universe_version=sello,
    )


def _estimacion(sello: str | None, vigente: str = VIGENTE) -> ItemPizarra:
    return ItemPizarra.sellado(
        CategoriaPizarra.ESTIMACION,
        "covarianza ledoit_wolf",
        Especialista.ESTADISTICO,
        sello,
        vigente,
        "vuelve a llamar a estimar_mercado",
    )


def _mesa(*items: ItemPizarra, **cambios: Any) -> MesaDeTrabajoState:
    base: dict[str, Any] = {"universe_version": VIGENTE, "activos": ACTIVOS, "items": items}
    return MesaDeTrabajoState.model_validate({**base, **cambios})


class TestItemPizarra:
    def test_sellado_con_el_universo_vigente_esta_vigente(self) -> None:
        item = _estimacion(VIGENTE)
        assert not item.obsoleto and item.que_hacer is None and item.estado == "Vigente"

    @pytest.mark.parametrize("sello", [ANTERIOR, None])
    def test_otro_sello_o_ninguno_es_obsoleto_y_dice_que_hacer(self, sello: str | None) -> None:
        item = _estimacion(sello)
        assert item.obsoleto and item.estado == "Obsoleto"
        assert item.que_hacer == "vuelve a llamar a estimar_mercado"

    @pytest.mark.parametrize(
        "cambios", [{"obsoleto": True}, {"obsoleto": False, "que_hacer": "rehacer"}]
    )
    def test_que_hacer_acompana_a_lo_obsoleto_y_solo_a_lo_obsoleto(
        self, cambios: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError, match="que_hacer"):
            ItemPizarra.model_validate({**_universo().model_dump(), **cambios})

    def test_categoria_y_origen_son_cerrados(self) -> None:
        with pytest.raises(ValidationError):
            ItemPizarra.model_validate({**_universo().model_dump(), "origen": "Un tal Pedro"})
        with pytest.raises(ValidationError):
            ItemPizarra.model_validate({**_universo().model_dump(), "categoria": "Chismes"})

    def test_es_inmutable(self) -> None:
        with pytest.raises(ValidationError):
            _universo().obsoleto = True  # type: ignore[misc]


class TestMesaDeTrabajoState:
    def test_granularidad_por_elemento_vigentes_y_obsoletos_conviven(self) -> None:
        mesa = _mesa(_universo(), _estimacion(ANTERIOR), _estimacion(VIGENTE))
        assert [i.obsoleto for i in mesa.items] == [False, True, False]
        assert mesa.obsoletos == (mesa.items[1],)

    def test_llamar_vigente_a_lo_sellado_con_otro_universo_no_valida(self) -> None:
        mentira = _estimacion(ANTERIOR, vigente=ANTERIOR)  # "vigente" respecto de OTRO universo
        assert not mentira.obsoleto
        with pytest.raises(ValidationError, match="contradice a su sello"):
            _mesa(_universo(), mentira)

    def test_llamar_obsoleto_a_lo_sellado_con_el_vigente_tampoco(self) -> None:
        with pytest.raises(ValidationError, match="contradice a su sello"):
            _mesa(_universo(), _estimacion(VIGENTE, vigente=ANTERIOR))

    def test_sin_sello_propio_la_vigencia_la_decide_quien_arma_la_mesa(self) -> None:
        """Las vistas se atan a la lista de activos, no a la versión (una cap no las toca)."""
        vistas = ItemPizarra(
            categoria=CategoriaPizarra.VISTAS, contenido="1 view", origen=Especialista.ANALISTA
        )
        assert _mesa(_universo(), vistas).obsoletos == ()

    @pytest.mark.parametrize(
        "items",
        [
            (_estimacion(VIGENTE),),  # sin universo
            (_universo(), _universo()),  # dos
            (_universo(ANTERIOR),),  # el universo de la mesa no es el vigente
        ],
    )
    def test_exactamente_un_universo_y_es_el_vigente(self, items: tuple[ItemPizarra, ...]) -> None:
        with pytest.raises(ValidationError, match="exactamente un Universo"):
            _mesa(*items)

    def test_sello_mal_formado_y_activos_repetidos(self) -> None:
        with pytest.raises(ValidationError):
            _mesa(_universo(), universe_version="uv_8f29d")
        with pytest.raises(ValidationError, match="duplicados"):
            _mesa(_universo(), activos=("VOOG", "VOOG"))

    def test_ida_y_vuelta_por_json(self) -> None:
        mesa = _mesa(_universo(), _estimacion(ANTERIOR))
        assert MesaDeTrabajoState.model_validate(mesa.model_dump(mode="json")) == mesa


def test_una_silla_atiende_al_menos_una_herramienta() -> None:
    with pytest.raises(ValidationError):
        Silla(especialista=Especialista.ESCEPTICO, conversa=False, herramientas=())
