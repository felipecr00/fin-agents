# ADR 003: Núcleo cuantitativo propio sobre numpy/scipy (vs PyPortfolioOpt / riskfolio-lib)

- Fecha: 2026-09-16
- Sprint: S1
- Estado: aceptada

## Contexto
S1 debe implementar covarianza histórica con ventana común para IBIT, Ledoit-Wolf,
Black-Litterman (prior por capitalización, Ω He-Litterman, utilidad cuadrática con
límites), HRP y mínima varianza, todo en módulos puros sin ADK ni LLM, con
reproducibilidad exacta y el golden test como árbitro (pesos ≈ 70/7/2/21 ±2 p.p.).
CLAUDE.md pide decidir entre PyPortfolioOpt, riskfolio-lib o implementación propia.

Se evaluaron las tres opciones sobre el ejercicio de referencia
(`docs/referencia_black_litterman.py`, que reproduce 70.0/7.1/2.0/20.9 con
`data/precios.csv`) en entornos aislados con el stack del repo (Python 3.11,
numpy 2.4.6, pandas 3.0.5, scipy 1.17.1):

| Criterio | PyPortfolioOpt 1.6.0 (feb-2026) | riskfolio-lib 7.3.0 (may-2026) | Propia (numpy/scipy) |
|---|---|---|---|
| Reproduce el oráculo | Sí, **solo** si se le inyecta la Σ híbrida y π en exceso calculados fuera de la librería (70.0/7.06/2.0/20.94; μ posterior y métricas idénticas a 4 decimales) | No: `blacklitterman_stats` recalcula Σ y π sobre retornos por período alineados (descarta 28 obs. de VOOG/BNS/VB); μ posterior 6.5 % vs 11.9 % esperado; con cota inferior 2 % el solver declara infactible | Sí por construcción: el golden test codifica exactamente la referencia |
| Covarianza híbrida (vol. de muestra larga + correlaciones de ventana común para IBIT) | No existe. `sample_cov` usa la covarianza *pairwise* de pandas: corr VOOG-IBIT 0.414 vs 0.491 de la referencia; matriz sin garantía de ser PSD | No existe; exige panel completo | Hay que escribirla de todos modos |
| Ledoit-Wolf con serie corta | Acepta NaN pero calcula sobre pairwise sin avisar | Panel completo obligatorio | Implementación explícita y documentada (ver Decisión) |
| Dependencias nuevas | cvxpy (+osqp, clarabel, scs, highspy…), scikit-learn, scikit-base | 15 directas: cvxpy, scikit-learn, statsmodels, arch, astropy, vectorbt, numba, matplotlib, xlsxwriter, networkx… | Ninguna |
| Estado del empaquetado | **La 1.6.0 no importa**: `skbase` requiere `packaging` y no lo declara (`ModuleNotFoundError`); hay que parchear el entorno | Importa; primer import 94 s (caché de fuentes de matplotlib), después 2.4 s | n/a |
| Números ocultos | `market_implied_prior_returns` suma `risk_free_rate=0.02` por defecto; `BlackLittermanModel` acepta `pi="market"` con ese rf | `l` (aversión) y `rf` con semántica distinta a la referencia (utilidad sin ½) | Todo parámetro viene de `config.yaml` |
| Reproducibilidad / auditoría | Solver cvxpy con tolerancias propias; el resultado depende de la versión del solver que resuelva el QP | Ídem, más capas | scipy SLSQP con punto inicial fijo; semilla no necesaria (todo determinista) |
| Tipado (mypy strict) | Sin stubs; `ignore_missing_imports` | Sin stubs | Tipado propio completo |

## Decisión
Implementar el núcleo cuantitativo en código propio sobre numpy/scipy, sin añadir
dependencias. PyPortfolioOpt se usó **una sola vez, fuera del repo**, para extraer
valores oráculo (HRP, mínima varianza y Ledoit-Wolf sobre los mismos inputs) que quedan
codificados en los tests unitarios de `portfolio/` y `quant/` con la versión citada,
igual que el golden test codifica el ejercicio de referencia (ADR-002). Así la
implementación propia se contrasta con una segunda implementación independiente sin
arrastrarla como dependencia.

Diseño concreto (todo en `quant/` y `portfolio/`, firmas de los stubs de S0):

1. **Covarianza histórica** (`estimar_covarianza`, `historica`): sobre las últimas
   `ventana_meses` observaciones. Volatilidad de cada activo con su propia muestra
   (ddof=1); correlación de cada par sobre la ventana común del par. Σ = D·ρ·D,
   anualizada ×`periodos_por_anio` (varianza). `observaciones_por_activo` registra la
   muestra efectiva (60/60/32/60). Reproduce la referencia exactamente.
2. **Ledoit-Wolf** (`ledoit_wolf`): contracción hacia el objetivo de **correlación
   constante** (Ledoit & Wolf 2003, el que preserva las varianzas heterogéneas de un
   universo con IBIT al 51 % y VB al 19 %). La intensidad δ* se estima sobre la ventana
   común de todos los activos (panel completo, único lugar donde la fórmula está
   definida) y se aplica a la matriz híbrida del punto 1. Con panel completo coincide
   con la implementación de PyPortfolioOpt (oráculo en test).
3. **Black-Litterman** (`optimizar_black_litterman`): π = δ·Σ·w_mkt (en exceso de rf);
   Q en exceso para views absolutas y tal cual para relativas; Ω He-Litterman
   (`diag(P·τΣ·Pᵀ)`) o Idzorek según `metodo_omega`; μ_BL y Σ_BL = Σ + M; utilidad
   cuadrática con δ, límites de `PortfolioConstraints` y Σw = 1 resuelta con
   `scipy.optimize.minimize(method="SLSQP")` desde un punto inicial determinista
   (equiponderado proyectado a los límites). Métricas ex ante con Σ (no Σ_BL), como la
   referencia. `idzorek` queda como método reconocido pero se implementa cuando un
   sprint lo necesite (hoy lanza `NotImplementedError` con mensaje claro).
4. **HRP** (`optimizar_hrp`): López de Prado (2016): distancia
   √(½(1−ρ)), enlace simple (`scipy.cluster.hierarchy`), cuasi-diagonalización y
   bisección recursiva con varianza inversa. HRP no admite límites por naturaleza; si el
   resultado los viola se proyecta al conjunto factible minimizando ‖w − w_HRP‖² con
   SLSQP y se registra `parametros["proyectado"]=True`.
5. **Mínima varianza** (`optimizar_min_varianza`): min wᵀΣw con límites y Σw = 1,
   SLSQP, mismo punto inicial determinista.
6. `estimar` construye `QuantEstimates` con las covarianzas pedidas, retornos históricos
   anualizados con intervalo t de Student (`nivel_confianza` nuevo en `config.yaml`) y
   régimen `INDETERMINADO` (la detección de régimen queda para S2/S5).

## Alternativas descartadas
- **PyPortfolioOpt como motor.** Reproduce el ejercicio, pero solo con la covarianza y
  el prior calculados fuera de ella; es decir, aporta únicamente la fórmula de BL (10
  líneas de álgebra) y un QP vía cvxpy, a cambio de una dependencia que hoy no importa
  sin parche, sin stubs, con rf oculto por defecto y con solver externo que fija la
  reproducibilidad a su versión.
- **riskfolio-lib como motor.** No reproduce la referencia con su API (recalcula Σ y π
  sobre el panel alineado, pierde la muestra larga), su optimización con cota inferior
  falla, y arrastra 15 dependencias ajenas al problema (astropy, vectorbt, arch,
  matplotlib…). Su fuerte (decenas de medidas de riesgo, modelos de factores) no está en
  el alcance de S1 ni de los sprints siguientes.
- **Ledoit-Wolf hacia identidad escalada (2004) o pairwise sobre NaN.** La identidad
  escalada iguala varianzas de activos con vol 19 %–51 %; el pairwise produce matrices
  no PSD sin aviso. Se prefiere correlación constante con δ* sobre la ventana común.
- **PyPortfolioOpt como dependencia de desarrollo solo para tests.** Metería cvxpy y el
  fallo de import en CI; los oráculos fijos cumplen la misma función (ADR-002).

## Consecuencias
- Cero dependencias nuevas; `mypy --strict` cubre todo el núcleo; los tests corren en
  décimas de segundo y sin solver externo.
- Se asume el mantenimiento de ~300 líneas de álgebra financiera. Mitigación: cada
  optimizador tiene oráculo externo en test y el golden test arbitra BL.
- Si un sprint futuro necesita medidas de riesgo más allá de varianza (CVaR, CDaR) o
  restricciones lineales generales, se reevalúa PyPortfolioOpt/cvxpy en un ADR nuevo;
  la frontera `portfolio/` → `CandidatePortfolio` hace el reemplazo local.
- `config.yaml` gana `estimacion.nivel_confianza` (pendiente de S0) y no cambia ningún
  contrato de `contracts/`.
- La intensidad de Ledoit-Wolf sobre la ventana común (32 obs.) es más ruidosa que
  sobre 60; queda documentado y cubierto por test de propiedades (δ* ∈ [0, 1], PSD,
  varianzas preservadas).
