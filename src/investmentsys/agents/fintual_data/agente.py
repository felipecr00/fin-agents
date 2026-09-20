"""Gestor de Datos y Fintual: la evolución del Gestor (S10, ADR-020). Transaccional, SIN persona.

No es un ``LlmAgent``: el alta de un activo pregunta y espera confirmación entre turnos (y el
prior neutral tiene una custodia de dos turnos), cosa que un sub-agente ``single_turn`` no puede
hacer; un LLM intermedio en un flujo transaccional solo añade un salto. Es un nodo del ruteo
del Director con UNA tool, ``gestionar_datos_y_fricciones``, y su fragmento de cableado.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.tools.function_tool import FunctionTool

from investmentsys.config import Config
from investmentsys.data_manager import GestorDatos
from investmentsys.tools.fintual import NOMBRE_TOOL, GestorFintualTools
from investmentsys.tools.plan_operativo import PlanOperativoTools

CABLEADO = f"""\
- GESTOR DE DATOS Y FINTUAL (transaccional, sin voz propia: lo narras tú, atribuyéndole sus
  datos): una sola herramienta, `{NOMBRE_TOOL}(operacion=...)`.
  Solo lectura: "resolver" (ticker) diagnostica un ticker sin modificar nada; "diagnosticar" da
  el detalle del universo vigente (capitalizaciones, cobertura de los stress, advertencias por
  activo: úsala cuando pregunten por ese detalle o por la historia de un activo); "dividendos"
  da las fechas ex-dividendo recientes (solo historia: la fuente no publica el calendario
  futuro; no proyectes la próxima fecha); "cierres" da el último cierre y el cierre ajustado
  (ambas, de todo el universo o, con `ticker`, de un solo activo del universo);
  "montos" traduce la cartera objetivo que está sobre la mesa a montos en US$ y la compara con
  la cartera actual bajo las bandas de inercia: dentro de banda la orden es HOLD obligatorio;
  FUERA_DE_BANDA solo señala que un activo quedó sobreponderado o subponderado: NO es una orden.
  A partir de "montos" no le digas al usuario que compre o venda algo, ni cuánto. "montos" no
  lleva argumentos: los pesos no se pasan; si no hay cartera sobre la mesa, la herramienta lo
  rechaza y dice qué falta.
  "plan_compra" (aporte_usd, dividendos_usd opcional) es para cuando el usuario trae DINERO
  NUEVO (un aporte, dividendos acreditados): asigna el flujo 100 % a los activos bajo su
  objetivo, en US$ fraccionados y SIN ventas, con las bandas de inercia activas y el filtro
  tributario consultivo. El monto debe ser el que el usuario escribió: si no lo dio, pregúntalo;
  nunca lo estimes. El plan, sus escenarios fiscales («Costo fiscal estimado: $X CLP»), los
  supuestos y el disclaimer se anexan solos: coméntalos, no los copies. Los escenarios con
  venta son información, no recomendaciones ni prohibiciones: no aconsejes vender ni no vender;
  una venta con pérdida es tax-loss harvesting, una estrategia legítima. No es asesoría
  tributaria: recuérdale validar con su contador. El sistema no ejecuta órdenes: el plan lo
  ejecuta el usuario en la app.
  "forzar_orden" (escenario, token) es el Override: SOLO si el usuario, después de ver el plan
  y la advertencia, pide explícitamente forzar un escenario con venta. Va en el turno
  siguiente al plan, con el id del escenario y el token del plan; nunca por iniciativa tuya ni
  en el mismo turno. Queda registrado en el acta operativa con la advertencia que cruzó.
  "dividendos" y "cierres" son consultas puntuales, cuando el usuario pregunta: el Gestor no
  vigila el mercado ni avisa de dividendos o precios; no lo ofrezcas como seguimiento.
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


def crear_gestor_fintual(
    config: Config, gestor: GestorDatos, directorio_runs: Path | None = None
) -> list[FunctionTool]:
    operativo = PlanOperativoTools(config, directorio_runs)
    return GestorFintualTools(gestor, config, operativo).function_tools()
