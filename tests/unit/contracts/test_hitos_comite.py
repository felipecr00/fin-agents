"""``HitoComite`` y ``CronologiaComite`` (S11): lo que la bitácora se compromete a contar."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from investmentsys.contracts import CronologiaComite, EventoComite, FaseComite, HitoComite

T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _hito(
    segundos: int = 0,
    fase: FaseComite = FaseComite.CONSTRUCTOR,
    iteracion: int = 1,
    evento: EventoComite = EventoComite.PROPUESTA,
    detalle: str = "propuesta 1 generada.",
) -> HitoComite:
    return HitoComite(
        timestamp=T0 + timedelta(seconds=segundos),
        fase=fase,
        iteracion=iteracion,
        evento=evento,
        detalle=detalle,
    )


def _veto(segundos: int, iteracion: int = 1) -> HitoComite:
    return _hito(
        segundos,
        FaseComite.VALIDADOR,
        iteracion,
        EventoComite.VETO,
        "VETO emitido. Motivo: concentracion_hhi_maxima",
    )


class TestHito:
    def test_la_linea_nombra_fase_y_ronda(self) -> None:
        assert _veto(0).linea() == (
            "Escéptico (Validador) · ronda 1: VETO emitido. Motivo: concentracion_hhi_maxima"
        )
        apertura = _hito(0, FaseComite.COMITE, 0, EventoComite.SESION_ABIERTA, "sesión abierta.")
        assert apertura.linea() == "Comité: sesión abierta."

    def test_un_timestamp_sin_zona_se_rechaza(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            HitoComite(
                timestamp=datetime(2026, 10, 5, 12, 0, 0),
                fase=FaseComite.COMITE,
                iteracion=0,
                evento=EventoComite.SESION_ABIERTA,
                detalle="sesión abierta.",
            )

    def test_un_veto_sin_motivo_se_rechaza(self) -> None:
        with pytest.raises(ValidationError, match="motivo"):
            _hito(0, FaseComite.VALIDADOR, 1, EventoComite.VETO, "VETO emitido.")

    @pytest.mark.parametrize(
        "cambio", [{"fase": "Tesorero"}, {"evento": "milagro"}, {"iteracion": -1}, {"detalle": ""}]
    )
    def test_fase_evento_iteracion_y_detalle_estan_acotados(
        self, cambio: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            HitoComite.model_validate({**_hito().model_dump(), **cambio})

    def test_sobrevive_al_viaje_por_json(self) -> None:
        hito = _veto(3)
        assert HitoComite.model_validate_json(hito.model_dump_json()) == hito


class TestCronologia:
    def test_resume_rondas_vetos_y_tiempos(self) -> None:
        cronologia = CronologiaComite(
            hitos=(
                _hito(0, FaseComite.COMITE, 0, EventoComite.SESION_ABIERTA, "sesión abierta."),
                _hito(10),
                _veto(12),
                _hito(40, iteracion=2),
                _hito(42, FaseComite.VALIDADOR, 2, EventoComite.APROBADA, "APROBADA."),
                _hito(50, FaseComite.REPORTER, 0, EventoComite.ACTA_CONSOLIDADA, "acta."),
            )
        )
        assert cronologia.iteraciones == 2 and len(cronologia.vetos) == 1
        assert cronologia.duracion == timedelta(seconds=50)
        assert cronologia.transcurrido(cronologia.hitos[2]) == timedelta(seconds=12)

    def test_hitos_fuera_de_orden_se_rechazan(self) -> None:
        with pytest.raises(ValidationError, match="fuera de orden"):
            CronologiaComite(hitos=(_hito(10), _hito(5)))

    def test_las_rondas_no_retroceden(self) -> None:
        with pytest.raises(ValidationError, match="no retroceden"):
            CronologiaComite(hitos=(_hito(0, iteracion=2), _hito(1, iteracion=1)))

    def test_una_cronologia_vacia_no_existe(self) -> None:
        with pytest.raises(ValidationError):
            CronologiaComite(hitos=())
