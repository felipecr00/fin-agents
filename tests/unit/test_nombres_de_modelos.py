"""Enmienda v2 §4 (ADR-018): ningún nombre comercial de modelo fuera de ``config.yaml``.

La lista de marcas vetadas vive en ``config.yaml: inferencia.nombres_vetados`` —el único archivo
que puede nombrarlas—, así que este test tampoco las escribe. Se revisa todo lo versionado o por
versionar (``git ls-files``), sin los binarios, el lock de dependencias ni las corridas.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from investmentsys.config import RAIZ_PROYECTO, cargar_config

EXCLUIDOS = ("config.yaml", "uv.lock")
PREFIJOS_EXCLUIDOS = ("runs/",)


def _archivos() -> list[Path]:
    salida = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=RAIZ_PROYECTO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [
        RAIZ_PROYECTO / a
        for a in salida
        if a not in EXCLUIDOS and not a.startswith(PREFIJOS_EXCLUIDOS) and "/.adk/" not in a
    ]


def menciones() -> list[str]:
    inferencia = cargar_config().inferencia
    patron = re.compile(
        r"\b(" + "|".join(map(re.escape, inferencia.nombres_vetados)) + r")\b", re.IGNORECASE
    )
    # Solo se excusan, literales, los nombres que impone el tooling (declarados en config.yaml).
    tooling = re.compile("|".join(map(re.escape, inferencia.excepciones_de_tooling)) or r"(?!)")
    halladas = []
    for ruta in _archivos():
        relativa = ruta.relative_to(RAIZ_PROYECTO)
        if patron.search(tooling.sub("", str(relativa))):
            halladas.append(f"{relativa}: en el nombre del archivo")
        try:
            texto = ruta.read_text("utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for n, linea in enumerate(texto.splitlines(), start=1):
            if patron.search(tooling.sub("", linea)):
                halladas.append(f"{relativa}:{n}: {linea.strip()[:120]}")
    return halladas


def test_ningun_nombre_de_modelo_fuera_de_config_yaml() -> None:
    assert menciones() == []


def test_el_vigilante_ve_lo_que_debe_ver() -> None:
    """Las marcas vetadas incluyen la familia del modelo asignado: el test no es decorativo."""
    config = cargar_config()
    familia = re.split(r"[-_. ]", config.inferencia.nivel_1.modelo)[0].lower()
    assert familia in config.inferencia.nombres_vetados


if __name__ == "__main__":  # `make nombres`: el grep del DoD, legible
    print("\n".join(menciones()) or "sin nombres de modelos fuera de config.yaml")
