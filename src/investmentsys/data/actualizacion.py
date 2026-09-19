"""Actualización validada del CSV de precios (``make update-prices``, ADR-011).

Tres barreras antes de tocar el CSV vigente, en este orden:

1. **Sanidad** del panel nuevo: meses únicos y contiguos, inicio en la fecha configurada (salvo
   los activos de inicio tardío declarados), precios > 0, ningún retorno mensual absurdo.
2. **Continuidad** contra el CSV vigente: en la ventana solapada los retornos mensuales deben
   coincidir dentro de la tolerancia, y no puede perderse historia. Una discrepancia es un
   ajuste retroactivo o un error de fuente: decide un humano, no este módulo.
3. **Escritura atómica**: archivo temporal en la misma carpeta, releído con
   ``CSVPriceProvider`` (las reglas del consumidor), copia de respaldo del vigente y
   ``os.replace``. Si algo falla, el CSV vigente queda intacto.

Nada aquí conoce Tiingo: la fuente es cualquier ``PriceProvider``. ``hoy`` y ``ahora`` se
inyectan: misma entrada, misma salida.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from investmentsys.config import ActualizacionConfig
from investmentsys.data.csv_provider import COLUMNA_FECHA, FORMATO_FECHA, CSVPriceProvider
from investmentsys.data.provider import DatosInvalidosError, PriceProvider
from investmentsys.data.tiingo_provider import ultimo_mes_cerrado

FORMATO_MARCA = "%Y%m%dT%H%M%S"
SUFIJO_BACKUP = "_backup_"
MESES_DIFF = 3
NOMBRE_RESUMEN = "resumen"


class Estado(StrEnum):
    ESCRITO = "escrito"
    SIN_CAMBIOS = "sin_cambios"
    SIMULACION = "simulacion"  # validó todo pero no escribió (--dry-run)
    ABORTADO = "abortado"


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProblemaSanidad(_Modelo):
    regla: str
    activo: str | None
    mes: str | None
    detalle: str


class Discrepancia(_Modelo):
    activo: str
    mes: str
    retorno_vigente: float
    retorno_nuevo: float
    diferencia: float


class ContinuidadActivo(_Modelo):
    activo: str
    meses_comparados: int
    diferencia_maxima: float | None
    mes_diferencia_maxima: str | None


class ResultadoContinuidad(_Modelo):
    tolerancia: float
    ventana: tuple[str, str] | None
    por_activo: tuple[ContinuidadActivo, ...]
    discrepancias: tuple[Discrepancia, ...]
    # Meses cerrados que el vigente tiene y el panel nuevo no: nunca se pierde historia.
    meses_perdidos: dict[str, tuple[str, ...]]
    # Meses del vigente aún sin cerrar en `hoy` (precio provisional): no son comparables.
    meses_provisionales_excluidos: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.discrepancias and not self.meses_perdidos


class CoberturaActivo(_Modelo):
    activo: str
    meses_descargados: int
    desde: str
    hasta: str
    meses_en_vigente: int
    meses_nuevos: tuple[str, ...]


class FilaDiff(_Modelo):
    mes: str
    activo: str
    vigente: float | None
    nuevo: float | None
    diferencia_relativa: float | None


class ResumenActualizacion(_Modelo):
    marca: str
    fuente: str
    hoy: date
    ultimo_mes_cerrado: str
    estado: Estado
    motivo: str
    ruta_csv: str
    cobertura: tuple[CoberturaActivo, ...]
    sanidad: tuple[ProblemaSanidad, ...]
    continuidad: ResultadoContinuidad | None
    discrepancias_aceptadas: bool
    diff_ultimos_meses: tuple[FilaDiff, ...]
    sha256_vigente: str | None
    sha256_nuevo: str | None
    backup: str | None


def _mes(marca: pd.Timestamp) -> str:
    return f"{marca:{FORMATO_FECHA}}"


def _retornos(panel: pd.DataFrame) -> pd.DataFrame:
    """Retornos simples mes a mes; ``NaN`` donde falta alguno de los dos precios."""
    return panel / panel.shift(1) - 1.0


# --- 1. sanidad ----------------------------------------------------------------------------


def validar_sanidad(
    panel: pd.DataFrame, config: ActualizacionConfig, fecha_inicio: date
) -> tuple[ProblemaSanidad, ...]:
    """Problemas del panel nuevo por sí solo; vacío = sano."""
    problemas: list[ProblemaSanidad] = []

    def anotar(regla: str, activo: str | None, mes: pd.Timestamp | None, detalle: str) -> None:
        problemas.append(
            ProblemaSanidad(
                regla=regla,
                activo=activo,
                mes=_mes(mes) if mes is not None else None,
                detalle=detalle,
            )
        )

    if panel.empty:
        anotar("panel_vacio", None, None, "la fuente no devolvió ningún mes")
        return tuple(problemas)
    indice = pd.DatetimeIndex(panel.index)
    for repetido in indice[indice.duplicated()].unique():
        anotar("fecha_duplicada", None, repetido, "el mes aparece más de una vez")
    if problemas:
        return tuple(problemas)  # con meses repetidos el resto de reglas no tiene sentido
    if not indice.is_monotonic_increasing:
        anotar("fechas_desordenadas", None, None, "las fechas deben ir en orden ascendente")
        return tuple(problemas)
    for faltante in pd.date_range(indice[0], indice[-1], freq="ME").difference(indice):
        anotar("mes_faltante", None, faltante, "hueco en el calendario del panel")

    primer_mes = pd.Timestamp(fecha_inicio) + pd.offsets.MonthEnd(0)
    retornos = _retornos(panel)
    for activo in (str(c) for c in panel.columns):
        serie = panel[activo]
        validos = serie.dropna()
        if validos.empty:
            anotar("sin_precios", activo, None, "ningún precio")
            continue
        primero = pd.Timestamp(validos.index[0])
        if primero != primer_mes and activo not in config.activos_inicio_tardio:
            anotar(
                "inicio_inesperado",
                activo,
                primero,
                f"empieza en {_mes(primero)} y no en {_mes(primer_mes)}; solo pueden empezar "
                f"tarde {list(config.activos_inicio_tardio)}",
            )
        desde_inicio = serie.loc[primero:]
        for mes in desde_inicio.index[desde_inicio.isna()]:
            anotar("hueco", activo, mes, "sin precio después de su primera observación")
        for mes in desde_inicio.index[desde_inicio <= 0]:
            anotar("precio_no_positivo", activo, mes, f"precio {desde_inicio[mes]:g}")
        r = retornos[activo]
        for mes in r.index[r.abs() > config.retorno_mensual_max]:
            anotar(
                "retorno_absurdo",
                activo,
                mes,
                f"retorno mensual {r[mes]:+.1%} supera ±{config.retorno_mensual_max:.0%}",
            )
    return tuple(problemas)


# --- 2. continuidad ------------------------------------------------------------------------


def validar_continuidad(
    vigente: pd.DataFrame, nuevo: pd.DataFrame, tolerancia: float, cierre: pd.Timestamp
) -> ResultadoContinuidad:
    """Compara retornos mensuales en la ventana solapada (los niveles pueden diferir).

    Se comparan retornos y no precios porque un precio ajustado se reescala hacia atrás con
    cada dividendo: el nivel cambia entre descargas, el retorno no.
    """
    provisionales = tuple(_mes(m) for m in vigente.index[vigente.index > cierre])
    cerrado = vigente.loc[vigente.index <= cierre]
    nuevo_alineado = nuevo.reindex(columns=cerrado.columns)

    perdidos: dict[str, tuple[str, ...]] = {}
    for activo in (str(c) for c in cerrado.columns):
        tenia = cerrado[activo].dropna().index
        tiene = nuevo_alineado[activo].dropna().index
        faltan = tuple(_mes(m) for m in tenia.difference(tiene))
        if faltan:
            perdidos[activo] = faltan

    r_vigente, r_nuevo = _retornos(cerrado), _retornos(nuevo_alineado)
    meses = r_vigente.index.intersection(r_nuevo.index)
    diferencias = (r_nuevo.loc[meses] - r_vigente.loc[meses]).abs()

    por_activo: list[ContinuidadActivo] = []
    discrepancias: list[Discrepancia] = []
    comparados = pd.DatetimeIndex([])
    for activo in (str(c) for c in cerrado.columns):
        d = diferencias[activo].dropna()
        comparados = comparados.union(pd.DatetimeIndex(d.index))
        por_activo.append(
            ContinuidadActivo(
                activo=activo,
                meses_comparados=len(d),
                diferencia_maxima=float(d.max()) if len(d) else None,
                mes_diferencia_maxima=_mes(d.index[int(d.to_numpy().argmax())]) if len(d) else None,
            )
        )
        discrepancias.extend(
            Discrepancia(
                activo=activo,
                mes=_mes(mes),
                retorno_vigente=float(r_vigente.loc[mes, activo]),
                retorno_nuevo=float(r_nuevo.loc[mes, activo]),
                diferencia=float(d[mes]),
            )
            for mes in d.index[d > tolerancia]
        )
    return ResultadoContinuidad(
        tolerancia=tolerancia,
        ventana=(_mes(comparados[0]), _mes(comparados[-1])) if len(comparados) else None,
        por_activo=tuple(por_activo),
        discrepancias=tuple(discrepancias),
        meses_perdidos=perdidos,
        meses_provisionales_excluidos=provisionales,
    )


# --- 3. escritura atómica ------------------------------------------------------------------


def serializar_csv(panel: pd.DataFrame, decimales: int) -> str:
    """Texto del CSV en el formato que lee ``CSVPriceProvider`` (``fecha`` = AAAA-MM)."""
    salida = panel.round(decimales)
    salida.index = pd.Index([_mes(m) for m in panel.index], name=COLUMNA_FECHA)
    return str(salida.to_csv(float_format=f"%.{decimales}f", na_rep="", lineterminator="\n"))


def escribir_csv_atomico(
    panel: pd.DataFrame, destino: Path, config: ActualizacionConfig, marca: str
) -> Path | None:
    """Reemplaza ``destino`` de forma atómica y devuelve la ruta del respaldo (si había vigente).

    El temporal vive en la misma carpeta (``os.replace`` solo es atómico dentro de un sistema
    de archivos) y se relee con ``CSVPriceProvider`` antes de reemplazar nada. Ante cualquier
    fallo se borra el temporal y ``destino`` queda como estaba.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, nombre = tempfile.mkstemp(
        dir=destino.parent, prefix=f".{destino.stem}_", suffix=".tmp"
    )
    temporal = Path(nombre)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as f:
            f.write(serializar_csv(panel, config.decimales_csv))
            f.flush()
            os.fsync(f.fileno())
        releido = CSVPriceProvider(temporal).precios(list(panel.columns))
        esperado = panel.round(config.decimales_csv)
        if not releido.index.equals(esperado.index) or not np.allclose(
            releido.to_numpy(dtype=float), esperado.to_numpy(dtype=float), equal_nan=True
        ):
            raise DatosInvalidosError("el CSV escrito no coincide con el panel validado")
        backup: Path | None = None
        if destino.exists():
            backup = destino.with_name(f"{destino.stem}{SUFIJO_BACKUP}{marca}{destino.suffix}")
            shutil.copy2(destino, backup)
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
    _podar_backups(destino, config.backups_a_conservar)
    return backup


def _podar_backups(destino: Path, conservar: int) -> None:
    patron = f"{destino.stem}{SUFIJO_BACKUP}*{destino.suffix}"
    backups = sorted(destino.parent.glob(patron))  # la marca AAAAMMDDTHHMMSS ordena por fecha
    for viejo in backups[: max(len(backups) - conservar, 0)]:
        viejo.unlink()


# --- orquestación --------------------------------------------------------------------------


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _cobertura(nuevo: pd.DataFrame, vigente: pd.DataFrame | None) -> tuple[CoberturaActivo, ...]:
    filas: list[CoberturaActivo] = []
    for activo in (str(c) for c in nuevo.columns):
        serie = nuevo[activo].dropna()
        previos = (
            vigente[activo].dropna().index
            if vigente is not None and activo in vigente.columns
            else pd.DatetimeIndex([])
        )
        filas.append(
            CoberturaActivo(
                activo=activo,
                meses_descargados=len(serie),
                desde=_mes(serie.index[0]) if len(serie) else "-",
                hasta=_mes(serie.index[-1]) if len(serie) else "-",
                meses_en_vigente=len(previos),
                meses_nuevos=tuple(_mes(m) for m in serie.index.difference(previos)),
            )
        )
    return tuple(filas)


def _diff(nuevo: pd.DataFrame, vigente: pd.DataFrame | None) -> tuple[FilaDiff, ...]:
    """Últimos ``MESES_DIFF`` meses del panel nuevo, más lo que el vigente tenga después."""
    if nuevo.empty:
        return ()
    meses = pd.DatetimeIndex(nuevo.index[-MESES_DIFF:])
    if vigente is not None:
        meses = meses.union(pd.DatetimeIndex(vigente.index[vigente.index >= meses[0]]))
    filas: list[FilaDiff] = []
    for mes in meses:
        for activo in (str(c) for c in nuevo.columns):
            v = _valor(vigente, mes, activo)
            n = _valor(nuevo, mes, activo)
            relativa = n / v - 1.0 if v is not None and n is not None else None
            filas.append(
                FilaDiff(
                    mes=_mes(mes), activo=activo, vigente=v, nuevo=n, diferencia_relativa=relativa
                )
            )
    return tuple(filas)


def _valor(panel: pd.DataFrame | None, mes: pd.Timestamp, activo: str) -> float | None:
    if panel is None or mes not in panel.index or activo not in panel.columns:
        return None
    valor = float(panel[activo].to_numpy(dtype=float)[panel.index.get_loc(mes)])
    return None if np.isnan(valor) else valor


def actualizar_precios(
    fuente: PriceProvider,
    activos: Sequence[str],
    ruta_csv: Path,
    config: ActualizacionConfig,
    fecha_inicio: date,
    *,
    hoy: date,
    ahora: datetime,
    nombre_fuente: str,
    simular: bool = False,
    aceptar_discrepancias: bool = False,
) -> ResumenActualizacion:
    """Descarga, valida y (si todo está verde) reescribe ``ruta_csv``. Nunca lanza por datos
    inválidos: devuelve un resumen con ``estado = ABORTADO`` y el motivo.

    ``aceptar_discrepancias`` es la decisión del humano tras revisar un aborto por continuidad
    (p. ej. un dividendo reexpresado): salta SOLO la comparación de retornos; la sanidad y la
    pérdida de historia siguen abortando.
    """
    marca = ahora.strftime(FORMATO_MARCA)
    cierre = ultimo_mes_cerrado(hoy)
    vigente = CSVPriceProvider(ruta_csv).precios() if ruta_csv.exists() else None

    nuevo = fuente.precios(list(activos))
    nuevo = nuevo.loc[nuevo.index <= cierre]
    # Se conserva el orden de columnas del CSV vigente si el universo no cambió.
    if vigente is not None and set(vigente.columns) == set(nuevo.columns):
        nuevo = nuevo.loc[:, list(vigente.columns)]

    sanidad = validar_sanidad(nuevo, config, fecha_inicio)
    continuidad = (
        validar_continuidad(vigente, nuevo, config.tolerancia_continuidad, cierre)
        if vigente is not None and not sanidad
        else None
    )

    def resumen(estado: Estado, motivo: str, backup: Path | None = None) -> ResumenActualizacion:
        return ResumenActualizacion(
            marca=marca,
            fuente=nombre_fuente,
            hoy=hoy,
            ultimo_mes_cerrado=_mes(cierre),
            estado=estado,
            motivo=motivo,
            ruta_csv=str(ruta_csv),
            cobertura=_cobertura(nuevo, vigente),
            sanidad=sanidad,
            continuidad=continuidad,
            discrepancias_aceptadas=aceptar_discrepancias,
            diff_ultimos_meses=_diff(nuevo, vigente),
            sha256_vigente=_sha256(ruta_csv) if vigente is not None else None,
            sha256_nuevo=hashlib.sha256(
                serializar_csv(nuevo, config.decimales_csv).encode("utf-8")
            ).hexdigest(),
            backup=str(backup) if backup is not None else None,
        )

    if sanidad:
        return resumen(Estado.ABORTADO, f"sanidad: {len(sanidad)} problema(s) en el panel nuevo")
    if continuidad is not None:
        if continuidad.meses_perdidos:
            return resumen(Estado.ABORTADO, "continuidad: el panel nuevo pierde meses del vigente")
        if continuidad.discrepancias and not aceptar_discrepancias:
            return resumen(
                Estado.ABORTADO,
                f"continuidad: {len(continuidad.discrepancias)} retorno(s) difieren más de "
                f"{config.tolerancia_continuidad:.2%} del CSV vigente",
            )
    if vigente is not None and ruta_csv.read_text(encoding="utf-8") == serializar_csv(
        nuevo, config.decimales_csv
    ):
        return resumen(Estado.SIN_CAMBIOS, "el CSV vigente ya contiene exactamente estos datos")
    if simular:
        return resumen(Estado.SIMULACION, "validaciones en verde; no se escribió (simulación)")
    backup = escribir_csv_atomico(nuevo, ruta_csv, config, marca)
    return resumen(Estado.ESCRITO, "validaciones en verde; CSV reemplazado", backup)


# --- presentación ------------------------------------------------------------------------


def formatear_resumen(r: ResumenActualizacion) -> str:
    """Resumen legible (Markdown) para la consola y para ``runs/``."""
    lineas = [
        f"# Actualización de precios {r.marca} — {r.estado.value.upper()}",
        "",
        f"- Fuente: {r.fuente} · hoy: {r.hoy} · último mes cerrado: {r.ultimo_mes_cerrado}",
        f"- CSV: `{r.ruta_csv}`",
        f"- Resultado: **{r.estado.value}** — {r.motivo}",
    ]
    if r.backup:
        lineas.append(f"- Respaldo del CSV anterior: `{r.backup}`")
    lineas += ["", "## Meses descargados por activo", ""]
    lineas += [
        "| Activo | Meses | Desde | Hasta | En el vigente | Meses nuevos |",
        "|---|---|---|---|---|---|",
    ]
    for cob in r.cobertura:
        nuevos = ", ".join(cob.meses_nuevos) if cob.meses_nuevos else "—"
        lineas.append(
            f"| {cob.activo} | {cob.meses_descargados} | {cob.desde} | {cob.hasta} "
            f"| {cob.meses_en_vigente} | {nuevos} |"
        )

    lineas += ["", "## Sanidad", ""]
    if r.sanidad:
        lineas += [
            f"- ✗ `{p.regla}` {p.activo or ''} {p.mes or ''}: {p.detalle}" for p in r.sanidad
        ]
    else:
        lineas.append("- ✓ sin duplicados, huecos, precios ≤ 0 ni retornos absurdos")

    lineas += ["", "## Continuidad contra el CSV vigente", ""]
    c = r.continuidad
    if c is None:
        lineas.append("- no evaluada (sin CSV vigente o panel nuevo insano)")
    else:
        ventana = f"{c.ventana[0]} … {c.ventana[1]}" if c.ventana else "sin solape"
        veredicto = "✓ verde" if c.ok else "✗ ROJA"
        lineas.append(f"- {veredicto} · tolerancia {c.tolerancia:.2%} · ventana {ventana}")
        if c.meses_provisionales_excluidos:
            lineas.append(
                f"- Excluidos por no estar cerrados (precio provisional en el vigente): "
                f"{', '.join(c.meses_provisionales_excluidos)}"
            )
        lineas += [
            "",
            "| Activo | Retornos comparados | Diferencia máx. | Mes |",
            "|---|---|---|---|",
        ]
        for a in c.por_activo:
            maxima = f"{a.diferencia_maxima:.3%}" if a.diferencia_maxima is not None else "—"
            lineas.append(
                f"| {a.activo} | {a.meses_comparados} | {maxima} "
                f"| {a.mes_diferencia_maxima or '—'} |"
            )
        for activo, meses in c.meses_perdidos.items():
            lineas.append(f"- ✗ {activo}: el panel nuevo no trae {', '.join(meses)}")
        if c.discrepancias:
            aceptadas = " (ACEPTADAS por el operador)" if r.discrepancias_aceptadas else ""
            lineas += ["", f"### Discrepancias{aceptadas}", ""]
            lineas += [
                "| Activo | Mes | Retorno vigente | Retorno nuevo | Diferencia |",
                "|---|---|---|---|---|",
            ]
            lineas += [
                f"| {d.activo} | {d.mes} | {d.retorno_vigente:+.2%} | {d.retorno_nuevo:+.2%} "
                f"| {d.diferencia:.2%} |"
                for d in c.discrepancias
            ]

    lineas += ["", f"## Diff de los últimos {MESES_DIFF} meses (vigente → nuevo)", ""]
    lineas += ["| Mes | Activo | Vigente | Nuevo | Δ nivel |", "|---|---|---|---|---|"]
    for f in r.diff_ultimos_meses:
        vigente = f"{f.vigente:.4f}" if f.vigente is not None else "—"
        nuevo = f"{f.nuevo:.4f}" if f.nuevo is not None else "—"
        delta = f"{f.diferencia_relativa:+.3%}" if f.diferencia_relativa is not None else "—"
        lineas.append(f"| {f.mes} | {f.activo} | {vigente} | {nuevo} | {delta} |")
    lineas += ["", "Herramienta de análisis: ninguna salida constituye asesoría financiera.", ""]
    return "\n".join(lineas)


def guardar_resumen(r: ResumenActualizacion, directorio: Path) -> Path:
    """``<directorio>/<marca>/resumen.{json,md}``; devuelve la carpeta."""
    carpeta = directorio / r.marca
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{NOMBRE_RESUMEN}.json").write_text(r.model_dump_json(indent=2), encoding="utf-8")
    (carpeta / f"{NOMBRE_RESUMEN}.md").write_text(formatear_resumen(r), encoding="utf-8")
    return carpeta
