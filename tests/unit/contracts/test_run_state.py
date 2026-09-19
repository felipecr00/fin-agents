from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    DISCLAIMER,
    CandidatePortfolios,
    EtapaCorrida,
    MarketViews,
    PortfolioConstraints,
    QuantEstimates,
    RunState,
    ValidationReport,
    Veredicto,
)


def test_estado_inicial(run_state_inicial: RunState) -> None:
    s = run_state_inicial
    assert s.etapa is EtapaCorrida.INICIADA
    assert not s.aprobado and s.portafolio_final is None and s.ultima_validacion is None
    assert s.disclaimer == DISCLAIMER


def test_ciclo_completo_y_round_trip(
    run_state_inicial: RunState,
    restricciones: PortfolioConstraints,
    views_golden: MarketViews,
    estimates: QuantEstimates,
    candidatos: CandidatePortfolios,
    validacion_aprobada: ValidationReport,
) -> None:
    s = run_state_inicial.avanzar(
        etapa=EtapaCorrida.ANALISIS_Y_ESTIMACION,
        restricciones=restricciones,
        market_views=views_golden,
        quant_estimates=estimates,
    )
    s = s.avanzar(etapa=EtapaCorrida.CONSTRUCCION, candidatos=(candidatos,))
    s = s.avanzar(etapa=EtapaCorrida.VALIDACION, validaciones=(validacion_aprobada,))
    assert s.aprobado and s.portafolio_final is not None
    assert s.portafolio_final.nombre == "bl_base"
    s = s.avanzar(etapa=EtapaCorrida.COMPLETADA, reporte_markdown=f"# Reporte\n\n{DISCLAIMER}")
    assert RunState.model_validate_json(s.model_dump_json()) == s
    assert run_state_inicial.etapa is EtapaCorrida.INICIADA  # el original no cambió


def test_completada_exige_aprobacion(run_state_inicial: RunState) -> None:
    with pytest.raises(ValidationError, match="APROBADA"):
        run_state_inicial.avanzar(
            etapa=EtapaCorrida.COMPLETADA, reporte_markdown=f"reporte {DISCLAIMER}"
        )


def test_completada_exige_disclaimer(
    run_state_inicial: RunState,
    candidatos: CandidatePortfolios,
    validacion_aprobada: ValidationReport,
) -> None:
    s = run_state_inicial.avanzar(candidatos=(candidatos,), validaciones=(validacion_aprobada,))
    with pytest.raises(ValidationError, match="disclaimer"):
        s.avanzar(etapa=EtapaCorrida.COMPLETADA, reporte_markdown="reporte sin advertencia")


def test_disclaimer_no_se_modifica(run_state_inicial: RunState) -> None:
    with pytest.raises(ValidationError, match="disclaimer"):
        run_state_inicial.avanzar(disclaimer="sin advertencia")


def test_fallida_exige_errores(run_state_inicial: RunState) -> None:
    with pytest.raises(ValidationError, match="FALLIDA"):
        run_state_inicial.avanzar(etapa=EtapaCorrida.FALLIDA)
    s = run_state_inicial.avanzar(etapa=EtapaCorrida.FALLIDA, errores=("timeout del analista",))
    assert s.errores == ("timeout del analista",)


def test_mas_validaciones_que_candidatos(
    run_state_inicial: RunState, validacion_aprobada: ValidationReport
) -> None:
    with pytest.raises(ValidationError, match="más validaciones"):
        run_state_inicial.avanzar(validaciones=(validacion_aprobada,))


def test_validacion_de_candidato_distinto_al_recomendado(
    run_state_inicial: RunState,
    candidatos: CandidatePortfolios,
    validacion_aprobada: ValidationReport,
) -> None:
    otra = ValidationReport(**{**validacion_aprobada.model_dump(), "candidato_evaluado": "x"})
    with pytest.raises(ValidationError, match="distinto al recomendado"):
        run_state_inicial.avanzar(candidatos=(candidatos,), validaciones=(otra,))


def test_subcontrato_con_otra_fecha_de_decision(
    run_state_inicial: RunState, views_golden: MarketViews
) -> None:
    otras = MarketViews(**{**views_golden.model_dump(), "fecha_decision": date(2026, 8, 31)})
    with pytest.raises(ValidationError, match="fecha de decisión distinta"):
        run_state_inicial.avanzar(market_views=otras)


def test_subcontrato_con_otro_universo(
    run_state_inicial: RunState, activos: tuple[str, ...]
) -> None:
    otras = PortfolioConstraints(activos=(*activos, "AAPL"), peso_min=0.0, peso_max=1.0)
    with pytest.raises(ValidationError, match="universo distinto"):
        run_state_inicial.avanzar(restricciones=otras)


def test_rechazo_luego_aprobacion(
    run_state_inicial: RunState,
    candidatos: CandidatePortfolios,
    validacion_aprobada: ValidationReport,
) -> None:
    from investmentsys.contracts import Criterio

    rechazo = ValidationReport(
        **{
            **validacion_aprobada.model_dump(),
            "criterios": (
                Criterio(nombre="sharpe_oos_minimo", valor=0.1, umbral=0.2, cumple=False),
            ),
            "veredicto": Veredicto.RECHAZADA,
        }
    )
    ronda2 = CandidatePortfolios(**{**candidatos.model_dump(), "iteracion": 2})
    ok2 = ValidationReport(**{**validacion_aprobada.model_dump(), "iteracion": 2})
    s = run_state_inicial.avanzar(candidatos=(candidatos, ronda2), validaciones=(rechazo,))
    assert not s.aprobado
    s = s.avanzar(validaciones=(rechazo, ok2))
    assert s.aprobado and s.portafolio_final is not None


# ------------------------------------------------ S7: sellado por universe_version (ADR-012)
def test_ningun_resultado_sin_sellar_llega_a_un_acta(
    run_state_inicial: RunState,
    estimates: QuantEstimates,
    candidatos: CandidatePortfolios,
    validacion_aprobada: ValidationReport,
) -> None:
    """El ``None`` del núcleo puro (golden, sensibilidad) tiene su cerco: RunState lo rechaza."""
    sin_sello = {"universe_version": None}
    with pytest.raises(ValidationError, match="quant_estimates: sin sellar"):
        run_state_inicial.avanzar(quant_estimates=estimates.model_copy(update=sin_sello))
    with pytest.raises(ValidationError, match=r"candidatos\[0\]: sin sellar"):
        run_state_inicial.avanzar(candidatos=(candidatos.model_copy(update=sin_sello),))
    with pytest.raises(ValidationError, match=r"validaciones\[0\]: sin sellar"):
        run_state_inicial.avanzar(
            candidatos=(candidatos,),
            validaciones=(validacion_aprobada.model_copy(update=sin_sello),),
        )


def test_resultado_sellado_con_otro_universo_se_rechaza(
    run_state_inicial: RunState, estimates: QuantEstimates
) -> None:
    viejo = estimates.model_copy(update={"universe_version": "f" * 64})
    with pytest.raises(ValidationError, match="quant_estimates: obsoleto"):
        run_state_inicial.avanzar(quant_estimates=viejo)


def test_universo_y_restricciones_de_sesion_son_obligatorios(run_state_inicial: RunState) -> None:
    crudo = run_state_inicial.model_dump()
    for campo in ("universo", "restricciones_sesion"):
        with pytest.raises(ValidationError, match=campo):
            RunState.model_validate({k: v for k, v in crudo.items() if k != campo})


def test_un_candidato_bl_exige_el_prior_en_el_acta(
    run_state_inicial: RunState, candidatos: CandidatePortfolios
) -> None:
    with pytest.raises(ValidationError, match="no registra el prior"):
        run_state_inicial.avanzar(prior=None, candidatos=(candidatos,))
