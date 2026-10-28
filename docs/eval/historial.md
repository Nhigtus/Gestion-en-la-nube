# Historial de evaluación de calidad

Cada fila la agrega el pipeline (`.github/workflows/ci.yml`) al correr en `main`.
El umbral mínimo es **8/10**: por debajo, el job falla y el PR queda en rojo.
El modo `offline` evalúa recuperación + guardarraíl (sin modelo) y el modo
`en-linea` evalúa el endpoint real de la EC2.

| Fecha (UTC) | Commit | Modo | Puntaje | Alucinaciones |
|---|---|---|---|---|
| 2026-10-28T18:59:26+00:00 | `c6fbc90` | offline | 10/10 | 0 |
| 2026-10-28T19:05:37+00:00 | `0d0faa1` | offline | 10/10 | 0 |
