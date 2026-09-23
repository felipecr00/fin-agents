"""Custodia de PROCEDENCIA (S10-S11): una cifra que llega por un argumento de LLM solo vale si el
usuario la ESCRIBIÓ. Visto con el modelo real: si una cifra puede llegar por un argumento, llega
—copiada de otra parte— con procedencia falsa."""

from __future__ import annotations

import re

from google.adk.tools.tool_context import ToolContext

_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
_MILES = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
DECIMALES = 6


def _lecturas(numero: str) -> set[float]:
    """«1.500» puede ser mil quinientos o uno y medio: valen ambas lecturas del usuario."""
    lecturas = set()
    if _MILES.fullmatch(numero):
        lecturas.add(float(re.sub(r"[.,]", "", numero)))
    if numero.count(".") + numero.count(",") <= 1:
        lecturas.add(float(numero.replace(",", ".")))
    return {round(x, DECIMALES) for x in lecturas}


def numeros_del_usuario(tool_context: ToolContext) -> set[float]:
    """Todo número que el usuario escribió en la sesión (y en el mensaje de este turno)."""
    textos = _textos_del_usuario(tool_context)
    return {x for t in textos for n in _NUMERO.findall(t) for x in _lecturas(n)}


def _textos_del_usuario(tool_context: ToolContext) -> list[str]:
    contenidos = [e.content for e in tool_context.session.events if e.author == "user"]
    return [
        parte.text
        for contenido in (*contenidos, tool_context.user_content)
        for parte in ((contenido.parts or []) if contenido else [])
        if parte.text
    ]


def tickers_que_no_escribio_el_usuario(tickers: list[str], tool_context: ToolContext) -> list[str]:
    """ADR-023: el universo lo define el usuario. Un ticker que él no escribió en la sesión
    (sin distinguir mayúsculas) no puede entrar por un argumento del LLM."""
    escrito = " ".join(_textos_del_usuario(tool_context)).upper()
    return [
        t
        for t in dict.fromkeys(x.strip().upper() for x in tickers if x and x.strip())
        if not re.search(rf"(?<![A-Z0-9]){re.escape(t)}(?![A-Z0-9])", escrito)
    ]


def lo_escribio_el_usuario(valor: float, tool_context: ToolContext) -> bool:
    return round(float(valor), DECIMALES) in numeros_del_usuario(tool_context)
