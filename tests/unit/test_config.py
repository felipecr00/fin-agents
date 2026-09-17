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
