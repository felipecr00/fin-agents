# ADR 020: Ruteo jerárquico del Director y Gestor-Fintual transaccional de una sola tool

- Fecha: 2026-09-20
- Sprint: S10
- Estado: aceptada (2026-09-20, checkpoint de S10: aprobadas las dos alternativas recomendadas)

## Contexto
El Director cablea hoy 13 entradas planas: `consultar_mesa_trabajo`, seis del Gestor
(`resolver`, `incorporar`, `retirar`, `refrescar_cap`, `aceptar_prior_neutral`,
`diagnosticar`), `estimar_mercado`, `construir_candidatos`, `ajustar_restricciones`,
`diagnosticar_cartera`, `convocar_comite` y el sub-agente `market_analyst`. S10 pide ruteo
jerárquico —personas, Gestor (transaccional, sin persona), comité— y que el Gestor evolucione a
`agents/fintual_data/` con la tool `gestionar_datos_y_fricciones` (ex-dividendos, cierres
ajustados, pesos → montos fraccionados en USD), más `fintual/no_trade_zones.py` (Nivel 3).

Hechos medidos:
- Con el ruteo plano el evalset real está en 22/22 (S9): la confusión entre tools es el riesgo
  que la propuesta v2 anticipa, no un fallo hoy medido. Sacar `estimar_mercado` y
  `diagnosticar_cartera` hacia las personas (ADR-019) no baja la cuenta: salen 2 tools y entran
  2 sub-agentes. La cuenta solo baja si el Gestor se agrupa.
- El alta de un activo es multi-turno con confirmaciones y una custodia de dos turnos
  (`aceptar_prior_neutral`). Un sub-agente `single_turn` no puede preguntarle al usuario
  (spike de ADR-019): un Gestor con LLM propio rompería ese flujo.
- La fuente ya contratada expone lo que pide el punto 4: `tiingo/daily/<t>/prices` diario trae
  `close`, `adjClose`, `divCash` y `splitFactor` (verificado el 2026-09-20 con BNS: ex-dividendos
  2026-01-06, 04-07 y 07-07). Solo hay HISTORIA: la fuente no publica dividendos futuros.

## Decisión
1. **Ruteo del Director, 8 entradas en 4 grupos**:
   - Personas (sub-agentes `single_turn`): `market_analyst`, `estadistico`, `esceptico`.
   - Gestor-Fintual (transaccional, sin LLM): `gestionar_datos_y_fricciones`.
   - Constructor (tools directas, sin cambio): `construir_candidatos`, `ajustar_restricciones`.
   - Comité: `convocar_comite`. Y la mesa, del Director: `consultar_mesa_trabajo`.
   `estimar_mercado` y `diagnosticar_cartera` dejan de ser tools del Director. El CABLEADO se
   reescribe por grupos; `INSTRUCCION` (el spec literal de S8) no se toca. `ATIENDE` y
   `componer_sala` siguen saliendo de lo que de verdad se cablea: las sillas del Estadístico y
   del Escéptico pasan a `conversa: true`.
2. **El Gestor es UNA FunctionTool con `operacion`**, sin persona:
   `gestionar_datos_y_fricciones(operacion, ticker?, prior_cap?, prior_metodologia?)`.
   - Operaciones heredadas, mismo código y mismas custodias de `GestorTools` (sello, obsoletos,
     neutral en dos turnos): `resolver`, `incorporar`, `retirar`, `refrescar_cap`,
     `aceptar_prior_neutral`, `diagnosticar`.
   - Operaciones nuevas, de solo lectura: `dividendos` (fechas ex-dividendo y monto por acción
     de cada activo del universo; historia, sin proyectar fechas futuras), `cierres` (último
     cierre y cierre ajustado con su fecha) y `montos` (ver 3).
   - Un argumento que no corresponde a la operación se RECHAZA (`status: rechazado`), no se
     ignora. `agents/fintual_data/` arma la tool y su fragmento de cableado; la FunctionTool
     vive en `tools/` como las demás; los datos diarios entran por dos métodos nuevos del
     protocolo puro `FuenteActivos`.
3. **`montos` no recibe cifras del LLM.** Pesos objetivo = la cartera recomendada vigente sobre
   la mesa (validada o exploratoria: hereda su `validado` y su prefijo); pesos actuales y valor
   de la cartera = `config.yaml: portafolio`. Pasa por `fintual/no_trade_zones.py`: banda
   absoluta en puntos porcentuales alrededor del peso objetivo (`fintual.banda_inercia`,
   default 0.05, configurable por activo); dentro de banda la orden del activo es `HOLD`
   obligatorio y, si todos lo están, la orden global es `HOLD`. Fuera de banda S10 solo lo
   SEÑALA (`FUERA_DE_BANDA`, con la desviación): cuánto comprar con aportes es
   `cash_flow_alloc` (S11). Los montos objetivo en USD se redondean a 2 decimales por mayor
   residuo, de modo que sumen exactamente el valor de la cartera (`fintual/montos.py`).
4. **Contrato nuevo** `contracts/fintual.py` (se añade; ningún contrato existente cambia):
   `OrdenInercia` (`HOLD` | `FUERA_DE_BANDA`), `DecisionInercia` (activo, peso objetivo, peso
   actual, desviación, banda, orden, monto objetivo USD) y `PlanInercia` (sello
   `universe_version`, `validado`, decisiones, orden global, disclaimer operativo de la
   enmienda §2). `test_fronteras.py` extiende `MODULOS_PUROS` a `fintual`.
5. **Evalset**: los criterios por tool aceptan la clave `tool:operacion`
   (`gestionar_datos_y_fricciones:incorporar`); los 22 casos se migran mecánicamente.

## Alternativas descartadas
- **Dejar las 5 mutaciones del Gestor planas y añadir `gestionar_datos_y_fricciones` solo para
  lo nuevo.** Es lo más seguro para el function-calling (firmas tipadas por operación, evalset
  intacto), pero el Director queda con 13 entradas: no hay ruteo jerárquico y contradice el
  punto 2 del spec. Es el plan B explícito: si los casos de alta (`alta_*`, `prior_*`)
  retroceden respecto de la línea base 22/22 con el modelo real, se vuelve a esta opción y se
  documenta aquí.
- **Gestor como `LlmAgent` thin (propuesta v2 §4.3).** El alta necesita preguntar y esperar
  confirmación entre turnos; `single_turn` no puede, y un LLM intermedio en un flujo
  transaccional con custodia solo añade un salto. La enmienda al spec ya lo dice: "sin persona".
- **Gestor como `BaseAgent` determinista con `input_schema`.** Sería un "agente sin LLM"
  literal, pero las custodias del Gestor usan `ToolContext` (turno, estado); portarlas a
  `InvocationContext` es riesgo sin ganancia frente a una FunctionTool.
- **Pesos objetivo o valor de cartera como argumentos de `montos`.** Cifras por argumentos de
  LLM: frontera del proyecto.
- **Proyectar la próxima fecha ex-dividendo por cadencia.** Sería una cifra que ninguna fuente
  publicó; se reporta la historia y se dice que la fuente no trae calendario futuro.

## Consecuencias
- El Director elige entre 8 entradas agrupadas en vez de 13 planas; la firma del Gestor pierde
  tipado por operación y lo compensa el rechazo en código de argumentos ajenos.
- `dividendos` y `cierres` consumen cuota de la fuente en conversación (1 request por activo;
  tier gratuito 50/h): se cachean por sesión y fecha.
- `montos` es informativo en S10: no es una orden de compra. El plan de aportes, el filtro
  tributario consultivo y el override son S11 y consumirán `PlanInercia`.
- Todo output operativo lleva el disclaimer "estimación algorítmica, no asesoría tributaria ni
  financiera".
