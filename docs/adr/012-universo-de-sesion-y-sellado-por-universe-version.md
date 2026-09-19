# ADR 012: Universo de sesión como contrato y sellado de resultados por `universe_version`

- Fecha: 2026-09-19
- Sprint: S7
- Estado: propuesta (cambio de contratos: requiere aprobación antes de implementar consumidores)

## Contexto
Hasta S6 el universo era `config.portafolio.activos`: cuatro strings que cada módulo leía por
su cuenta. El spec fuente del Director (S8) exige un universo que cambia en sesión ("agrega
X"), diagnósticos que el usuario ve antes de incorporar un activo y una regla de obsolescencia:
al cambiar el universo, los resultados previos dejan de valer. Una lista de strings no puede
llevar diagnósticos ni demostrar sobre qué universo se calculó un resultado.

## Decisión
1. **Contratos nuevos** (`contracts/universe.py`, `session.py`, `prior.py`):
   - `AssetDiagnostic`: ticker resuelto, nombre, moneda, inicio/fin de datos, frecuencia,
     huecos, meses disponibles, advertencias, `apto`, y el bloque de prior (ADR-013).
   - `Universe`: diagnósticos en orden canónico, origen por activo (`config_inicial |
     agregado_en_sesion`), `prior_neutral_aceptado` y `version` = SHA-256 del contenido
     canónico (incluye caps congeladas y la aceptación de neutral). Solo admite activos aptos.
     `version` viaja serializada y se revalida: un JSON manipulado no carga.
   - `SessionConstraints`: piso y techo generales y límites por activo, cada uno con su origen
     (`default_config | ajuste_usuario`), sellado con `universe_version`. Valida los dos
     chequeos de factibilidad que dependen solo de la sesión (piso×N ≤ 100 %, los techos
     alcanzan 100 %) con mensajes que dicen qué corregir.
   - `PriorSnapshot`: w_mkt, procedencia por activo y tabla π (ADR-013).
2. **Contratos modificados**:
   - `QuantEstimates`, `CandidatePortfolios`, `ValidationReport` ganan
     `universe_version: str | None`. `None` = "sin sellar": solo lo produce el núcleo puro
     llamado directamente (golden, sensibilidad); **las herramientas sellan siempre y rechazan
     todo input sin sello o con un sello distinto al del universo vigente**.
   - `CandidatePortfolios.no_disponibles: dict[Tecnica, motivo]`: BL con prior pendiente se
     declara aquí con su mensaje; el comité sigue con HRP y mínima varianza.
   - `ValidationReport.advertencias`: degradaciones por historia corta (qué ventana de
     backtest y qué stress aplican a cada activo); no cambian el veredicto, nunca se omiten.
   - `RunState` (se aplica en el hito 3, con sus consumidores): `universo: Universe`,
     `restricciones_sesion: SessionConstraints` y `prior: PriorSnapshot | None` (None solo si
     BL no estuvo disponible). Dentro de un `RunState` el sello es obligatorio: todo
     sub-contrato debe llevar `universe_version == universo.version`, y
     `activos == universo.activos`.
3. **Obsolescencia como invariante mecánico**, no como instrucción a un LLM: la comparación de
   sellos vive en `tools/` y en el validador de `RunState`.
4. `PortfolioConstraints` no cambia: es el formato del optimizador y el golden lo construye
   directamente. `SessionConstraints.a_portfolio_constraints()` lo produce.

## Alternativas descartadas
- **Versión = contador incremental**: no es reproducible entre sesiones ni detecta dos
  universos iguales construidos por caminos distintos. El hash sí.
- **`universe_version` obligatorio en todos los contratos**: obligaría a cambiar el golden test
  (que llama a `estimar` y a `optimizar_black_litterman` sin universo). El sello opcional en el
  contrato y obligatorio en herramientas y `RunState` da la misma garantía donde importa.
- **Excluir las advertencias/fechas de datos del hash**: refrescar precios cambia los números;
  un resultado calculado con la serie anterior debe quedar obsoleto.
- **Origen del activo dentro de `AssetDiagnostic`**: el diagnóstico es lo que devuelve
  `resolver(ticker)`, que no sabe cómo entró el activo a la sesión.

## Consecuencias
- Cambio de contrato → este ADR + todos los consumidores (tools, orquestador, reporter,
  replay, comparador) + tests, en el mismo PR (CLAUDE.md).
- Los `RunState` anteriores a S7 no validan contra el contrato nuevo; ya eran no repetibles
  por `config_hash` distinto (ADR-009).
- `SessionConstraints` no modela cortos (`Fraccion` ≥ 0): coincide con `permitir_cortos: false`;
  habilitarlos sería otro cambio de contrato.
- `config.portafolio.activos` pasa a ser la semilla del universo inicial, no "el universo".
