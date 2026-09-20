# Propuesta de Evolución de Arquitectura: Del Monolito Opaco a la Sala de Inversión Observable

> **Documento Técnico de Arquitectura & Reingeniería de Sistema Multiagente (ADK)**  
> **Ámbito:** Asset Management Sistemático, Operación Real en Fintual Acciones y Laboratorio Cuantitativo de I+D  
> **Fecha:** Septiembre 2026  
> **Versión:** 2.0.0 (Final Consolidada)

---

## Índice General

1. [Diagnóstico del Sistema Vigente y Crítica de Fondo](#1-diagnóstico-del-sistema-vigente-y-crítica-de-fondo)  
2. [Principios de Diseño y Fundamentos No Negociables](#2-principios-de-diseño-y-fundamentos-no-negociables)  
3. [Arquitectura del Target State: Las Capas del Sistema](#3-arquitectura-del-target-state-las-capas-del-sistema)  
4. [Especialistas como Sub-Agentes Delgados (Thin LlmAgents)](#4-especialistas-como-sub-agentes-delgados-thin-llmagents)  
5. [La Pizarra de la Mesa de Trabajo (State Introspection)](#5-la-pizarra-de-la-mesa-de-trabajo-state-introspection)  
6. [Observabilidad del Comité y Streaming de Hitos](#6-observabilidad-del-comité-y-streaming-de-hitos)  
7. [Operación Pragmática en Fintual Acciones (Capa Real)](#7-operación-pragmática-en-fintual-acciones-capa-real)  
8. [Laboratorio Cuantitativo de I+D & Modelos Generativos](#8-laboratorio-cuantitativo-de-id--modelos-generativos)  
9. [Ruteo de Cómputo, Inferencia y Control de Costos](#9-ruteo-de-cómputo-inferencia-y-control-de-costos)  
10. [Árbol de Archivos y Especificación de Contratos](#10-árbol-de-archivos-y-especificación-de-contratos)  
11. [Plan de Implementación en Sprints](#11-plan-de-implementación-en-sprints)  
12. [Matriz de Verificación y Testing](#12-matriz-de-verificación-y-testing)

---

## 1\. Diagnóstico del Sistema Vigente y Crítica de Fondo

### 1.1 Lo que Funciona y Debe Preservarse

El sistema actual construido sobre Google Agent Development Kit (ADK) cuenta con una ingeniería base sólida que no debe destruirse:

* **Fronteras arquitectónicas puras:** Las carpetas `quant/`, `portfolio/`, `risk/`, `contracts/` y `data_manager/` son módulos de Python puro, deterministas, sin llamadas a LLMs ni dependencias de ADK (garantizado estrictamente por `tests/test_fronteras.py`).  
* **Invariantes por contratos Pydantic:** Cada cálculo y transición de estado viaja sellado con el identificador `universe_version`. Toda mutación en el universo de inversión invalida automáticamente cualquier resultado anterior.  
* **Seguridad de estado:** Las matrices de covarianza, optimizaciones numéricas y ponderaciones vectoriales jamás transitan como argumentos generados en texto libre por un LLM; residen en el `SessionState` de ADK y son manipuladas exclusivamente por herramientas deterministas (`FunctionTool`).

### 1.2 La Crítica de Fondo: El Equipo no Existe como Experiencia

A pesar de su solidez interna, el sistema falla en su promesa fundamental de producto:

1. **Asimetría injustificada de interfaz:** El usuario puede conversar con el `Analista de Mercado` (sub-agente), pero el `Estadístico (Quant)`, el `Escéptico (Validador)` y el `Gestor de Datos` son funciones matemáticas invisibles detrás de tools del Director. La naturaleza interna de un algoritmo dictó erróneamente la experiencia de usuario.  
2. **El Comité como caja negra:** Al llamar a `convocar_comite`, la ejecución en `pipeline.py` se aísla en una sesión anidada donde el usuario no ve nada. La negociación más rica (el Constructor proponiendo y el Validador vetando por riesgo) es muda hasta que aparece el JSON final del acta.  
3. **Punto único de falla conversacional:** Doce herramientas planas en un solo `LlmAgent` (el Director) generan confusión semántica (`estimar_mercado` vs `construir_candidatos` vs `diagnosticar_cartera`). Los errores de selección de tools crecen de forma superlineal.  
4. **La mesa de trabajo oculta:** Las hipótesis exploratorias viven en variables internas de ADK que solo se observan abriendo la pestaña de desarrollador en `adk web`. El usuario no tiene cómo pedir la "pizarra actual".  
5. **Erosión de la custodia semántica:** El flag `validado: false` vive en el tipo de dato, pero al ser narrado por el Director en lenguaje natural, pierde su advertencia y puede confundir al inversor.

---

## 2\. Principios de Diseño y Fundamentos No Negociables

Para solventar estos problemas sin debilitar las custodias, el rediseño adopta cinco principios rectores:

1. **Separación de Planos:** El sistema separa con rigor el **Plano Conversacional y Deliberativo** (donde los LLMs interpretan, dialogan y sintetizan) del **Plano Determinista** (donde algoritmos convexos, matrices y cálculos de riesgo corren en código puro).  
2. **Especialistas Delgados (*Thin Sub-Agents*):** Cada disciplina del Asset Management se expone como un sub-agente conversacional con personalidad técnica y voz propia, pero gobernando una única herramienta especializada.  
3. **Pizarra Compartida (*Shared Blackboard*):** Toda hipótesis, vista o diagnóstico exploratorio se registra en un artefacto estructurado que el usuario puede inspeccionar en cualquier momento.  
4. **Streaming de Hitos de Gobernanza:** El comité anidado mantiene su aislamiento computacional, pero emite señales de avance (*milestones*) en tiempo real a la sesión principal.  
5. **Pragmatismo de Inversión Real:** Las decisiones operativas se someten a filtros de fricción económica (spread FX USD/CLP, retención de dividendos, normas tributarias del SII en Chile y bandas de inercia *No-Trade Zones* en Fintual Acciones).

---

## 3\. Arquitectura del Target State: Las Capas del Sistema

&nbsp;

![][image1]

&nbsp;

flowchart TD

&nbsp;&nbsp;&nbsp;&nbsp;%% Estilos Globales

&nbsp;&nbsp;&nbsp;&nbsp;classDef humanClass fill:\#EBF5FB,stroke:\#2980B9,stroke-width:2px,color:\#1B4F72,font-weight:bold;

&nbsp;&nbsp;&nbsp;&nbsp;classDef dirClass fill:\#FEF9E7,stroke:\#F39C12,stroke-width:2px,color:\#7D6608,font-weight:bold;

&nbsp;&nbsp;&nbsp;&nbsp;classDef fintualClass fill:\#E8F8F5,stroke:\#1ABC9C,stroke-width:2px,color:\#0E6251;

&nbsp;&nbsp;&nbsp;&nbsp;classDef quantLabClass fill:\#F4ECF7,stroke:\#8E44AD,stroke-width:2px,color:\#512E5F;

&nbsp;&nbsp;&nbsp;&nbsp;classDef stateClass fill:\#EAEDED,stroke:\#7F8C8D,stroke-width:2px,color:\#2C3E50,stroke-dasharray: 5 5;

&nbsp;&nbsp;&nbsp;&nbsp;classDef actionClass fill:\#FDEDEC,stroke:\#E74C3C,stroke-width:2px,color:\#78281F,font-weight:bold;

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% CAPA 0: USUARIO

&nbsp;&nbsp;&nbsp;&nbsp;subgraph C0 \["CAPA 0: USUARIO / COMANDO"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;User\["👤 Usuario Humano (Lead PM / CIO)"\]:::humanClass

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% CAPA 1: DIRECTOR Y PIZARRA

&nbsp;&nbsp;&nbsp;&nbsp;subgraph C1 \["CAPA 1: ORQUESTACIÓN Y ESTADO (ADK)"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Director\["🎯 Lead CIO Orchestrator (agente.py)\<br/\>• Ruteo jerárquico a sub-agentes\<br/\>• Disclaimer visual para datos no validados"\]:::dirClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Pizarra\[("📋 Pizarra Mesa de Trabajo\<br/\>(SessionState / mesa\_trabajo.py)\<br/\>• Sello universe\_version\<br/\>• Inventario de Vistas y Diagnósticos")\]:::stateClass

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;User \<--\>|"Directivas / Vistas / Gate"| Director

&nbsp;&nbsp;&nbsp;&nbsp;Director \<--\>|"Lectura / Escritura"| Pizarra

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% CAPA 2A: OPERACIÓN REAL FINTUAL

&nbsp;&nbsp;&nbsp;&nbsp;subgraph C2A \["CAPA 2A: OPERACIÓN REAL (FINTUAL ACCIONES)"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;direction TB

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Data\["📊 Gestor de Datos & Fintual\<br/\>(Sub-Agente Thin)\<br/\>• Adj Close, splits y dividendos USD"\]:::fintualClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Quant\["📈 Estadístico / Quant Lead\<br/\>(Sub-Agente Thin)\<br/\>• Ledoit-Wolf Shrinkage & HRP"\]:::fintualClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Risk\["🛡️ Escéptico / Validador\<br/\>(Sub-Agente Thin)\<br/\>• Stress test y riesgo de colas"\]:::fintualClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Guard\["⚙️ Fintual Execution Guard\<br/\>• No-Trade Zones (±5%)\<br/\>• Cash-Flow Rebalancing (sin venta)\<br/\>• Órdenes fraccionadas en USD"\]:::fintualClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Data \--\>|"Precios limpios"| F\_Quant

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Quant \--\>|"Pesos teóricos"| F\_Risk

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;F\_Risk \--\>|"Cartera diagnosticada"| F\_Guard

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% CAPA 2B: QUANT I+D LAB

&nbsp;&nbsp;&nbsp;&nbsp;subgraph C2B \["CAPA 2B: QUANT I+D LAB (INSPIRADO EN EL LIBRO)"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;direction TB

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Reader\["📑 Investigador / Lector\<br/\>(Paper-to-Spec)\<br/\>• Salida: StrategySpec.json"\]:::quantLabClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_NLP\["🎙️ Señales NLP & Fed\<br/\>• Transcripción \+ clasificador de sentimiento locales (int8)\<br/\>• Salida: Sentiment\_Feature.parquet"\]:::quantLabClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Strat\["💻 Estratega / Backtester\<br/\>• Generador de código vectorbt\<br/\>• Salida: BacktestReport.json"\]:::quantLabClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Sim\["🧪 Simulador Generativo Profundo\<br/\>• VAEs, Normalizing Flows, WGAN-GP\<br/\>• 10k mundos sintéticos / estrés"\]:::quantLabClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Audit\["⚖️ Validador Adversario (DSR)\<br/\>• Deflated Sharpe Ratio\<br/\>• Falsación sobre datos sintéticos"\]:::quantLabClass

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Reader \--\>|"StrategySpec.json"| R\_Strat

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_NLP \--\>|"Features NLP"| R\_Strat

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Strat \--\>|"Estrategia candidata"| R\_Audit

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;R\_Sim \--\>|"Mundos contrafactuales"| R\_Audit

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% CONEXIONES DE CANALES

&nbsp;&nbsp;&nbsp;&nbsp;Director \--\>|"Canal A: Operación Real"| F\_Data

&nbsp;&nbsp;&nbsp;&nbsp;Director \--\>|"Canal B: Experimentos I+D"| R\_Reader

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% RESULTADOS FINALES

&nbsp;&nbsp;&nbsp;&nbsp;subgraph OUT \["SALIDAS Y EJECUCIÓN"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;AppFintual\["📱 App Fintual (Plan de Compra Neta)\<br/\>Ej: 'Comprar $65 en VB y $35 en BNS'"\]:::actionClass

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;LabReport\["🔬 Veredicto I+D / Archivo de Estrategias\<br/\>Aprobada (DSR \> umbral) o Rechazada"\]:::actionClass

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;F\_Guard \--\> AppFintual

&nbsp;&nbsp;&nbsp;&nbsp;R\_Audit \--\> LabReport

&nbsp;&nbsp;&nbsp;&nbsp;R\_Audit \-.-\>|"Si es Aprobada (Promoción a Señal)"| F\_Quant

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;%% MODO C: COMITÉ ANIDADO

&nbsp;&nbsp;&nbsp;&nbsp;subgraph C3 \["MODO C: CONVOCATORIA FORMAL (COMITÉ ANIDADO)"\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Comite\["🏛️ Pipeline Anidado (comite.py / pipeline.py)\<br/\>Constructor ⇄ Validador (Max N turnos)"\]:::dirClass

&nbsp;&nbsp;&nbsp;&nbsp;end

&nbsp;

&nbsp;&nbsp;&nbsp;&nbsp;Director \--\>|"solicitar\_comite (Orden Preparatoria)"| Comite

&nbsp;&nbsp;&nbsp;&nbsp;Comite \-.-\>|"Streaming de Hitos (pipeline\_milestones)"| Director

&nbsp;

---

## 4\. Especialistas como Sub-Agentes Delgados (Thin LlmAgents)

Para resolver la asimetría del diseño vigente sin inflar el costo de inferencia, los módulos matemáticos se envuelven en **sub-agentes delgados** (`mode="single_turn"` en ADK). Cada sub-agente tiene un rol estricto, una personalidad funcional y acceso a una sola herramienta determinista.

### 4.1 El Estadístico (Quant Lead)

* **Archivo:** `agents/estadistico/agente.py`  
* **Rol:** Riguroso, empírico, reacio a supuestos no comprobados. Explica matrices de covarianza, descomposiciones espectrales y estabilidad de factores.  
* **Herramienta Única:** `estimar_mercado` (invoca funciones en `quant/`).  
* **Comportamiento:** Si el usuario pregunta *"¿Por qué bajó la correlación entre BNS y VOOG?"*, el Director delega en el Estadístico, quien corre la estimación con Ledoit-Wolf y contesta en primera persona técnica con atribución clara.

### 4.2 El Escéptico (Risk & Validation Lead)

* **Archivo:** `agents/esceptico/agente.py`  
* **Rol:** Adversario institucionalizado. Su incentivo psicológico y de diseño es encontrar fallas, riesgos de cola y vulnerabilidades en las carteras propuestas.  
* **Herramienta Única:** `diagnosticar_cartera` (invoca funciones en `risk/`).  
* **Comportamiento:** Advierte si una posición en BNS está expuesta a un shock de crédito internacional o si la cartera sufre un Value-at-Risk (VaR) desproporcionado ante subidas de tasas.

### 4.3 El Gestor de Datos y Fintual (Execution & Corporate Actions)

* **Archivo:** `agents/fintual_data/agente.py`  
* **Rol:** Pragmático, enfocado en microestructura y costos de transacción reales.  
* **Herramienta Única:** `gestionar_datos_y_fricciones` (invoca `data_manager/`).  
* **Comportamiento:** Supervisa fechas ex-dividendo de activos extranjeros, custodia los precios de cierre ajustados y traduce las ponderaciones a dólares fraccionados para la aplicación.

### 4.4 El Analista de Mercado (Macro & Earnings)

* **Archivo:** `agents/analista/agente.py`  
* **Rol:** El agente vigente. Extrae tesis cualitativas y traduce noticias o discursos a la estructura `MarketViews`.

---

## 5\. La Pizarra de la Mesa de Trabajo (State Introspection)

Para eliminar la invisibilidad del estado exploratorio, se crea el contrato `MesaDeTrabajoState` y la herramienta de introspección para el Director:

\# contracts/mesa\_trabajo.py

from pydantic import BaseModel, Field

from typing import List, Dict, Any, Optional

&nbsp;

class ItemPizarra(BaseModel):

&nbsp;&nbsp;&nbsp;&nbsp;categoria: str \= Field(description="Universo, Vistas, Diagnóstico o Restricción")

&nbsp;&nbsp;&nbsp;&nbsp;contenido: str \= Field(description="Descripción legible del elemento en la mesa")

&nbsp;&nbsp;&nbsp;&nbsp;origen: str \= Field(description="Especialista que introdujo el elemento")

&nbsp;&nbsp;&nbsp;&nbsp;obsoleto: bool \= Field(default=False, description="True si quedó desactualizado por cambio de universo")

&nbsp;

class MesaDeTrabajoState(BaseModel):

&nbsp;&nbsp;&nbsp;&nbsp;universe\_version: str

&nbsp;&nbsp;&nbsp;&nbsp;items: List\[ItemPizarra\] \= Field(default\_factory=list)

&nbsp;&nbsp;&nbsp;&nbsp;ultimo\_diagnostico\_id: Optional\[str\] \= None

&nbsp;&nbsp;&nbsp;&nbsp;vistas\_activas\_hash: Optional\[str\] \= None

### Visualización al Usuario

Cuando el usuario pregunta *"¿Qué tenemos hasta ahora?"* o *"Muestra la mesa de trabajo"*, el Director no improvisa; consulta la herramienta `consultar_mesa_trabajo` y renderiza:

\#\#\# 📋 Mesa de Trabajo Actual (Universo: uv\_8f29d | VOOG, VB, BNS)

&nbsp;

| Categoría | Detalle | Especialista | Estado |

| :--- | :--- | :--- | :--- |

| \*\*Universo\*\* | \`\['VOOG', 'VB', 'BNS'\]\` fijado para Fintual | Gestor de Datos | Vigente |

| \*\*Vistas\*\* | Tesis alcista en Small-Caps (VB \> VOOG por 3%) | Analista de Mercado | Vigente |

| \*\*Estimación\*\* | Covarianza calculada vía Ledoit-Wolf Shrinkage | Estadístico | Vigente |

| \*\*Diagnóstico\*\*| VaR 95% \= 1.8% diario; CVaR 99% \= 3.2% | Escéptico | Vigente |

| \*\*Restricción\*\*| No-Trade Zone activa en ±5% | Fintual Guard | Vigente |

---

## 6\. Observabilidad del Comité y Streaming de Hitos

El flujo del Comité (`Modo C`) se refactoriza para resolver la caja negra sin vulnerar el aislamiento de la sesión anidada.

### 6.1 El Ceremonial de Convocatoria (Adiós al Token Vacío)

El gate de dos turnos se transforma en la formalización de la **Orden Preparatoria de Sesión**:

* **Turno 1 (Solicitud):** El Director llama a `solicitar_comite`. La herramienta lee el estado y devuelve un memorándum de convocatoria:  
  > *«Comité listo para sesionar. Parámetros fijados:*  
>   *• Universo: VOOG, VB, BNS (Sello: `uv_8f29d`)*  
>   *• Prior: Equilibrio neutral estimado por el Estadístico*  
>   *• Restricciones: Límite por emisor BNS \<= 20%, No-Trade Zones Fintual activas.*  
>   *¿Confirmas la convocatoria formal para iniciar la deliberación?»*  
* **Turno 2 (Ejecución):** Con la confirmación explícita del usuario, se valida el `invocation_id` blindado por test y se despacha el runner.

### 6.2 Streaming de Hitos hacia Arriba (`pipeline_milestones`)

Durante la ejecución de `pipeline.py`, el loop de deliberación entre el Constructor y el Validador escribe eventos en un buffer de estado compartido:

\# contracts/hitos\_comite.py

from pydantic import BaseModel

from datetime import datetime

&nbsp;

class HitoComite(BaseModel):

&nbsp;&nbsp;&nbsp;&nbsp;timestamp: datetime

&nbsp;&nbsp;&nbsp;&nbsp;fase: str \# "Analista", "Constructor", "Validador", "Reporter"

&nbsp;&nbsp;&nbsp;&nbsp;iteracion: int

&nbsp;&nbsp;&nbsp;&nbsp;evento: str

&nbsp;&nbsp;&nbsp;&nbsp;detalle: str

El Director reporta el avance paso a paso en la interfaz principal:

> 1. *«Analista y Estadístico: Vistas formalizadas y matriz de covarianza calculada.»*  
> 2. *«Constructor: Propuesta 1 generada (HRP ponderado: VOOG 62%, VB 22%, BNS 16%).»*  
> 3. *«Escéptico (Validador): VETO emitido. Motivo: Rotación requerida (42%) excede el límite de costos de Fintual.»*  
> 4. *«Constructor: Recalibrando con penalización de rotación L1...»*  
> 5. *«Escéptico: APROBADO. Candidato 2 cumple todas las restricciones de riesgo y gobernanza.»*  
> 6. *«Reporter: Acta final consolidada.»*

---

## 7\. Operación Pragmática en Fintual Acciones (Capa Real)

La Capa Operativa traduce la teoría cuantitativa a las restricciones de la corredora local Fintual en Chile:

\[Pesos Teóricos del Optimizador HRP / Black-Litterman\]

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▼

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;┌─────────────────────────────┐

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│   Fintual Execution Guard   │

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└──────────────┬──────────────┘

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│

&nbsp;&nbsp;├── 1\. Bandas de Inercia: ¿Desviación \> ±5%?

&nbsp;&nbsp;├── 2\. Aportes: ¿Hay flujo nuevo en USD?

&nbsp;&nbsp;├── 3\. Dividendos: ¿Caja disponible de BNS?

&nbsp;&nbsp;└── 4\. Impuestos: Evitar ventas con ganancia

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▼

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;\[Instrucción Pragmática en la App\]

&nbsp;&nbsp;"Aporte de $150 USD detectado: Comprar $105 en VB

&nbsp;&nbsp;&nbsp;y $45 en BNS. No vender VOOG para evitar impuestos."

### 7.1 Regla de Bandas de Tolerancia (*No-Trade Zones*)

* Si el peso objetivo de `VOOG` es $55%$, se define una banda admisible de $\[50%, 60%\]$.  
* Mientras el valor de mercado de `VOOG` oscile dentro de ese rango, el sistema tiene **estrictamente prohibido generar órdenes de rebalanceo**. Se eliminan costos de rotación y fricciones cambiarias.

### 7.2 Rebalanceo por Flujos de Caja (*Cash-Flow Rebalancing*)

* **Cero ventas:** Para corregir desviaciones, el sistema nunca vende activos ganadores (lo que gatillaría el Impuesto Global Complementario ante el SII en Chile).  
* **Distribución de Aportes:** Si el usuario ingresa nuevo capital mensual o se acreditan dividendos en USD de `BNS`, el `Fintual Execution Guard` destina el 100% de los fondos a los activos que quedaron por debajo de su ponderación objetivo.  
* **Acciones Fraccionadas:** Las compras se formulan en montos exactos en dólares (con 2 decimales), aprovechando la capacidad de compra fraccionada de Fintual.

---

## 8\. Laboratorio Cuantitativo de I+D & Modelos Generativos

La Capa de I+D está **desacoplada de la cuenta real** y permite explorar las técnicas avanzadas de la literatura financiera contemporánea.

┌────────────────────────────────────────────────────────────────────────────────────────┐

│                        FLUJO DE INVESTIGACIÓN EN EL QUANT LAB                          │

├────────────────────────────────────────────────────────────────────────────────────────┤

│ 1\. Investigador (Paper-to-Spec) ──► Genera StrategySpec.json (sin código)              │

│ 2\. Feature Store & NLP          ──► Publica features (NLP local de Nivel 2)            │

│ 3\. Estratega (vectorbt)         ──► Genera y corre backtest\_run.py                     │

│ 4\. Simulador (Deep Generative)  ──► Genera 10k mundos sintéticos (VAEs/Flows/WGAN)     │

│ 5\. Validador Adversario         ──► Aplica Deflated Sharpe Ratio (DSR) & Falsación     │

└────────────────────────────────────────────────────────────────────────────────────────┘

### 8.1 Ingesta de Literatura: Separación Spec $\\rightarrow$ Código

El Agente Investigador lee papers (arXiv, SSRN) o código legado (Matlab) y produce exclusivamente un documento declarativo:

{

&nbsp;&nbsp;"strategy\_name": "SmallCap\_Momentum\_Regime",

&nbsp;&nbsp;"universe": \["VOOG", "VB"\],

&nbsp;&nbsp;"signal\_logic": "Long VB when 12M Momentum \> VOOG and Fed Sentiment \> 0",

&nbsp;&nbsp;"rebalance\_frequency": "Monthly",

&nbsp;&nbsp;"cost\_assumptions\_bps": 15,

&nbsp;&nbsp;"risk\_limits": { "max\_drawdown\_limit": 0.25 }

}

*Ningún código se ejecuta hasta que la especificación es aprobada conceptualmente.*

### 8.2 Deep Generative Simulator: Falsación en Mundos Contrafactuales

El simulador genera trayectorias sintéticas que respetan los hechos estilizados del mercado (*stylized facts*):

* **Variational Autoencoders (VAEs) & Normalizing Flows (RealNVP):** Modelan densidades multivariadas exactas y capturan colas pesadas (*fat tails*).  
* **WGAN-GP para Series de Tiempo:** Modela dependencias no lineales y clustering de volatilidad.  
* **Objetivo de la simulación:** Someter la estrategia a 10.000 trayectorias sintéticas que nunca ocurrieron en la historia pero que son estadísticamente plausibles.

### 8.3 El Validador como Adversario

El Validador aplica el **Deflated Sharpe Ratio (DSR)** de López de Prado para penalizar la selección múltiple (*multiple testing bias*) y corre pruebas de ruido blanco. Si la estrategia no supera el estrés en los mundos sintéticos del simulador, es vetada y archivada en el registro de experimentos.

---

## 9\. Ruteo de Cómputo, Inferencia y Control de Costos

Para garantizar que el sistema sea económicamente sostenible y rápido, se establece una división estricta de motores de ejecución:

| Nivel de Inferencia | Tecnologías / Modelos | Asignación en el Sistema | Justificación Económica |
| :---- | :---- | :---- | :---- |
| **Nivel 1: LLM Frontier (Cloud)** | El que asigne `config.yaml: inferencia.nivel_1` (enmienda §4) | Director Orquestador, Lector de Papers (Spec), Estratega (Código) | Razonamiento abstracto complejo, síntesis ejecutiva y generación de código estricto. |
| **Nivel 2: Modelos Locales Cuantizados** | Transcriptor de audio y clasificador de sentimiento financiero cuantizados (int8 / GGUF); asignación en `config.yaml: inferencia.nivel_2` | Agente NLP de Señales Alternativas (Fed Speeches, Earnings Calls) | Procesa horas de audio y miles de textos por centavos en hardware local. |
| **Nivel 3: Motores Deterministas (Cero LLM)** | Python puro, NumPy, Polars, CVXPY, Riskfolio-Lib, vectorbt, PyTorch | Estadístico (`quant/`), Escéptico (`risk/`), Fintual Guard, Simuladores y Backtesters | Exactitud matemática estricta, cero alucinación y velocidad en milisegundos. |

---

## 10\. Árbol de Archivos y Especificación de Contratos

sistema\_adk/

├── agente.py                  \# Director adelgazado: ruteo jerárquico a sub-agentes

├── estado.py                  \# SessionState de ADK: mesa\_trabajo, hitos y contratos

├── comite.py                  \# Gate ceremonial y orquestación del pipeline anidado

├── pipeline.py                \# Pipeline de deliberación con emisión de hitos en vivo

├── nucleo.py                  \# FunctionTools limpias que conectan ADK con capas puras

│

├── agents/                    \# SUB-AGENTES THIN (LlmAgent de single-turn)

│   ├── analista/              \# Analista de Mercado (MarketViews)

│   ├── estadistico/           \# Quant Lead (estimar\_mercado)

│   ├── esceptico/             \# Validador de Riesgo (diagnosticar\_cartera)

│   ├── fintual\_data/          \# Gestor de Datos, FX y Dividendos

│   └── reporter/              \# Redactor del informe formal del acta

│

├── contracts/                 \# CONTRATOS PYDANTIC COMPARTIDOS

│   ├── mesa\_trabajo.py        \# Esquema de la Pizarra de trabajo viva

│   ├── hitos\_comite.py        \# Esquema de eventos y streaming de deliberación

│   ├── market\_views.py        \# Vistas de mercado estructuradas

│   ├── run\_state.py           \# Estado consolidado de ejecución de cartera

│   └── strategy\_spec.py       \# Especificación formal de estrategias de I+D

│

├── quant/                     \# CÓDIGO DETERMINISTA PURO (CERO ADK, CERO LLM)

│   ├── shrinkage.py           \# Ledoit-Wolf y filtrado RMT

│   ├── hrp.py                 \# Hierarchical Risk Parity y clustering

│   └── black\_litterman.py     \# Modelo Bayesiano de integración de vistas

│

├── risk/                      \# CÓDIGO DETERMINISTA PURO

│   ├── metrics.py             \# VaR, CVaR, Drawdown y análisis de colas

│   └── stress\_testing.py      \# Shocks paramétricos y pruebas históricas

│

├── fintual/                   \# GOBERNANZA OPERATIVA REAL

│   ├── no\_trade\_zones.py      \# Bandas de inercia de rebalanceo

│   ├── cash\_flow\_alloc.py     \# Asignación de aportes sin venta

│   └── tax\_filter.py          \# Estimación de fricción imponible SII

│

├── research\_lab/              \# LABORATORIO CUANTITATIVO DE I+D

│   ├── backtester.py          \# Motor vectorbt estandarizado

│   ├── generative\_sim.py      \# VAEs, Normalizing Flows y WGAN-GP en PyTorch

│   └── overfitting\_audit.py   \# Deflated Sharpe Ratio y White Noise Tests

│

└── tests/                     \# BATERÍA DE PRUEBAS Y CUSTODIAS

&nbsp;&nbsp;&nbsp;&nbsp;├── test\_fronteras.py      \# Garantiza que quant/risk/contracts no importen ADK

&nbsp;&nbsp;&nbsp;&nbsp;├── test\_director.py       \# Comprueba ruteo jerárquico a sub-agentes

&nbsp;&nbsp;&nbsp;&nbsp;├── test\_gate\_security.py  \# Fija la invariante del invocation\_id en el comité

&nbsp;&nbsp;&nbsp;&nbsp;└── test\_atribucion.py     \# Verifica que las cifras siempre nombren al especialista

---

## 11\. Plan de Implementación en Sprints

┌────────────────────────────────────────────────────────────────────────────────────────┐

│ SPRINT 1: VISIBILIDAD, PIZARRA Y ATRIBUCIÓN INMEDIATA                                  │

│ • Implementar contracts/mesa\_trabajo.py y la tool \`consultar\_mesa\_trabajo\`.           │

│ • Establecer atribución obligatoria en el Director ("El Estadístico estimó...").      │

│ • Inyectar prefijo visual automático de advertencia a cifras con \`validado: false\`.   │

│ • Escribir \`tests/test\_gate\_security.py\` para fijar por test el invocation\_id del gate.│

├────────────────────────────────────────────────────────────────────────────────────────┤

│ SPRINT 2: NIVELACIÓN DEL EQUIPO (SUB-AGENTES THIN)                                     │

│ • Construir \`agents/estadistico/\` y \`agents/esceptico/\` como LlmAgents de una tool.    │

│ • Desmontar las 12 tools planas del Director y reemplazar por ruteo a sub-agentes.    │

│ • Implementar \`fintual/no\_trade\_zones.py\` y el agente \`agents/fintual\_data/\`.          │

│ • Actualizar \`test\_director.py\` para verificar delegación de roles.                   │

├────────────────────────────────────────────────────────────────────────────────────────┤

│ SPRINT 3: OBSERVABILIDAD DEL COMITÉ & EXPERIENCIA FINTUAL INTEGRADA                    │

│ • Cablear \`pipeline.py\` para emitir hitos de deliberación a \`pipeline\_milestones\`.    │

│ • Hacer que el Director transmita los eventos del Comité en vivo en el chat.           │

│ • Implementar el calculador de aportes en USD fraccionados para Fintual.               │

│ • Unificar la experiencia en una sola interfaz eliminando la app pipeline separada.    │

├────────────────────────────────────────────────────────────────────────────────────────┤

│ SPRINT 4: MODALIDAD QUANT I+D LAB (AVANZADA)                                           │

│ • Crear \`contracts/strategy\_spec.py\` y el flujo Paper-to-Spec.                         │

│ • Integrar el motor de backtesting vectorbt estandarizado.                            │

│ • Conectar el validador con cálculo de Deflated Sharpe Ratio (DSR).                    │

│ • Integrar el simulador generativo (VAEs / Flows) para validación contrafactual.       │

└────────────────────────────────────────────────────────────────────────────────────────┘

---

## 12\. Matriz de Verificación y Testing

Cada avance se audita contra criterios de aceptación matemáticos y de software:

1. **Invariante de Fronteras (`pytest tests/test_fronteras.py`):**  
   * Pasa estrictamente. Ningún archivo en `quant/`, `risk/`, `fintual/` o `contracts/` contiene imports de `google.adk` o similares.  
2. **Invariante de Custodia de Gate (`pytest tests/test_gate_security.py`):**  
   * Comprueba que si se invoca la fase `ejecutar` sin un token emitido en el turno inmediatamente anterior con el mismo `invocation_id`, el sistema lanza una excepción controlada de violación de gate.  
3. **Auditabilidad de la Pizarra:**  
   * La ejecución de cualquier cambio de universo muta el sello `universe_version` y marca instantáneamente como `obsoleto: true` todas las estimaciones previas en la mesa de trabajo.  
4. **Verificación de Atribución (`pytest tests/test_atribucion.py`):**  
   * Un evaluador automático analiza las respuestas del Director y falla si se reporta una cifra numérica de retorno, riesgo o correlación sin explicitar si provino del Estadístico, del Escéptico o del Gestor de Datos.  
5. **Comportamiento Fintual No-Trade:**  
   * Si las desviaciones de peso de `{VOOG, VB, BNS}` están dentro del rango $\[-5%, \+5%\]$, la orden generada debe ser explícitamente `HOLD` con indicación de compra solo en caso de inyección de aportes.

&nbsp;

[image1]: <data:image/png;base64,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>