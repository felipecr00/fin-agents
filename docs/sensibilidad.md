# Sensibilidad de la cartera a sus supuestos (S5)

> Herramienta de análisis. Ninguna salida constituye asesoría financiera.

**Pregunta**: si nuestras estimaciones están algo equivocadas, ¿cuánto cambia la cartera que
recomienda Black-Litterman, y a cuál de los supuestos es más frágil?

**Respuesta corta** (portafolio de referencia, datos hasta 2026-09-30): a los **retornos
esperados**. Un error de ±1-2 p.p. en un retorno esperado mueve la cartera más que un error de
±10-20 % en volatilidades o correlaciones. Y la mitad de la cartera (VOOG 70 %, IBIT 2 %) no la
deciden las estimaciones sino los límites de peso.

## Cómo reproducirlo

```bash
make sensibilidad
```

```bash
make sensibilidad RUN_STATE=runs/<run_id>/run_state.json
```

El primero usa las views del ejercicio de referencia; el segundo, las de una corrida real.
Escribe `runs/sensibilidad/<fecha>_<hash de config>/informe.md` y `sensibilidad.json` (cada
perturbación en el contrato `Sensibilidad`). No usa agentes ni LLM, y es determinista: misma
entrada, mismo directorio y mismo contenido (verificado por hash). El código vive en
`risk/sensibilidad.py` (análisis) y `risk/informe_sensibilidad.py` (formato); la rejilla, en
`config.yaml: sensibilidad`.

## Qué se perturba

Un supuesto a la vez, con signo + y −, y se reoptimiza con el mismo código del golden test:

| Supuesto | Familia | Perturbación | Magnitudes |
|---|---|---|---|
| Retornos esperados | `views_q` | `q_anual` de cada view | ±1 y ±2 p.p. |
| Retornos esperados | `mu_posterior` | μ posterior de cada activo, con Σ_BL fija | ±1 y ±2 p.p. |
| Covarianzas | `volatilidad` | σ de cada activo (correlaciones fijas) | ±10 y ±20 % |
| Covarianzas | `correlacion` | ρ de cada par (volatilidades fijas) | ±10 y ±20 % |
| Covarianzas | `covarianza_global` | toda Σ | ±10 y ±20 % |
| Parámetros | `parametros` | δ (aversión al riesgo) y τ | ±10 y ±20 % |

Son 80 reoptimizaciones. Las de Σ se propagan por todo el modelo (prior π = δΣw, Ω, posterior y
término de riesgo), que es lo que ocurriría si la estimación de Σ fuera otra. Las dos familias
de retornos responden preguntas distintas: `views_q` es "¿y si el analista se equivoca en su
número?" (Black-Litterman amortigua ese error mezclándolo con el prior); `mu_posterior` es el
experimento clásico de media-varianza, "¿y si el retorno que entra al optimizador está mal?".

**Medidas.** *Cambio máx.*: el mayor cambio absoluto de un peso frente a la cartera base, en
p.p. (el mismo `cambio_max_pp` del contrato). *Desplazamiento medio*: su promedio sobre las
perturbaciones de una familia o de un supuesto; es lo que ordena el ranking, porque el máximo
crece con el número de perturbaciones de la familia y el promedio no. *Rotación*: ½·Σ|Δw|.

Todo se corre dos veces: con los **límites reales** (2 %-70 %) y con **límites relajados**
(0 %-100 %), para ver qué parte de la estabilidad es del modelo y cuál es del tope.

## Resultados (referencia, 2026-09-30, `config_hash` 24522e5c)

Cartera base con límites reales: VOOG 70,0 / BNS 7,1 / IBIT 2,0 / VB 20,9 (la del golden test).

| Supuesto | Límites reales | Límites relajados |
|---|---|---|
| Retornos esperados | **5,85 p.p.** | **8,06 p.p.** |
| Covarianzas | 3,40 p.p. | 3,46 p.p. |
| Parámetros del modelo | 2,24 p.p. | 1,30 p.p. |

Por familia, con límites reales:

| Familia | Medio (p.p.) | Peor (p.p.) | Peor caso |
|---|---|---|---|
| `mu_posterior` | 8,03 | 22,07 | μ de VB +2 p.p. → VB pasa de 20,9 % a 43,0 % |
| `volatilidad` | 5,14 | 15,60 | σ de BNS −20 % → BNS sube a 22,7 %, VB cae a 5,3 % |
| `covarianza_global` | 4,40 | 7,11 | Σ −20 % |
| `views_q` | 2,95 | 7,18 | view de BNS +2 p.p. |
| `parametros` | 2,24 | 7,11 | δ −20 % |
| `correlacion` | 2,08 | 5,06 | ρ(BNS, VB) +20 % |

Rango de cada peso sobre las 80 perturbaciones (límites reales): VOOG 51,7-70,0 %; BNS
2,0-26,0 %; IBIT 2,0-2,0 %; VB 2,0-43,0 %.

## Cómo leerlo

1. **El supuesto frágil son los retornos esperados.** Un solo punto porcentual de error en el
   μ de VB o de BNS mueve 17,5 p.p. de cartera; las seis perturbaciones que más mueven la
   cartera son todas de `mu_posterior`. El resultado coincide en dirección con la literatura
   clásica de media-varianza (Chopra y Ziemba, 1993: los errores en medias pesan mucho más que
   los de varianzas, y estos más que los de covarianzas); aquí el orden es el mismo:
   retornos > volatilidades > correlaciones.
2. **Por qué**: el posterior deja a los cuatro activos con retornos esperados muy parecidos
   (VOOG 11,9 %, BNS 10,2 %, IBIT 11,1 %, VB 9,5 %) y BNS y VB están muy correlacionados
   (0,78): para el optimizador son casi sustitutos, así que una diferencia mínima de retorno
   decide cuál se lleva el 28 % que dejan libre VOOG e IBIT.
3. **±2 p.p. es una rejilla optimista.** El intervalo de confianza al 95 % del retorno
   histórico anual que calcula `quant.estimar` es de ±17 p.p. para VOOG y VB, ±21 p.p. para BNS
   y ±64 p.p. para IBIT. Nadie conoce un retorno esperado con 2 p.p. de precisión.
4. **Black-Litterman sí amortigua el error del analista**: mover el `q` de una view ±2 p.p.
   desplaza la cartera 2,95 p.p. de media, casi tres veces menos que el mismo error aplicado
   directamente a μ. Es la razón para usar BL y no media-varianza con retornos históricos.
5. **Los límites sostienen media cartera.** Con límites reales VOOG está en su máximo e IBIT en
   su mínimo: ninguna de las 80 perturbaciones mueve IBIT y solo tres bajan a VOOG de 70 %. Sin
   límites el óptimo sería 98 % VOOG. La estabilidad de esos dos pesos es del tope, no del
   modelo; toda la fragilidad se concentra en el reparto BNS/VB.
6. **Correlaciones, δ y τ importan poco** en este universo (≈ 2 p.p.): no es donde conviene
   gastar esfuerzo de estimación.
7. Con las views de una corrida real (`20260917T223633_172451Z`) la conclusión es la misma y
   más marcada: retornos 10,6 p.p., covarianzas 5,6, parámetros 2,2.

## Qué implica para el sistema

- La tolerancia del golden test (±2 p.p. en pesos) es una prueba de regresión del código, no
  una medida de precisión de la cartera: el reparto BNS/VB tiene una incertidumbre real de
  decenas de puntos.
- Lo que más valor aporta es la calidad de las views (S5, hito 1: evalsets del analista) y no
  refinar la covarianza. Ledoit-Wolf frente a la histórica cambia volatilidades y correlaciones
  en magnitudes que este análisis muestra como de segundo orden.
- Un informe para el usuario debería presentar el reparto BNS/VB como un rango, no como una
  cifra. `Perturbacion.a_contrato()` ya produce `Sensibilidad`, el campo de `CandidatePortfolio`
  que quedó vacío en S1; poblarlo en `construir_candidatos` queda pendiente.

## Limitaciones

- Una perturbación a la vez: no mide errores simultáneos ni correlacionados entre supuestos.
- Las magnitudes de retornos (p.p. absolutos) y de covarianzas (% relativos) no son la misma
  unidad; la comparación es "bajo errores que se consideran plausibles", y esos rangos son un
  juicio que vive en `config.yaml`.
- Mide desplazamiento de pesos, no pérdida de utilidad ni de retorno realizado: dos carteras
  muy distintas entre casi sustitutos pueden rendir parecido.
- Una perturbación de correlación que deje Σ sin ser definida positiva se omite y se lista en
  el informe (no ocurre con la rejilla actual).
