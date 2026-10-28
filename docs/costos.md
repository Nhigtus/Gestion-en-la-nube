# Costos (FinOps)

**Presupuesto objetivo del enunciado:** USD 10/mes · **Escenario base:** 10 000 consultas/mes.
**Región:** `us-east-1`, precios públicos on-demand (octubre 2026). En AWS Academy se descuenta del crédito del laboratorio.

## Hallazgo que cambia el diseño

Bedrock está **bloqueado** en esta cuenta (`bedrock:InvokeModel` → `AccessDeniedException`, verificado
con la CLI y con una Lambda usando `LabRole`). El modelo corre en contenedor en la EC2, y eso cambia
la estructura de costos: aparece una instancia encendida, que es justo lo que la arquitectura
serverless evitaba.

## Estimado con modelo en contenedor (lo que se despliega hoy)

| Concepto | Supuesto | Estimado (USD/mes) | Real (USD/mes) | Diferencia y causa |
|---|---|---|---|---|
| EC2 t3.small | 8 h/día × 30 días = 240 h × 0,0208 | 4,99 | — | |
| EBS gp3 | 20 GB × 0,08/GB (modelo + imágenes Docker) | 1,60 | — | |
| DynamoDB on-demand | 10 000 lecturas + 20 000 escrituras + 1 GB | 0,03 | — | |
| API Gateway / Lambda | no se usan con Ollama | 0,00 | — | |
| **Total con 8 h/día** | | **≈ 6,62** | | **Cumple ≤ 10** |
| **Total con la EC2 24/7** | 730 h × 0,0208 + EBS + resto | **≈ 16,81** | | **No cumple**: el modelo en contenedor no puede estar 24/7 bajo el tope |

## Estimado de la arquitectura objetivo (Bedrock, serverless)

| Concepto | Supuesto | Estimado (USD/mes) |
|---|---|---|
| API Gateway HTTP API | 10 000 req × 1,00/M | 0,01 |
| Lambda | 10 000 inv × 1 s × 512 MB | 0,00 (free tier) |
| DynamoDB on-demand | igual que arriba | 0,03 |
| Bedrock Nova Micro | 15 M in × 0,035/M + 3 M out × 0,14/M | 0,95 |
| CloudWatch Logs | 1 GB | 0,50 |
| **Total 24/7** | | **≈ 1,50** |

## Costo por consulta

- **Con Ollama en EC2:** el costo es por tiempo encendido, no por consulta. Con 10 000 consultas/mes
  repartidas en 240 h, sale **≈ USD 0,0007 por consulta**; con 1 000 consultas sube a 0,007 porque la
  instancia cuesta lo mismo.
- **Con Bedrock:** **≈ USD 0,00015 por consulta** (0,15 milésimas).

La lección de FinOps: el modelo gestionado cobra por uso y el contenedor cobra por tiempo. Con tráfico
bajo y horario de oficina, el contenedor es razonable; 24/7 lo hace 11 veces más caro.

## Optimizaciones aplicadas

1. **EC2 apagada fuera de clase** (`stop-instances`), que es la diferencia entre USD 6,62 y USD 16,81.
2. **t3.small en vez de t3.medium** (2 GB alcanzan para un modelo de 1,5B cuantizado, con 2 GB de swap).
3. **EBS de 20 GB** justo para el modelo y las imágenes; sin snapshots automáticos.
4. **Un solo contenedor de modelo** (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=10m`).
5. **Contexto acotado**: 5 FAQ por consulta en vez de la base completa; `num_predict` 300.
6. **DynamoDB on-demand + TTL 30 días** en el historial.
7. **Sin NAT Gateway ni ALB** (USD 32/mes cada uno): la EC2 tiene IP pública y security group.
8. **Sin S3 ni CloudWatch Logs**: los logs del contenedor quedan en el host (`docker logs`).

## Cómo se mide el costo real

- AWS Cost Explorer filtrado por el tag `Equipo=equipo-8` y por servicio.
- Contador de tokens en la tabla `Uso` (precio del modelo × tokens) para el costo por consulta.
- AWS Budgets con el tope de 10 USD (sin suscripciones: se consulta en la consola y contra el contador de `Uso`).
- Reporte semanal: horas de EC2, consultas, tokens promedio, costo acumulado y proyección.

## Costo de las piezas nuevas (hito 8)

| Pieza | Costo |
|---|---|
| Panel de administración (`/admin`) | USD 0: son endpoints de la misma app |
| Token en SSM Parameter Store (1 SecureString estándar) | USD 0: el nivel estándar no cobra |
| Evaluación de calidad en GitHub Actions | USD 0: minutos gratuitos en repo público |
| Set de 10 preguntas + historial en el repo | USD 0 |
