# Costos (FinOps)

**Presupuesto objetivo del enunciado:** USD 10/mes · **Escenario base:** 10 000 consultas/mes, ~1 500 tokens de entrada y 300 de salida por consulta (pregunta + 6 FAQ de contexto + historial corto).
**Región de referencia:** `us-east-1`, precios públicos on-demand (octubre 2026). En AWS Academy se descuenta del crédito del laboratorio, no de una tarjeta.

## Estimado

| Concepto | Supuesto | Estimado (USD/mes) | Real (USD/mes) | Diferencia y causa |
|---|---|---|---|---|
| API Gateway (HTTP API) | 10 000 req × USD 1,00/M | 0,01 | — | |
| Lambda | 10 000 inv × 1 s × 512 MB (free tier 400 000 GB-s) | 0,00 | — | |
| DynamoDB on-demand | 10 000 lecturas + 20 000 escrituras + 1 GB | 0,03 | — | |
| Bedrock Nova Micro | 15 M tokens entrada × 0,035/M + 3 M salida × 0,14/M | 0,95 | — | |
| CloudWatch Logs | 1 GB ingerido + 1 mes de retención | 0,50 | — | |
| S3 (frontend) | 100 MB + 10 000 GET | 0,01 | — | |
| CloudFront | 1 GB transferido (free tier 1 TB) | 0,00 | — | |
| **Total sin EC2** | | **≈ 1,50** | | |
| EC2 t3.micro (sólo hito 6–7) | 8 h/día × 30 días = 240 h × 0,0104 | 2,50 | — | |
| EBS gp3 de la EC2 | 8 GB × 0,08/GB | 0,64 | — | |
| **Total con EC2 encendida 8 h/día** | | **≈ 4,64** | | |
| **Total con EC2 24/7 (anti-patrón)** | 730 h | ≈ 12,2 | | **Supera el objetivo: por eso la arquitectura final es serverless** |

## Costo por consulta

Con el escenario base: **USD 0,00015 por consulta** (≈ 0,15 milésimas de dólar). Una consulta con Claude Haiku en vez de Nova Micro cuesta ~20× más (≈ USD 0,003), todavía dentro del presupuesto si el volumen es de miles y no de millones.

## Optimizaciones aplicadas

1. **Serverless en lugar de EC2 24/7**: elimina el costo fijo de instancia; sólo se paga por invocación.
2. **Contexto acotado**: 6 FAQ (~1 500 tokens) en vez de la base completa; `maxTokens` 400 evita respuestas largas.
3. **Sin embeddings ni vector DB**: el ranking TF-IDF corre dentro de la Lambda a costo cero.
4. **DynamoDB on-demand + TTL 30 días** en el historial: no se paga capacidad ociosa ni almacenamiento viejo.
5. **Retención de CloudWatch Logs de 7 días** (en vez de “nunca expira”).
6. **EC2 sólo para el hito 6–7**, apagada fuera de clase y con `InstanceType` parametrizado.
7. **Caché de respuestas frecuentes** (a implementar): si la misma pregunta se repite, se responde desde DynamoDB sin llamar al modelo.

## Cómo se medirá el costo real

- AWS Cost Explorer filtrado por el tag `Equipo=juanes`, más el costo estimado por tokens que registra la tabla `Uso` (tokens × precio del modelo).
- Alarma de AWS Budgets al 80 % y 100 % del tope mensual, al correo del director.
- Reporte semanal: consultas, tokens promedio, costo acumulado y proyección a fin de mes.
