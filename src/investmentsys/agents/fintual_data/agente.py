"""Gestor de Datos y Fintual: la evolución del Gestor (S10, ADR-020). Transaccional, SIN persona.

No es un ``LlmAgent``: el alta de un activo pregunta y espera confirmación entre turnos (y el
prior neutral tiene una custodia de dos turnos), cosa que un sub-agente ``single_turn`` no puede
hacer; un LLM intermedio en un flujo transaccional solo añade un salto. Es un nodo del ruteo
del Director con UNA tool, ``gestionar_datos_y_fricciones``, y su fragmento de cableado.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from investmentsys.config import Config
from investmentsys.data_manager import GestorDatos
from investmentsys.tools.fintual import NOMBRE_TOOL, GestorFintualTools

CABLEADO = f"""\
- GESTOR DE DATOS Y FINTUAL (transaccional, sin voz propia: lo narras tú, atribuyéndole sus
  datos): una sola herramienta, `{NOMBRE_TOOL}(operacion=...)`.
  Solo lectura: "resolver" (ticker) diagnostica un ticker sin modificar nada; "diagnosticar" da
  el detalle del universo vigente (capitalizaciones, cobertura de los stress, advertencias por
  activo: úsala cuando pregunten por ese detalle o por la historia de un activo); "dividendos"
  da las fechas ex-dividendo recientes (solo historia: la fuente no publica el calendario
  futuro; no proyectes la próxima fecha); "cierres" da el último cierre y el cierre ajustado;
  "montos" traduce la cartera objetivo que está sobre la mesa a montos en US$ y la compara con
  la cartera actual bajo las bandas de inercia: dentro de banda la orden es HOLD obligatorio;
  FUERA_DE_BANDA solo señala la desviación, no es una orden. "montos" no lleva argumentos: los
  pesos no se pasan; si no hay cartera sobre la mesa, la herramienta lo rechaza y dice qué falta.
  Cambian el universo: "incorporar", "retirar" (ticker), "refrescar_cap" (cambia una
  capitalización congelada) y "aceptar_prior_neutral" (degrada el prior de TODO el universo).
  Un argumento que no corresponde a la operación se rechaza: manda solo los que la operación usa.
  Alta de un activo, siempre en este orden:
  1. operacion="resolver" con el ticker, y presenta el diagnóstico (desde cuándo hay datos y
     qué limita eso).
  2. Mira `prior.tiene_cap` en la respuesta. Si es true (la fuente expone la capitalización):
     tras confirmar, operacion="incorporar" e informa el valor congelado y su fecha. Si es false
     (ETF o activo sin capitalización en la fuente): haz UNA sola pregunta con estas opciones,
     en este orden: (a) [recomendada] el usuario aporta la capitalización del subyacente o del
     índice que replica → "incorporar" con ticker, prior_cap y prior_metodologia; (b) usar el AUM
     como proxy débil → lo mismo, con prior_metodologia "AUM: proxy débil"; (c) degradar el
     universo COMPLETO a prior neutral → advierte que es todo-o-nada (afecta a todos los
     activos, no solo al nuevo) y del sesgo de equal-weight documentado en ADR-013. Si la
     elige: "incorporar" solo con el ticker y luego "aceptar_prior_neutral", cuya primera llamada
     NO degrada: devuelve la advertencia. Preséntala y espera; solo si el usuario confirma en su
     siguiente mensaje, vuelve a llamarla. Nunca propongas tú el valor de una capitalización.
  3. Toda operación que cambia el universo devuelve `resultados_obsoletos`: decláralos al
     usuario tal como vienen, uno por uno.
"""


def crear_gestor_fintual(config: Config, gestor: GestorDatos) -> list[FunctionTool]:
    return GestorFintualTools(gestor, config).function_tools()
