# Sprint 2 — Validación y riesgo (adversarial)

## Objetivo
Construir el agente que intenta romper las carteras y tiene poder de veto.

## Alcance
- `risk/`: backtest walk-forward con rebalanceo y costos de config.yaml (los costos se
  aplican en CADA rebalanceo); métricas Sharpe OOS, max drawdown, turnover, concentración.
- Stress tests históricos: 2022 (tasas) y 2025-26 (corrección cripto). El escenario
  2020 (covid) queda fuera: `data/precios.csv` comienza en septiembre de 2021.
- Veredicto APROBADA/RECHAZADA contra umbrales de config.yaml, con razones.
- Verificación explícita de look-ahead bias.

## Definition of Done
- Test que inyecta look-ahead bias a propósito y demuestra que se detecta.
- Test donde una cartera diseñada para violar umbrales es rechazada con razones correctas.
- `make check` verde; PR mergeado.

## Estado
En curso (rama `sprint/S2-validacion-riesgo`).

### Decisiones de alcance
- Los stress tests cubren 2022 (ciclo de tasas) y la corrección cripto 2025-26. No hay
  escenario 2020: los datos empiezan en 2021-09.

### Limitaciones conocidas
- El backtest walk-forward opera sobre ~60 observaciones mensuales (2021-10 a 2026-09).
  Con esa muestra las métricas OOS tienen alta varianza: el Sharpe OOS y el max drawdown
  son indicativos, no estadísticamente concluyentes. IBIT solo aporta 32 observaciones.
