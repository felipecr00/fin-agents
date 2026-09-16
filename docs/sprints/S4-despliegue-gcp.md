# Sprint 4 — Despliegue GCP

## Objetivo
Dev en Cloud Run, prod en Vertex AI Agent Engine, despliegue automatizado desde GitHub.

## Prerrequisitos
Proyecto GCP con facturación activa, APIs de Vertex AI habilitadas, Artifact Registry.

## Alcance
- Contenedor del servicio; despliegue a Cloud Run (entorno dev).
- Despliegue a Vertex AI Agent Engine con sesiones administradas (prod).
- `.github/workflows/deploy.yaml`: en merge a main despliega a dev; promoción a prod
  manual (workflow_dispatch). Autenticación con Workload Identity Federation — ninguna
  llave de servicio en el repo. Secretos en Secret Manager.
- Verificar la guía vigente de despliegue de ADK antes de codificar.

## Definition of Done
- Merge a main → dev desplegado automáticamente.
- Una corrida remota reproduce el resultado local (mismos datos, misma semilla).
- Documento breve de operación en docs/ (cómo desplegar, cómo ver logs, costos aprox).

## Estado
(pendiente)
