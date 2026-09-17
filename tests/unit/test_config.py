from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from investmentsys.config import RUTA_CONFIG, Config, MetodoOmega, cargar_config, hash_config
from investmentsys.contracts import MetodoCovarianza


def test_carga_el_config_del_repo() -> None:
    cfg = cargar_config()
    assert cfg.portafolio.activos == ("VOOG", "BNS", "IBIT", "VB")
    assert cfg.optimizacion.metodo_covarianza is MetodoCovarianza.HISTORICA
    assert cfg.optimizacion.metodo_omega is MetodoOmega.HE_LITTERMAN
    assert cfg.datos.ruta_csv == Path("data/precios.csv")
    assert cfg.reproducibilidad.semilla == 42
    assert 0.0 < cfg.estimacion.nivel_confianza < 1.0
    assert set(cfg.prior_equilibrio.capitalizacion_usd_billones) == set(cfg.portafolio.activos)


def test_hash_es_estable_y_hexadecimal() -> None:
    h = hash_config()
    assert len(h) == 64 and int(h, 16) >= 0
    assert h == hash_config(RUTA_CONFIG)


def test_rechaza_claves_desconocidas() -> None:
    crudo = cargar_config().model_dump()
    crudo["optimizacion"]["gamma"] = 1.0
    with pytest.raises(ValidationError):
        Config.model_validate(crudo)


def test_rechaza_prior_con_otro_universo() -> None:
    crudo = cargar_config().model_dump()
    crudo["prior_equilibrio"]["capitalizacion_usd_billones"].pop("VB")
    with pytest.raises(ValidationError, match="no coincide con el universo"):
        Config.model_validate(crudo)


def test_rechaza_pesos_actuales_que_no_suman_uno() -> None:
    crudo = cargar_config().model_dump()
    crudo["portafolio"]["pesos_actuales"]["VOOG"] = 0.5
    with pytest.raises(ValidationError, match="suman"):
        Config.model_validate(crudo)


def test_escenarios_stress_del_repo() -> None:
    escenarios = cargar_config().validacion.escenarios_stress
    assert [e.nombre for e in escenarios] == ["tasas_2022", "cripto_2025_26"]
    assert all(e.desde <= e.hasta for e in escenarios)
    assert 0.0 < cargar_config().validacion.concentracion_hhi_maxima <= 1.0


def test_rechaza_escenarios_repetidos_o_invertidos() -> None:
    crudo = cargar_config().model_dump()
    escenarios = list(crudo["validacion"]["escenarios_stress"])
    crudo["validacion"]["escenarios_stress"] = [*escenarios, dict(escenarios[0])]
    with pytest.raises(ValidationError, match="repetidos"):
        Config.model_validate(crudo)
    crudo = cargar_config().model_dump()
    primero = dict(escenarios[0])
    primero["hasta"] = primero["desde"].replace(year=2020)
    crudo["validacion"]["escenarios_stress"] = [primero, *escenarios[1:]]
    with pytest.raises(ValidationError, match="posterior a 'hasta'"):
        Config.model_validate(crudo)


def test_agentes_modelo_fijo_y_sin_alias_latest() -> None:
    cfg = cargar_config()
    assert cfg.agentes.modelo == "gemini-3.5-flash"
    assert cfg.agentes.max_intentos_analista >= 1
    crudo = cfg.agentes.model_dump() | {"modelo": "gemini-flash-latest"}
    with pytest.raises(ValidationError, match="-latest"):
        type(cfg.agentes).model_validate(crudo)
