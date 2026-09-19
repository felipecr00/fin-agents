"""Contratos de S8 (ADR-014): la aprobación del comité y el diagnóstico exploratorio."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    AprobacionComite,
    CandidatePortfolio,
    DiagnosticoCartera,
    EstadoPrior,
    PriorProvenance,
    ResumenComite,
    RunState,
    ValidationReport,
)
from tests.almacen import sellar, sesion_de, universo_de, universo_referencia

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _resumen(**cambios: Any) -> ResumenComite:
    u = universo_referencia()
    base: dict[str, Any] = {
        "universe_version": u.version,
        "activos": u.activos,
        "inicio_datos": {d.ticker: d.fecha_inicio_datos for d in u.diagnosticos},
        "estado_prior": EstadoPrior.CAPITALIZACION,
        "procedencias_prior": dict.fromkeys(u.activos, PriorProvenance.USUARIO),
        "restricciones": sesion_de(u),
    }
    return ResumenComite.model_validate({**base, **cambios})


def _aprobacion(**cambios: Any) -> AprobacionComite:
    base: dict[str, Any] = {
        "resumen": _resumen(),
        "solicitado_en": T0,
        "confirmado_en": T0 + timedelta(minutes=2),
        "invocacion_solicitud": "inv-1",
        "invocacion_confirmacion": "inv-2",
    }
    return AprobacionComite.model_validate({**base, **cambios})


class TestResumenComite:
    def test_no_hay_resumen_con_el_prior_pendiente(self) -> None:
        with pytest.raises(ValidationError, match="prior pendiente"):
            _resumen(estado_prior=EstadoPrior.PENDIENTE)

    def test_neutral_es_todo_o_nada(self) -> None:
        u = universo_referencia()
        mezcla = {**dict.fromkeys(u.activos, PriorProvenance.USUARIO), "IBIT": "neutral"}
        with pytest.raises(ValidationError, match="todo-o-nada"):
            _resumen(procedencias_prior=mezcla)

    def test_restricciones_de_otro_universo(self) -> None:
        with pytest.raises(ValidationError):
            _resumen(restricciones=sesion_de(universo_de(("AAA", "BBB"))))


class TestAprobacionComite:
    def test_confirmar_en_el_turno_de_la_solicitud_no_es_una_aprobacion(self) -> None:
        with pytest.raises(ValidationError, match="mismo turno"):
            _aprobacion(invocacion_confirmacion="inv-1")

    def test_la_confirmacion_no_precede_a_la_solicitud(self) -> None:
        with pytest.raises(ValidationError, match="anterior"):
            _aprobacion(confirmado_en=T0 - timedelta(seconds=1))


class TestRunStateConAprobacion:
    def test_el_acta_admite_la_aprobacion_y_sobrevive_al_round_trip(
        self, run_state_inicial: RunState
    ) -> None:
        acta = run_state_inicial.avanzar(aprobacion=_aprobacion())
        assert RunState.model_validate_json(acta.model_dump_json()) == acta

    def test_sin_aprobacion_sigue_siendo_valida(self, run_state_inicial: RunState) -> None:
        """Modo comando (apps/pipeline, scripts) y actas de S7: ``aprobacion`` es None."""
        assert run_state_inicial.aprobacion is None

    def test_aprobacion_de_otro_universo_no_entra_al_acta(
        self, run_state_inicial: RunState
    ) -> None:
        otro = universo_de(universo_referencia().activos)
        ajena = _aprobacion(
            resumen=_resumen(universe_version=otro.version, restricciones=sesion_de(otro))
        )
        with pytest.raises(ValidationError, match="aprobó el universo"):
            run_state_inicial.avanzar(aprobacion=ajena)


class TestDiagnosticoCartera:
    @pytest.fixture
    def diagnostico(
        self, validacion_aprobada: ValidationReport, candidato_bl: CandidatePortfolio
    ) -> DiagnosticoCartera:
        sellado = sellar(validacion_aprobada, universo_referencia())
        return DiagnosticoCartera.desde_reporte(sellado, candidato_bl.metricas)

    def test_nace_etiquetado_no_validado_y_sin_veredicto(
        self, diagnostico: DiagnosticoCartera
    ) -> None:
        volcado = diagnostico.model_dump(mode="json")
        assert volcado["etiqueta"] == "diagnostico" and volcado["validado"] is False
        assert "veredicto" not in volcado and "sugerencias" not in volcado

    def test_validado_nunca_puede_ser_true(self, diagnostico: DiagnosticoCartera) -> None:
        with pytest.raises(ValidationError):
            DiagnosticoCartera.model_validate({**diagnostico.model_dump(), "validado": True})

    def test_sin_sello_no_hay_diagnostico(
        self, validacion_aprobada: ValidationReport, candidato_bl: CandidatePortfolio
    ) -> None:
        sin_sello = validacion_aprobada.model_copy(update={"universe_version": None})
        with pytest.raises(ValueError, match="sin sellar"):
            DiagnosticoCartera.desde_reporte(sin_sello, candidato_bl.metricas)

    def test_un_acta_no_lo_admite_como_validacion(
        self, run_state_inicial: RunState, diagnostico: DiagnosticoCartera
    ) -> None:
        with pytest.raises(ValidationError):
            run_state_inicial.avanzar(validaciones=(diagnostico.model_dump(),))
