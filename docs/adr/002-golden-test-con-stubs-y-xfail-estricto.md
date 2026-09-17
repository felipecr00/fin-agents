# ADR 002: Golden test escrito en S0 sobre stubs que lanzan NotImplementedError

- Fecha: 2026-09-16
- Sprint: S0
- Estado: aceptada

## Contexto
El golden test (`tests/golden/test_black_litterman.py`) es el árbitro del núcleo
cuantitativo, pero la implementación llega en S1. Hay que dejarlo escrito completo,
que CI siga verde, y que falle por la razón correcta (no por imports) cuando se
implemente mal.

## Decisión
- `quant/` y `portfolio/` exponen ya la API que S1 implementará (`estimar_covarianza`,
  `estimar`, `optimizar_black_litterman`) como stubs que lanzan `NotImplementedError`;
  sus docstrings fijan el contrato numérico del ejercicio de referencia.
- Cada test golden lleva `xfail(raises=NotImplementedError, strict=True)`. Con
  `xfail_strict`, la suite falla si el test pasa (S1 debe retirar el marcador) y también
  si falla por otra excepción (un `ImportError` o un error de tipo no se disfraza).
- Los parámetros del ejercicio que no estaban en `config.yaml` (capitalizaciones del prior,
  método de Ω y de covarianza) se añadieron allí. Los valores esperados (pesos, vols,
  correlaciones, posterior) viven en el test como oráculo, no como parámetros.
- Se añadió `investmentsys/config.py`: carga tipada de `config.yaml` con `extra="forbid"`
  y `hash_config()` para `RunState.config_hash`.

## Alternativas descartadas
- **`pytest.skip` hasta S1.** No verifica que el test importe ni que falle por la razón
  esperada; se olvida con facilidad.
- **No crear stubs y dejar el test con imports rotos.** CI en rojo durante S0 y la API de
  S1 sin acordar.
- **Leer `config.yaml` con `yaml.safe_load` a un dict.** Sin tipos ni detección de claves
  mal escritas; cada consumidor repetiría las comprobaciones.

## Consecuencias
- S1 debe implementar exactamente la firma de los stubs o cambiarla junto con el test.
- Al pasar el golden test, S1 retira `pendiente_s1` de los tres tests marcados.
- `config.yaml` tiene tres claves nuevas (`metodo_covarianza`, `metodo_omega`,
  `prior_equilibrio`) documentadas en el archivo.
