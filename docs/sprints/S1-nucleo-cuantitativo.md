# Sprint 1 — Núcleo cuantitativo (determinista)

## Objetivo
Implementar la matemática del sistema como código puro y hacer pasar el golden test.

## Alcance
- `quant/`: covarianza histórica con ventana configurable + Ledoit-Wolf; manejo de la
  ventana común para IBIT (serie corta); anualización consistente.
- `portfolio/`: Black-Litterman (prior de equilibrio por capitalización, posterior con
  views, optimización con límites de config.yaml), HRP y mínima varianza global.
- ADR: elección PyPortfolioOpt vs riskfolio-lib vs implementación propia.

## Fuera de alcance
LLMs, ADK, backtest, régimen de mercado (va en S2 si el tiempo alcanza, o S5).

## Definition of Done
- Golden test en verde con tolerancia ±2 p.p. (pesos ≈ 70/7/2/21).
- Tests unitarios por estimador y optimizador; cero llamadas a modelos.
- `make check` verde; PR mergeado.

## Estado
Cerrado el 2026-09-16 (rama `sprint/S1-nucleo-cuantitativo`, PR contra `main`).

### Logrado
- ADR-003: núcleo propio sobre numpy/scipy. Se evaluaron PyPortfolioOpt 1.6.0 y
  riskfolio-lib 7.3.0 en entornos aislados: ninguna tiene la covarianza híbrida, la
  primera no importa sin parchear (`packaging` sin declarar) y la segunda no reproduce
  la referencia. Cero dependencias nuevas; `uv.lock` intacto.
- `quant/covariance.py`: histórica híbrida (vol por activo con su muestra, correlación
  por par en ventana común; 60/60/32/60 obs.) y Ledoit-Wolf hacia correlación constante
  (2003) con δ* sobre la ventana común aplicada a la matriz híbrida. Reproduce las vols y
  correlaciones de la referencia a 4 decimales.
- `quant/estimates.py`: `estimar` construye `QuantEstimates` con covarianzas por método,
  retornos históricos anualizados con intervalo t de Student
  (`config.yaml: estimacion.nivel_confianza`, pendiente de S0) y guarda explícita de
  look-ahead (`LookAheadError` antes de calcular nada). Régimen `INDETERMINADO`.
- `portfolio/`: Black-Litterman (π por capitalización, Q en exceso solo en absolutas, Ω
  He-Litterman, Σ_BL = Σ + M, utilidad cuadrática con SLSQP y punto inicial
  determinista), HRP (López de Prado, enlace simple, proyección al conjunto factible si
  viola límites) y mínima varianza. `_comun.py` concentra QP, proyección y métricas.
- Golden test en verde sin `xfail`: pesos 70.0/7.07/2.0/20.94, posterior y métricas
  idénticos a la referencia a 4 decimales.
- Oráculos externos codificados en tests (PyPortfolioOpt 1.6.0, calculados fuera del
  repo): HRP y mínima varianza coinciden a 1e-7; δ* de Ledoit-Wolf coincide con la
  fórmula canónica (0.7244; PyPortfolioOpt da 0.6798 por mezclar ddof=1 con 1/T).
- `make check` verde: 137 tests (52 nuevos), ruff y mypy strict sin avisos.

### Pendiente
- `metodo_omega=idzorek` lanza `NotImplementedError`; se implementa cuando un sprint
  necesite usar `View.confianza`.
- Detección de régimen de mercado (`RegimenMercado`): S2 si alcanza el tiempo, si no S5.
- `Sensibilidad` de los candidatos (perturbación de τ, δ, views) queda vacía: S5.
- `CandidatePortfolios` (el contenedor con `recomendado`) lo arma el Constructor en S3 a
  partir de los tres candidatos.

### Aprendizajes
- Contrastar contra librerías externas ANTES de decidir vale la pena: la evaluación tomó
  minutos y evitó adoptar una dependencia que ni siquiera importaba.
- Las mezclas de convenciones (ddof=1 vs 1/T, rf sumado por defecto, `l` sin ½) son la
  fuente típica de discrepancias entre implementaciones "equivalentes". Cada test de
  oráculo documenta la convención usada.
- Con pandas 3.0 y numpy 2.4, `DatetimeIndex.__getitem__` ya tipa como `Timestamp`
  (sin `cast`), y `scipy-stubs` exige `LinearConstraint` en lugar de dicts para
  `minimize` bajo mypy strict.
- Los tests "por propiedades" necesitan datos sintéticos cuya estructura verdadera
  difiera del objetivo de contracción; con correlación constante verdadera δ* no baja
  con más datos (y es correcto que no baje).
