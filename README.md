# 🤖 Equipo equipo-8 — Chat de FAQ con IA

> **Ficha del caso** — Chat 24/7 que responde en lenguaje natural las preguntas frecuentes del programa, con la base de FAQ propia, historial de conversación y gasto acotado.

| Campo | Valor |
|---|---|
| Proyecto | **08** — Chat de FAQ con IA para aspirantes |
| Equipo | `equipo-8` |
| Integrantes | Juan Esteban Valencia — 1004735345 · Juan Hineztroza — código pendiente |
| Curso | GTN-2026-2 · Ambiente `lab` · Región `us-east-1` |
| URL demo | _sale en el Output `UrlDemo` del stack_ |
| Costo mensual estimado | **≈ USD 6,63** con la EC2 encendida 8 h/día (objetivo: ≤ USD 10) |
| Despliegue | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-equipo-8 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides NombreEquipo=equipo-8 NumeroProyecto=08` |

## 🧩 El problema

Las mismas ~50 preguntas llegan cada semestre al asistente del programa (fechas, requisitos, calendario). Hoy responde a mano por correo y el aspirante espera días. Queremos un chat en la web que responda 24/7 **a partir de la base de FAQ curada por el asistente**, sin inventar, con historial y con un tope de gasto mensual que el director pueda vigilar.

## 👥 Actores

| Actor | Qué necesita |
|---|---|
| Estudiante aspirante | Preguntar en lenguaje natural y recibir respuesta útil al instante (HU-01) |
| Asistente del programa | Editar la base de FAQ sin programar y ver qué no se supo responder (HU-02, HU-04) |
| Director | Tope de gasto mensual y visibilidad del costo por consulta (HU-03) |

## 🏗️ Arquitectura

```
Navegador ──► EC2 t3.small (puerto 80, sin SSH abierto)
                 │  Docker Compose
                 ├── app (Flask + gunicorn, contenedor)
                 │      ├──► DynamoDB  FAQ · Conversaciones · SinRespuesta · Uso
                 │      └──► Ollama (contenedor) — qwen2.5:1.5b-instruct
                 └── logs del contenedor (docker logs)

AWS Budgets (tope 10 USD, sin suscripciones) · SSM (token del panel)
```

**Por qué el modelo va en contenedor:** en la cuenta de AWS Academy el acceso a Bedrock está
denegado (`bedrock:InvokeModel` → `AccessDeniedException`, comprobado desde la CLI y desde una
Lambda con `LabRole`). El enunciado permite explícitamente “modelo en contenedor para la demo”,
así que Ollama corre en la misma EC2 y la app lo consume por la red interna de Docker.

**Arquitectura objetivo (cuando haya Bedrock):** API Gateway + Lambda + DynamoDB, sin servidor
encendido, ≈ USD 1,50/mes y disponible 24/7 real. El código se escribe con un proveedor de LLM
intercambiable (`PROVEEDOR_LLM=ollama|bedrock`) para migrar sin reescribir la lógica. La decisión
y el análisis están en `docs/decisiones.md`.

**Restricciones del laboratorio que condicionan el diseño** (verificadas, no supuestas):

| Restricción | Efecto |
|---|---|
| `bedrock:InvokeModel` denegado | Modelo en contenedor (plan B del enunciado) |
| `iam:CreateRole` denegado | El stack usa el `LabRole` / `LabInstanceProfile` existentes; no crea roles |
| Sesión de laboratorio de 4 h | Credenciales temporales y EC2 que se apaga fuera de clase |
| Crédito del lab | Cada cambio se mide; `delete-stack` al terminar |

## 🔑 Decisiones (resumen — detalle en `docs/decisiones.md`)

| Decisión | Elegimos | Alternativa descartada | Por qué |
|---|---|---|---|
| Cómputo | EC2 t3.small + Docker Compose | Lambda + API Gateway | Es la única forma de correr el modelo en contenedor hoy; Lambda queda como objetivo |
| Modelo | Ollama + qwen2.5:1.5b | Bedrock Nova Micro | Bedrock está bloqueado en el laboratorio; 1,5B entra en 2 GB de RAM |
| Base de FAQ | DynamoDB on-demand | RDS | Sin servidor ni costo fijo |
| Recuperación | TF-IDF local sobre las FAQ | Embeddings + vector DB | 50 FAQ caben en el prompt; cero costo y menos piezas |
| Historial | DynamoDB (sesión + timestamp) | Sólo memoria del navegador | Persistencia y evidencia para la demo |
| Acceso a la EC2 | SSM Session Manager | SSH con puerto 22 | Sin puerto abierto ni llaves que rotar |
| CI | GitHub Actions | Jenkins en la EC2 | Gratis en repo público, sin servidor que mantener |
| Tope de gasto | Budgets + contador en DynamoDB | Sólo confiar en el panel de AWS | Dos barreras independientes |
| Token del panel | Generado al azar y guardado en SSM SecureString | Token en `.env` o en la plantilla | Cero secretos en el repo y sin despliegue extra |
| Evaluación de calidad | Set de 10 preguntas en el CI, mínimo 8/10 | Revisión manual del prompt | Detecta regresiones antes de mezclar |

## 💰 Costos

Ver `docs/costos.md`. **≈ USD 6,63/mes** con la EC2 8 h/día; **≈ USD 16,81/mes** si queda 24/7.
Esa diferencia es la razón por la que la arquitectura objetivo es serverless: con Bedrock el mismo
tráfico cuesta ≈ USD 1,50 y sí puede estar 24/7.

## 🔌 API

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/chat` | `{mensaje, sesion}` → respuesta, FAQ usadas, latencia, tokens y costo |
| `GET` | `/api/historial/<sesion>` | Historial de la conversación (DynamoDB, TTL 30 días) |
| `GET` | `/api/uso` | Consultas, tokens y costo del mes contra el tope |
| `GET` | `/health` | Estado, modelo y proveedor |
| `GET` | `/admin` | Panel para mantener la base de FAQ (token en SSM, no en el repo) |
| `GET` | `/api/admin/faqs` | Lista la base completa (requiere `X-Admin-Token`) |
| `POST` `PUT` `DELETE` | `/api/admin/faqs[/<id>]` | Crea, edita y borra FAQ sin desplegar código |
| `GET` | `/api/admin/sin-respuesta` | Preguntas que el bot no supo responder, ordenadas por frecuencia |
| `POST` | `/api/admin/sin-respuesta/<id>/convertir` | Convierte una pregunta sin respuesta en FAQ |
| `GET` | `/api/admin/reporte` | Totales y top 5 para el reporte semanal |

La base de FAQ se carga sola en el primer arranque (`app/data/faq.json`, 26 preguntas de ejemplo).
El prompt y la estrategia de contexto están documentados en `docs/prompt.md`.

### Panel de administración

En `http://<ip>/admin` el asistente edita la base en vivo. El token **no está en el repositorio**:
se genera al azar en el arranque y se guarda cifrado en SSM (`/gtn/equipo-8/admin-token`).

```bash
aws ssm get-parameter --name /gtn/equipo-8/admin-token \
  --with-decryption --query Parameter.Value --output text
```

Sin token (o con uno inválido) los endpoints responden `401` y no modifican nada.
Las preguntas que el bot no supo responder se convierten en FAQ desde la segunda pestaña del panel.

### Evaluación automática de calidad (reto extra)

`tests/eval/preguntas.json` tiene 10 preguntas (7 del dominio y 3 fuera de la base) y
`app/eval/evaluar.py` calcula aciertos y alucinaciones. El pipeline falla si baja de **8/10**,
publica el reporte como artefacto, comenta el resultado en el PR y guarda el histórico en
`docs/eval/historial.md`.

```bash
python app/eval/evaluar.py                                   # offline: recuperación + guardarraíl
python app/eval/evaluar.py --url http://<ip>                 # endpoint real de la EC2
python app/eval/evaluar.py --simular-regresion               # demuestra el pipeline en rojo
```

## 🚀 Cómo levantar en local

```bash
cd app
cp .env.example .env
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct
# http://localhost:8000/  (sin credenciales de AWS el chat no responde: usa DynamoDB)
```

## ☁️ Cómo desplegar en AWS

```bash
cfn-lint iac/*.yaml
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-equipo-8 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides NombreEquipo=equipo-8 NumeroProyecto=08
```

Detalle, costos, cómo detener y cómo destruir en `iac/README.md`.

## 📅 Estado de hitos

| Hito | Estado |
|---|---|
| 0 — Ficha del caso | ✅ README, decisiones, costos, backlog e IaC |
| 6–7 — Servicio en línea | ✅ EC2 + Docker + Ollama; chat, historial, contador de uso, panel de FAQ y preguntas sin respuesta |
| 9–10 — Arquitectura (Nota 2) | ⏳ diagrama + 6 pilares |
| 11–12 — Automatización | ⏳ CI con cfn-lint, tests, build y evaluación de calidad; falta el despliegue automático |
| 13–14 — Seguridad y costos | ⏳ auditoría IAM + FinOps |
| 16 — Sustentación | ⏳ demo |
| Extra | ✅ Evaluación automática de calidad en el pipeline (mínimo 8/10) |

## 🗂️ Estructura

```
app/         app Flask + Dockerfile + compose (app + Ollama) + tests + eval/
docs/        decisiones.md · costos.md · prompt.md · eval/historial.md
tests/eval/  set de 10 preguntas con respuesta esperada
iac/         main.yaml (CloudFormation) + README de despliegue
.github/     plantilla de historia de usuario y CI (cfn-lint + tests + evaluación)
```

## 🔀 Flujo de trabajo

- Una rama por historia (`hu-01-chat`), PR contra `main`, CI en verde y revisión del compañero antes de mezclar.
- Cada PR referencia su issue (`Closes #NN`).
- Historias en issues con criterios Dado/Cuando/Entonces y el hito al que pertenecen.
