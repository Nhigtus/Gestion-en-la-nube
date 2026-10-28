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

## Dónde se corta el gasto (HU-03)

| # | Barrera | Implementación | Efecto |
|---|---|---|---|
| 1 | Presupuesto | `AWS::Budgets::Budget` `gtn-equipo-8-tope` con alertas **ACTUAL 80 %** y **FORECASTED 100 %** | Aviso temprano al 80 % del gasto y proyección al 100 %, visible en la consola |
| 2 | Contador | Tabla `gtn-equipo-8-uso`: consultas, tokens y costo del mes | Al llegar a **USD 10** o **5 000 consultas**, `/api/chat` responde `429` con mensaje de mantenimiento y **no llama al modelo** |
| 3 | Rate limit | 30 consultas/minuto por IP en memoria (`RATE_MAX_POR_MINUTO`) | Un pico recibe `429` + `Retry-After`; con 2 workers de gunicorn el límite efectivo es ~60/min |

Las alertas se publican en el topic SNS `gtn-equipo-8-alertas-gasto`, **sin suscriptores**: quedan
registradas en AWS Budgets y no envían correos. Costo de SNS: USD 0 (no hay entregas).

```bash
aws budgets describe-notifications-for-budget --account-id 287834270100 \
  --budget-name gtn-equipo-8-tope
# ACTUAL > 80 % → topic …-alertas-gasto
# FORECASTED > 100 % → topic …-alertas-gasto
```

## Cómo se mide el costo real

- **Cost Explorer** filtrado por servicio (la cuenta del laboratorio no etiqueta los costos por
  proyecto en el primer día, así que se filtra por los servicios del stack).
- **Contador de tokens** en la tabla `Uso` (precio del modelo × tokens) para el costo por consulta.
- **AWS Budgets** con el tope de 10 USD: `ActualSpend` y `ForecastedSpend` sin suscripciones.
- Reporte semanal: horas de EC2, consultas, tokens promedio, costo acumulado y proyección.

### Medición del 28 de octubre de 2026 (mes en curso)

```bash
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-10-29 \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
aws budgets describe-budget --account-id 287834270100 \
  --budget-name gtn-equipo-8-tope --query 'Budget.CalculatedSpend'
```

| Fuente | Valor | Lectura |
|---|---|---|
| Cost Explorer, total del mes | ≈ **USD 0,00** | El laboratorio cubre el consumo con crédito; el `UnblendedCost` neto queda en cero |
| Cost Explorer, EC2 Compute | USD 0,00013 | Uso real de la instancia, absorbido por el crédito |
| Budgets `ActualSpend` | **USD 0,00** | Coincide con Cost Explorer |
| Budgets `ForecastedSpend` | **USD 0,084** | Proyección del mes; muy por debajo del tope de 10 |

El gasto **estimado a precio público** sigue siendo el de la tabla de arriba (≈ 6,62 USD/mes con
8 h/día); la diferencia con el medido es el crédito del laboratorio, no una optimización.

### Costo por consulta medido por la app

`/api/uso` devuelve `costo_promedio` y `costo_usd`. Con Ollama el precio por token es 0, así que el
contador del modelo marca **USD 0,000000** por consulta; el costo real es el tiempo de EC2:

| Consultas/mes | Costo de infraestructura (8 h/día) | Costo por consulta |
|---|---|---|
| 1 000 | ≈ 6,62 | ≈ USD 0,0066 |
| 10 000 | ≈ 6,62 | ≈ USD 0,00066 |
| 100 000 | ≈ 6,62 | ≈ USD 0,000066 |

Por eso el contador de tokens sirve para vigilar el tope lógico y Cost Explorer para el gasto real:
son dos métricas distintas y ambas se muestran en el panel.

## Costo de las piezas nuevas (hito 8)

| Pieza | Costo |
|---|---|
| Panel de administración (`/admin`) | USD 0: son endpoints de la misma app |
| Token en SSM Parameter Store (1 SecureString estándar) | USD 0: el nivel estándar no cobra |
| Evaluación de calidad en GitHub Actions | USD 0: minutos gratuitos en repo público |
| Set de 10 preguntas + historial en el repo | USD 0 |
