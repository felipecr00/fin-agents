"""``bitacora.emitir``: cada hito, al estado Y a una línea de ``bitacora.jsonl`` (S11)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from investmentsys.contracts import EventoComite, FaseComite, HitoComite
from investmentsys.orchestrator.bitacora import (
    ARCHIVO_BITACORA,
    CLAVE_HITOS,
    TITULO_CRONOLOGIA,
    emitir,
    leer_bitacora,
    leer_hitos,
    renderizar_cronologia,
)

T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _reloj(paso_s: int = 65):
    marcas = iter(T0 + timedelta(seconds=paso_s * i) for i in range(100))
    return lambda: next(marcas)


def _tres_hitos(estado: dict[str, Any], carpeta: Path | None) -> list[HitoComite]:
    reloj = _reloj()
    return [
        emitir(estado, carpeta, reloj, FaseComite.COMITE, 0, EventoComite.SESION_ABIERTA, "abre."),
        emitir(
            estado,
            carpeta,
            reloj,
            FaseComite.VALIDADOR,
            1,
            EventoComite.VETO,
            "VETO emitido. Motivo: HHI 0.62 > 0.55",
        ),
        emitir(
            estado, carpeta, reloj, FaseComite.REPORTER, 0, EventoComite.ACTA_CONSOLIDADA, "acta."
        ),
    ]


def test_cada_hito_va_al_estado_y_a_una_linea_de_la_bitacora(tmp_path: Path) -> None:
    estado: dict[str, Any] = {}
    carpeta = tmp_path / "20261005T120000_000000Z"
    hitos = _tres_hitos(estado, carpeta)

    assert list(leer_hitos(estado)) == hitos
    lineas = (carpeta / ARCHIVO_BITACORA).read_text("utf-8").splitlines()
    assert len(lineas) == 3 and all(json.loads(linea)["timestamp"] for linea in lineas)
    assert list(leer_bitacora(carpeta / ARCHIVO_BITACORA)) == hitos
    assert json.loads(lineas[1]) == {
        "timestamp": "2026-10-05T12:01:05Z",
        "fase": "Escéptico (Validador)",
        "iteracion": 1,
        "evento": "veto",
        "detalle": "VETO emitido. Motivo: HHI 0.62 > 0.55",
    }


def test_la_bitacora_se_puede_leer_despues_de_cada_hito(tmp_path: Path) -> None:
    """Legible EN PARALELO: no se escribe al final, cada ``emitir`` deja su línea completa."""
    estado: dict[str, Any] = {}
    reloj = _reloj()
    for n in range(1, 4):
        emitir(estado, tmp_path, reloj, FaseComite.CONSTRUCTOR, n, EventoComite.PROPUESTA, f"p{n}")
        assert len(leer_bitacora(tmp_path / ARCHIVO_BITACORA)) == n


def test_sin_disco_los_hitos_siguen_en_el_estado(tmp_path: Path) -> None:
    ocupado = tmp_path / "no_es_carpeta"
    ocupado.write_text("x", encoding="utf-8")  # mkdir fallará: equivale a un disco no escribible
    estado: dict[str, Any] = {}
    assert len(_tres_hitos(estado, ocupado)) == 3
    assert len(estado[CLAVE_HITOS]) == 3
    assert len(_tres_hitos({}, None)) == 3


def test_la_cronologia_narra_fases_rondas_vetos_con_motivo_y_tiempos() -> None:
    estado: dict[str, Any] = {}
    _tres_hitos(estado, None)
    texto = renderizar_cronologia(leer_hitos(estado))
    assert texto.splitlines()[0] == TITULO_CRONOLOGIA
    assert "1 ronda Constructor ⇄ Escéptico, 1 veto, duración total 02:10 (mm:ss)." in texto
    assert "2. `+01:05` **Escéptico (Validador)** · ronda 1: VETO emitido. Motivo: HHI" in texto
    assert "3. `+02:10` **Reporter**: acta." in texto
    assert renderizar_cronologia(()) == ""
