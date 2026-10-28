# Decisiones de arquitectura (Nota 2)

Cada decisión nace de una historia o requisito no funcional. Se revisa contra los 6 pilares al final.

| # | Decisión | Alternativas | Elegida | Por qué | Pilar asociado | Historia |
|---|---|---|---|---|---|---|
| 1 | Cómputo de la API | ECS Fargate 24/7 · EC2 24/7 · Lambda | **Lambda + API Gateway HTTP API** | Pago por invocación (~USD 0 con 10k consultas), escala sola y no hay servidor que parchear. 24/7 en EC2 cuesta ~USD 7,6/mes sólo de instancia | Optimización de costos · Excelencia operativa | HU-01, HU-03 |
| 2 | Modelo de lenguaje | Bedrock (Nova Micro / Claude Haiku) · contenedor con modelo local | **Bedrock Nova Micro**, con Claude Haiku como respaldo configurable por parámetro | USD 0,035/M tokens de entrada; un contenedor con modelo pequeño exige EC2 permanente y da peor español | Costos · Rendimiento | HU-01, HU-03 |
| 3 | Base de conocimiento | RDS MySQL · S3 + JSON · DynamoDB | **DynamoDB on-demand** | Sin servidor, sin costo fijo, escritura desde el panel de administración y lecturas de un dígito en ms | Costos · Fiabilidad | HU-02 |
| 4 | Recuperación de contexto | Embeddings + vector DB (OpenSearch/pgvector) · TF-IDF en la Lambda | **TF-IDF en la Lambda sobre las 50 FAQ** | Con 50 documentos el puntaje por términos es suficiente y cabe en el prompt; evita costo de embeddings y una pieza más | Costos · Simplicidad | HU-01 |
| 5 | Historial de conversación | Sólo navegador · RDS · DynamoDB | **DynamoDB**: PK `sesion`, SK `timestamp`; TTL 30 días | Persistente para la demo, barato y con expiración automática | Costos · Seguridad | HU-01 |
| 6 | Control de gasto | Confiar en el panel de AWS · sólo Budgets · varias capas | **3 capas**: Budgets con alarma por correo + contador de tokens en DynamoDB que corta al llegar al tope + throttling en API Gateway | El enunciado exige tope configurado; una sola capa se puede saltar | Costos · Seguridad | HU-03 |
| 7 | Administración de FAQ | Panel propio con token · Cognito · editar el JSON en el repo | **Panel propio con token en SSM Parameter Store** (endurecer en hito 13–14) | “Sin programar” sin pagar Cognito; se audita después | Seguridad · Costos | HU-02 |
| 8 | CI/CD | Jenkins en la EC2 · GitHub Actions | **GitHub Actions** (cfn-lint + tests + build Docker) | Gratis en repo público, sin servidor Jenkins que mantener ni exponer | Excelencia operativa · Seguridad | RNF-IaC |
| 9 | Entrega de la infraestructura | Consola · CLI suelta · CloudFormation | **CloudFormation** con stacks por capa, Parámetros y Outputs | Requisito del curso; reproducible desde cero y destruible | Excelencia operativa | RNF-IaC |
| 10 | Servidor propio (hito 6–7) | Sólo serverless desde el inicio | **EC2 t3.micro con Docker Compose**, apagada fuera de clase | El hito pide servidor propio y app dockerizada; se usa como escaparate y respaldo de demo | Costos | HU-01 |

## Límite de gasto (cómo se aplica)

1. **AWS Budgets** con monto = `TopeGastoUSD` (10) y alerta al 80 % y 100 % al correo del director.
2. **Contador de uso** en la tabla `Uso`: cada consulta suma tokens de entrada/salida; si el costo acumulado del mes supera el tope, la Lambda responde con un mensaje de mantenimiento y no llama al modelo.
3. **Throttling** del HTTP API (rate/burst) para que un pico no dispare el consumo.

## Revisión 6 pilares (Well-Architected)

| Pilar | Cómo lo cumple el diseño | Riesgo detectado |
|---|---|---|
| Excelencia operativa | Todo en CloudFormation; CI con cfn-lint; logs estructurados en CloudWatch; un solo comando para crear/destruir | Falta automatizar el despliegue (hito 11–12) |
| Seguridad | Sin credenciales en el repo; IAM de mínimo privilegio por función; bucket S3 privado; token de administración en SSM; sin puerto 22 abierto | El panel de administración con token compartido debe endurecerse (Cognito o firma) |
| Fiabilidad | Lambda y DynamoDB on-demand con reintentos; Bedrock con modelo de respaldo; mensaje claro si se agota el tope | Dependencia de la cuota de Bedrock en la cuenta del laboratorio |
| Eficiencia de rendimiento | Contexto acotado a 6 FAQ + `maxTokens` 400; caché de respuestas frecuentes en DynamoDB | Latencia de Bedrock en horas pico |
| Optimización de costos | Serverless, on-demand, TTL en historial, EC2 sólo 8 h/día, tope de gasto en 3 capas | Si se habilita un modelo grande, el costo por consulta sube 10× |
| Sostenibilidad | Escala a cero, sin instancias encendidas 24/7, retención de logs limitada | La EC2 del hito 6–7 consume aunque esté ociosa: apagarla |

## Pendientes de decisión

- Modelo definitivo cuando se confirme el catálogo de Bedrock disponible en AWS Academy (Nova Micro vs. Claude Haiku).
- Mecanismo de autenticación del panel de administración (token en SSM vs. Cognito).
- Estrategia de evaluación automática de calidad en el pipeline (reto extra).
