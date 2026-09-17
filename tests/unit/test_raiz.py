"""ADR-008: la raíz del proyecto es el primer ancestro con config.yaml (repo y contenedores)."""

from __future__ import annotations

from pathlib import Path

import pytest

from investmentsys.config import NOMBRE_CONFIG, RAIZ_PROYECTO, _localizar_raiz


@pytest.mark.parametrize(
    "paquete",
    ["src/investmentsys", "investmentsys"],  # repo y Cloud Run; Agent Engine (/app/investmentsys)
)
def test_localiza_la_raiz_en_ambos_layouts(tmp_path: Path, paquete: str) -> None:
    (tmp_path / NOMBRE_CONFIG).write_text("{}", encoding="utf-8")
    modulo = tmp_path / paquete / "config.py"
    modulo.parent.mkdir(parents=True)
    modulo.touch()
    assert _localizar_raiz(modulo) == tmp_path.resolve()


def test_sin_config_falla_con_mensaje_claro(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=NOMBRE_CONFIG):
        _localizar_raiz(tmp_path / "investmentsys" / "config.py")


def test_la_raiz_del_repo_no_cambia() -> None:
    assert (RAIZ_PROYECTO / "pyproject.toml").is_file()
