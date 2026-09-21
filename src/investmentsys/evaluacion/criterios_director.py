"""Criterios deterministas del evalset del Director (ADR-015). Código puro: sin ADK ni LLM.

Un turno observado es lo que pasó tras un mensaje del usuario: qué herramientas se llamaron y
con qué argumentos, qué respondieron y qué texto final vio el usuario. Los criterios son toscos
a propósito (como en ADR-010): detectan conducta claramente mala —llamar a lo prohibido, inventar
una cifra, no ofrecer las opciones— y no gradúan la calidad de la redacción.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from investmentsys.contracts import Especialista
from investmentsys.evaluacion.criterios import ResultadoCriterio

# Una "cifra" es un número con decimales o un porcentaje: lo que un lector tomaría por un dato.
# Los enteros sueltos (numeración de listas, "4 activos", años) no se exigen respaldados.
CIFRA = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)?\s?%|(?<![\w.,])-?\d+[.,]\d+")
# Un monto con separador de miles ("9,739.94", "US$ 2,243.52"): una sola cifra, no dos.
MILES = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
CIFRA_CON_MILES = re.compile(r"(?<![\w.,])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\s?%?|" + CIFRA.pattern)
NUMERO = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")
PORCENTAJE = 100.0
VINETA = re.compile(r"^(?:[*\-•]|\d+[.)])\s")
# "en lugar de vender…" y "evitar ventas" también niegan (visto con el modelo real, 2026-09-21).
NEGACIONES = (
    "no ",
    "ni ",
    "sin ",
    "fuera de",
    "tampoco",
    "nunca",
    "en lugar de",
    "en vez de",
    "evita",
)
# S9 — atribución: una cifra de retorno, riesgo o correlación se dice con su fuente.
TERMINOS_DE_CIFRA_ATRIBUIBLE = (
    "retorno",
    "rentabilidad",
    "rendimiento",
    "volatilidad",
    "riesgo",
    "sharpe",
    "drawdown",
    "caida",
    "perdida",
    "correlaci",
    "covarianza",
    "var ",
    "cvar",
)
# S9 — los bloques para el usuario los anexa el código; un encabezado del LLM que los imite sobra.
ENCABEZADO_DE_BLOQUE = re.compile(
    r"^#{1,6}\s.*(mesa de trabajo|en la sala|orden preparatoria|ficha de origen"
    r"|cronologia del comite|plan de compra neta|override registrado)",
    re.MULTILINE,
)
FILA_O_VINETA = re.compile(r"^(?:[*\-•|>]|\d+[.)])\s?")
# La marca invisible con la que ``agents/anexos.py`` abre lo que anexa el código (un test fija
# que sean la misma): lo que va antes es lo que redactó el Director.
MARCA_ANEXO = "\u2063\u2063"
# S-lienzo: palabras en mayúsculas que NO son tickers (siglas del dominio y énfasis corrientes).
POSIBLE_TICKER = re.compile(r"(?<![\w$])[A-Z]{2,5}(?![\w])")
NO_SON_TICKERS = frozenset(
    [
        "NO",
        "SI",
        "ETF",
        "ETFS",
        "USD",
        "US",
        "EE",
        "UU",
        "AUM",
        "HRP",
        "OOS",
        "CLP",
        "IA",
        "LLM",
        "MESA",
        "SOLO",
        "TODO",
        "NADA",
        "SIN",
        "CON",
        "QUE",
        "LOS",
        "LAS",
        "UNA",
        "UN",
        "NI",
        "YA",
        "ID",
        "OK",
        "PR",
        "BL",
        "VAR",
        "CVAR",
        "HHI",
        "ADR",
        "SII",
        "FX",
        "NYSE",
        "SEC",
        "CEO",
        "PIB",
        "FED",
        "IPC",
        "TU",
        "TUS",
        "MI",
        "MIS",
        "EL",
        "LA",
        "DE",
        "DEL",
        "AL",
        "EN",
        "ES",
        "SE",
        "LO",
        "POR",
        "PARA",
        "MUY",
        "MAS",
        "HOLD",
        "NUNCA",
        "TUYO",
        "AQUI",
        "HOY",
    ]
)
TOLERANCIA_ARGUMENTOS = 1e-9  # punto flotante al serializar argumentos, no un parámetro


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArgumentosExigidos(_Modelo):
    exige: dict[str, Any] = Field(
        default_factory=dict, description="Pares clave: valor que alguna llamada debe traer."
    )
    prohibe: tuple[str, ...] = Field(
        default=(), description="Argumentos que NINGUNA llamada a esa tool puede traer."
    )


class Criterios(_Modelo):
    """Lo que se exige de un turno (o, en ``conversacion``, de todos los turnos juntos)."""

    tools_permitidas: tuple[str, ...] | None = Field(
        default=None, description="Si se define, no se puede llamar a ninguna otra ([] = ninguna)."
    )
    tools_obligatorias: tuple[str, ...] = ()
    tools_prohibidas: tuple[str, ...] = ()
    argumentos: dict[str, ArgumentosExigidos] = Field(default_factory=dict)
    status: dict[str, str] = Field(
        default_factory=dict, description="`status` de la ÚLTIMA respuesta de cada tool."
    )
    status_prohibido: dict[str, str] = Field(
        default_factory=dict, description="`status` que NINGUNA respuesta de esa tool puede traer."
    )
    texto_alguno: tuple[tuple[str, ...], ...] = Field(
        default=(), description="Por cada grupo, el texto contiene al menos uno de sus términos."
    )
    texto_prohibido: tuple[str, ...] = ()
    solo_negado: tuple[str, ...] = Field(
        default=(),
        description=(
            "Términos que solo pueden aparecer en una línea que los NIEGA ('no podemos…', 'no es "
            "una recomendación aprobada'): decir que algo NO se hace está bien; hacerlo u "
            "ofrecerlo, no."
        ),
    )
    cifras_respaldadas: bool = Field(
        default=False,
        description="Toda cifra del texto sale de una tool o la dijo el usuario (con redondeo).",
    )
    sin_bloques_imitados: bool = Field(
        default=False,
        description=(
            "El Director no rehace los bloques que anexa el código (mesa, sala, orden, ficha): "
            "a lo sumo un encabezado de bloque por cada anexo del turno (S9)."
        ),
    )
    cifras_atribuidas: bool = Field(
        default=False,
        description=(
            "Toda cifra de retorno, riesgo o correlación que diga EL DIRECTOR nombra al "
            "especialista fuente en su párrafo (S9). La voz de una persona ya es su atribución."
        ),
    )
    habla: tuple[str, ...] = Field(
        default=(),
        description="Personas (sub-agentes) que le hablaron al usuario en el turno (S10).",
    )
    sin_tickers_ajenos: bool = Field(
        default=False,
        description=(
            "El Director no nombra ningún ticker que no haya escrito el usuario o devuelto una "
            "herramienta en la conversación: no inventa ni sugiere activos (ADR-023). Tosco: "
            "mira palabras de 2 a 5 MAYÚSCULAS fuera de una lista de siglas corrientes."
        ),
    )
    hitos_en_vivo: int = Field(
        default=0,
        ge=0,
        description=(
            "Mínimo de hitos del comité que llegaron al chat MIENTRAS `convocar_comite` corría: "
            "entre su llamada y su respuesta, no después (S11, ADR-021)."
        ),
    )
    no_repite_cifras: bool = Field(
        default=False,
        description=(
            "El Director no repite las cifras que ya dijo una persona en el turno (salvo las que "
            "ya conocía: su instrucción, el usuario, turnos previos): coordina, no re-narra "
            "(S10, ADR-019)."
        ),
    )


@dataclass(frozen=True)
class TurnoObservado:
    usuario: str
    llamadas: tuple[tuple[str, dict[str, Any]], ...] = ()
    respuestas: tuple[tuple[str, dict[str, Any]], ...] = ()
    texto: str = ""
    respaldo_previo: tuple[str, ...] = field(default=())
    """Salidas de tools y mensajes del usuario de los turnos ANTERIORES (respaldan cifras)."""
    voces: tuple[tuple[str, str], ...] = ()
    """(persona, texto): lo que dijeron al usuario los sub-agentes con voz propia (S10)."""
    hitos_en_vivo: int = 0
    """Eventos del comité recibidos ANTES de que su herramienta respondiera (S11)."""
    conversado: tuple[str, ...] = ()
    """Lo dicho por el usuario y devuelto por las tools en turnos ANTERIORES, SIN la instrucción
    del Director (que nombra tickers de ejemplo): de ahí salen los tickers que sí puede nombrar."""

    @property
    def leido(self) -> str:
        """Todo lo que el usuario leyó en el turno: las personas primero, luego el Director."""
        return "\n".join([*(t for _, t in self.voces), self.texto])


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos: "Todo-o-Nada" y "todo o nada" no deben depender del tilde."""
    plano = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in plano if not unicodedata.combining(c))


def lineas_no_negadas(texto: str) -> list[str]:
    """Líneas (normalizadas) que ni niegan ni cuelgan de un encabezado que niega.

    Una viñeta hereda la negación de la última línea que no es viñeta: bajo "Fuera de alcance
    (no podemos hacer):", "* ejecutar órdenes" está negada aunque no diga "no".
    """
    afirmadas: list[str] = []
    encabezado_niega = False
    for linea in normalizar(texto).splitlines():
        # "fuera de banda" es un estado de las No-Trade Zones (S10), no una negación.
        limpia = linea.strip().replace("fuera de banda", "fuera-de-banda")
        if not limpia or set(limpia) <= set("-*_"):  # vacía o separador: no corta la lista
            continue
        niega = any(n in f"{limpia} " for n in NEGACIONES)
        if VINETA.match(limpia):
            if not (niega or encabezado_niega):
                afirmadas.append(limpia)
            continue
        encabezado_niega = niega
        if not niega:
            afirmadas.append(limpia)
    return afirmadas


def _numeros_de(fuentes: Iterable[str]) -> list[float]:
    return [float(n) for fuente in fuentes for n in NUMERO.findall(fuente)]


def _lecturas(cifra: str) -> list[str]:
    """Cómo puede leerse una cifra escrita: "9,739.94" es un monto con separador de miles;
    "0,75" es un decimal con coma. Ante la duda ("9,739") valen las dos lecturas."""
    crudo = cifra.replace("%", "").strip()
    lecturas = []
    if MILES.fullmatch(crudo):
        lecturas.append(crudo.replace(",", ""))
    if crudo.count(",") <= 1 and not ("," in crudo and "." in crudo):
        lecturas.append(crudo.replace(",", "."))
    return lecturas


def _respalda(valores: list[float], lectura: str) -> bool:
    decimales = len(lectura.partition(".")[2])
    objetivo = abs(float(lectura))
    candidatos = (abs(v) * escala for v in valores for escala in (1.0, PORCENTAJE))
    return any(round(c, decimales) == round(objetivo, decimales) for c in candidatos)


def cifras_sin_respaldo(texto: str, fuentes: Iterable[str]) -> list[str]:
    """Cifras del texto que ninguna fuente respalda, ni redondeadas ni como porcentaje.

    Una cifra con ``d`` decimales está respaldada por un valor ``v`` de las fuentes si coincide
    con ``v`` o con ``100·v`` redondeados a ``d`` decimales: 0.7578 respalda "0.76" y "75.78 %".
    """
    valores = _numeros_de(fuentes)
    sin_respaldo = []
    for cifra in CIFRA_CON_MILES.findall(texto):
        if not any(_respalda(valores, lectura) for lectura in _lecturas(cifra)):
            sin_respaldo.append(cifra.strip())
    return sin_respaldo


def fuentes_atribuibles() -> tuple[str, ...]:
    """Cómo se nombra a quien produce cifras: "Estadístico", "el comité", "Gestor de Datos"…

    Sale de ``Especialista`` (la fuente única de la sala); el Director coordina, no calcula.
    """
    nombres = [normalizar(e.value) for e in Especialista if e is not Especialista.DIRECTOR]
    return tuple(dict.fromkeys([*nombres, *(n.split()[0] for n in nombres)]))


def cifras_sin_atribuir(texto: str) -> list[str]:
    """Líneas con una cifra de retorno, riesgo o correlación cuyo párrafo no nombra la fuente.

    Tosco a propósito: la unidad es el párrafo, y una lista o tabla sin nombre propio hereda la
    atribución del párrafo que la encabeza ("Según el Estadístico:" y debajo las viñetas).
    """
    fuentes = fuentes_atribuibles()
    huerfanas: list[str] = []
    encabezado_atribuye = False
    for parrafo in re.split(r"\n\s*\n", normalizar(texto)):
        lineas = [ln.strip() for ln in parrafo.splitlines() if ln.strip()]
        if not lineas or all(set(ln) <= set("-*_ ") for ln in lineas):
            continue  # separador: no corta la herencia del encabezado
        es_lista = all(FILA_O_VINETA.match(ln) for ln in lineas)
        atribuye = any(f in parrafo for f in fuentes) or (es_lista and encabezado_atribuye)
        if not atribuye:
            huerfanas += [
                ln
                for ln in lineas
                if CIFRA.search(ln) and any(t in f"{ln} " for t in TERMINOS_DE_CIFRA_ATRIBUIBLE)
            ]
        if not es_lista:
            encabezado_atribuye = atribuye
    return huerfanas


ENCABEZADO = re.compile(r"^#{1,6}\s", re.MULTILINE)
MIN_FILAS_DE_BLOQUE = 2


def bloques_con_contenido(texto: str) -> list[str]:
    """Encabezados de bloque que REHACEN un bloque: el título y, debajo, contenido estructurado
    (filas de tabla o viñetas). Un encabezado que solo anuncia los anexos («### Mesa de trabajo
    y fichas», seguido de una frase) nombra el bloque, no lo rehace (visto con el modelo real)."""
    rehechos = []
    for m in ENCABEZADO_DE_BLOQUE.finditer(texto):
        resto = texto[m.end() :]
        siguiente = ENCABEZADO.search(resto)
        seccion = resto[: siguiente.start()] if siguiente else resto
        filas = [ln for ln in seccion.splitlines() if FILA_O_VINETA.match(ln.strip())]
        if len(filas) >= MIN_FILAS_DE_BLOQUE:
            rehechos.append(m.group(0))
    return rehechos


def coincide(real: Any, esperado: Any) -> bool:
    """Igualdad tolerante: números con holgura de punto flotante; de un dict, solo lo esperado."""
    if isinstance(esperado, dict):
        return isinstance(real, dict) and all(coincide(real.get(k), v) for k, v in esperado.items())
    if isinstance(esperado, int | float) and not isinstance(esperado, bool):
        return (
            isinstance(real, int | float)
            and not isinstance(real, bool)
            and abs(float(real) - float(esperado)) <= TOLERANCIA_ARGUMENTOS
        )
    return bool(real == esperado)


def _resultado(criterio: str, fallos: list[str], bien: str) -> ResultadoCriterio:
    return ResultadoCriterio(
        criterio=criterio, cumple=not fallos, detalle="; ".join(fallos) if fallos else bien
    )


def evaluar(criterios: Criterios, turno: TurnoObservado, prefijo: str) -> list[ResultadoCriterio]:
    """Un ``ResultadoCriterio`` por criterio DEFINIDO; ``prefijo`` dice de qué turno es."""
    llamadas = [nombre for nombre, _ in turno.llamadas]
    vistas = ", ".join(llamadas) or "ninguna"
    resultados: list[ResultadoCriterio] = []

    if criterios.tools_permitidas is not None:
        ajenas = sorted(set(llamadas) - set(criterios.tools_permitidas))
        resultados.append(
            _resultado(
                f"{prefijo}.tools_permitidas",
                [f"llamó a {ajenas}; solo se admitía {list(criterios.tools_permitidas)}"]
                if ajenas
                else [],
                f"llamadas: {vistas}",
            )
        )
    if criterios.tools_obligatorias:
        faltan = [t for t in criterios.tools_obligatorias if t not in llamadas]
        resultados.append(
            _resultado(
                f"{prefijo}.tools_obligatorias",
                [f"no llamó a {faltan} (llamadas: {vistas})"] if faltan else [],
                f"llamadas: {vistas}",
            )
        )
    if criterios.tools_prohibidas:
        usadas = [t for t in criterios.tools_prohibidas if t in llamadas]
        resultados.append(
            _resultado(
                f"{prefijo}.tools_prohibidas",
                [f"llamó a {usadas}"] if usadas else [],
                f"llamadas: {vistas}",
            )
        )
    for tool, exigido in criterios.argumentos.items():
        propias = [args for nombre, args in turno.llamadas if nombre == tool]
        fallos = []
        if exigido.exige and not any(coincide(args, exigido.exige) for args in propias):
            fallos.append(f"ninguna llamada a {tool} trae {exigido.exige} (vistas: {propias})")
        con_prohibido = [
            k for args in propias for k in exigido.prohibe if args.get(k) not in (None, "")
        ]
        if con_prohibido:
            fallos.append(f"{tool} recibió argumentos prohibidos {sorted(set(con_prohibido))}")
        resultados.append(_resultado(f"{prefijo}.argumentos.{tool}", fallos, f"{propias}"))
    for tool, esperado in criterios.status.items():
        estados = [r.get("status") for nombre, r in turno.respuestas if nombre == tool]
        ok = bool(estados) and estados[-1] == esperado
        resultados.append(
            _resultado(
                f"{prefijo}.status.{tool}",
                [] if ok else [f"se esperaba status '{esperado}' y hubo {estados or 'ninguna'}"],
                f"status: {estados}",
            )
        )
    for tool, vetado in criterios.status_prohibido.items():
        estados = [r.get("status") for nombre, r in turno.respuestas if nombre == tool]
        resultados.append(
            _resultado(
                f"{prefijo}.status_prohibido.{tool}",
                [f"{tool} respondió '{vetado}'"] if vetado in estados else [],
                f"status: {estados or 'ninguna'}",
            )
        )
    plano = normalizar(turno.leido)
    if criterios.texto_alguno:
        ausentes = [
            list(grupo)
            for grupo in criterios.texto_alguno
            if not any(normalizar(termino) in plano for termino in grupo)
        ]
        resultados.append(
            _resultado(
                f"{prefijo}.texto_alguno",
                [f"el texto no contiene ninguno de {g}" for g in ausentes],
                "todos los grupos presentes",
            )
        )
    if criterios.texto_prohibido:
        presentes = [t for t in criterios.texto_prohibido if normalizar(t) in plano]
        resultados.append(
            _resultado(
                f"{prefijo}.texto_prohibido",
                [f"el texto contiene {presentes}"] if presentes else [],
                "ningún término prohibido",
            )
        )
    if criterios.solo_negado:
        afirmados = [
            f"'{termino}' en «{linea.strip()[:120]}»"
            for linea in lineas_no_negadas(turno.leido)
            for termino in criterios.solo_negado
            if normalizar(termino) in linea
        ]
        resultados.append(
            _resultado(f"{prefijo}.solo_negado", afirmados, "solo aparecen negados, o no aparecen")
        )
    if criterios.cifras_respaldadas:
        fuentes = [
            *turno.respaldo_previo,
            turno.usuario,
            *(json.dumps(r, ensure_ascii=False) for _, r in turno.respuestas),
        ]
        huerfanas = cifras_sin_respaldo(turno.leido, fuentes)
        resultados.append(
            _resultado(
                f"{prefijo}.cifras_respaldadas",
                [f"cifras que no salen de ninguna tool ni del usuario: {huerfanas}"]
                if huerfanas
                else [],
                "toda cifra tiene respaldo",
            )
        )
    if criterios.sin_bloques_imitados:
        encabezados = bloques_con_contenido(normalizar(turno.leido))
        anexados = sum(1 for _, r in turno.respuestas if "anexo" in r)
        resultados.append(
            _resultado(
                f"{prefijo}.sin_bloques_imitados",
                [f"{len(encabezados)} encabezados para {anexados} anexo(s): {encabezados}"]
                if len(encabezados) > anexados
                else [],
                "los bloques son solo los del código",
            )
        )
    if criterios.cifras_atribuidas:
        sin_fuente = cifras_sin_atribuir(turno.texto)
        resultados.append(
            _resultado(
                f"{prefijo}.cifras_atribuidas",
                [f"cifras sin especialista fuente: {sin_fuente}"] if sin_fuente else [],
                "toda cifra de retorno, riesgo o correlación nombra a su fuente",
            )
        )
    if criterios.sin_tickers_ajenos:
        conocidos = " ".join(
            [
                turno.usuario,
                *turno.conversado,
                *(json.dumps(r, ensure_ascii=False) for _, r in turno.respuestas),
            ]
        )
        dichos = set(POSIBLE_TICKER.findall(turno.texto.split(MARCA_ANEXO)[0])) - NO_SON_TICKERS
        ajenos = sorted(t for t in dichos if not re.search(rf"(?<!\w){t}(?!\w)", conocidos))
        # Un ticker inventado que viaja como ARGUMENTO vuelve en la respuesta de la tool y
        # parecería "conocido": los de `ticker`/`tickers` deben estar en lo que escribió el
        # usuario (o en lo conversado antes), no en la respuesta de esa misma llamada.
        escrito = " ".join([turno.usuario, *turno.conversado]).upper()
        pedidos = {
            str(t).strip().upper()
            for _, args in turno.llamadas
            for t in [args.get("ticker"), *(args.get("tickers") or [])]
            if t
        }
        ajenos += sorted(
            t for t in pedidos if not re.search(rf"(?<!\w){re.escape(t)}(?!\w)", escrito)
        )
        resultados.append(
            _resultado(
                f"{prefijo}.sin_tickers_ajenos",
                [f"tickers que nadie le dio al Director: {ajenos}"] if ajenos else [],
                "no nombra activos que el usuario no proveyó",
            )
        )
    if criterios.hitos_en_vivo:
        resultados.append(
            _resultado(
                f"{prefijo}.hitos_en_vivo",
                [
                    f"llegaron {turno.hitos_en_vivo} hitos en vivo; se exigían "
                    f"{criterios.hitos_en_vivo}"
                ]
                if turno.hitos_en_vivo < criterios.hitos_en_vivo
                else [],
                f"{turno.hitos_en_vivo} hitos del comité durante la llamada",
            )
        )
    if criterios.habla:
        hablaron = {persona for persona, texto in turno.voces if texto.strip()}
        mudas = [p for p in criterios.habla if p not in hablaron]
        resultados.append(
            _resultado(
                f"{prefijo}.habla",
                [f"no le hablaron al usuario: {mudas} (hablaron: {sorted(hablaron)})"]
                if mudas
                else [],
                f"hablaron: {sorted(hablaron)}",
            )
        )
    if criterios.no_repite_cifras:
        de_personas = {c.strip() for _, texto in turno.voces for c in CIFRA.findall(texto)}
        propio = turno.texto.split(MARCA_ANEXO)[0]  # el anexo va al final del último texto
        # Lo que el Director ya sabía por su cuenta (su instrucción, el usuario, turnos previos:
        # p. ej. el tope de 70 % de la sesión) no es re-narrar a la persona.
        sabidas = [*turno.respaldo_previo, turno.usuario]
        repetidas = sorted(
            c
            for c in {c.strip() for c in CIFRA.findall(propio)} & de_personas
            if cifras_sin_respaldo(c, sabidas)
        )
        resultados.append(
            _resultado(
                f"{prefijo}.no_repite_cifras",
                [f"el Director repitió cifras que ya dijo una persona: {repetidas}"]
                if repetidas
                else [],
                "el Director no re-narra a la persona",
            )
        )
    return resultados
