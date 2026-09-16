# Sprint 2 — Validación y riesgo (adversarial)

## Objetivo
Construir el agente que intenta romper las carteras y tiene poder de veto.

## Alcance
- `risk/`: backtest walk-forward con rebalanceo y costos de config.yaml; métricas
  Sharpe OOS, max drawdown, turnover, concentración.
- Stress tests históricos: 2020 (covid), 2022 (tasas), 2025-26 (corrección cripto).
- Veredicto APROBADA/RECHAZADA contra umbrales de config.yaml, con razones.
- Verificación explícita de look-ahead bias.

## Definition of Done
- Test que inyecta look-ahead bias a propósito y demuestra que se detecta.
- Test donde una cartera diseñada para violar umbrales es rechazada con razones correctas.
- `make check` verde; PR mergeado.

## Estado
(pendiente)
