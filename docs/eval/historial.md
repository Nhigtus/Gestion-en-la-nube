# Historial de evaluación de calidad

Cada fila la agrega el pipeline (`.github/workflows/ci.yml`) al correr en `main`.
El umbral mínimo es **8/10**: por debajo, el job falla y el PR queda en rojo.
El modo `offline` evalúa recuperación + guardarraíl (sin modelo) y el modo
`en-linea` evalúa el endpoint real de la EC2.

| Fecha (UTC) | Commit | Modo | Puntaje | Alucinaciones |
|---|---|---|---|---|
