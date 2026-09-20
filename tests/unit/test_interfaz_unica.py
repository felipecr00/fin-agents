"""S11 — unificación: ``apps/equipo`` es la ÚNICA interfaz; el modo comando es un target de make
y de despliegue, no algo que ``adk web`` sirva."""

from __future__ import annotations

from investmentsys.config import RAIZ_PROYECTO

MAKEFILE = (RAIZ_PROYECTO / "Makefile").read_text(encoding="utf-8")
DOCKERFILE = (RAIZ_PROYECTO / "Dockerfile").read_text(encoding="utf-8")


def _apps(carpeta: str) -> list[str]:
    return sorted(p.parent.name for p in (RAIZ_PROYECTO / carpeta).glob("*/agent.py"))


def test_adk_web_solo_sirve_al_equipo() -> None:
    assert _apps("apps") == ["equipo"]
    assert "adk web apps" in MAKEFILE


def test_el_modo_comando_sobrevive_como_target_de_make_y_de_despliegue() -> None:
    assert _apps("comando") == ["pipeline"]
    assert (RAIZ_PROYECTO / "comando/pipeline/.agent_engine_config.json").is_file()
    assert "\ncomando:" in MAKEFILE and "scripts/run_pipeline.py" in MAKEFILE
    assert "APP ?= pipeline" in MAKEFILE and "$(DIR_APP)/$(APP)/agent.py" in MAKEFILE
    # dev lo sirve como API junto al equipo (corrida-dev y replay), sin UI: api_server.
    assert "COPY comando/pipeline ./servidos/pipeline" in DOCKERFILE
    assert "adk api_server" in DOCKERFILE and "adk web" not in DOCKERFILE


def test_el_agente_del_eval_no_es_una_interfaz() -> None:
    assert _apps("tests/eval/agentes") == ["market_analyst"]
    assert "AGENTE_EVAL := tests/eval/agentes/market_analyst" in MAKEFILE
