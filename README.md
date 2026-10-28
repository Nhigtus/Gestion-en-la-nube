# 🤖 Equipo equipo-8 — Chat de FAQ con IA

> **Ficha del caso** — Chat 24/7 que responde en lenguaje natural las preguntas frecuentes del programa, con la base de FAQ propia, historial de conversación y gasto acotado.

| Campo | Valor |
|---|---|
| Proyecto | **08** — Chat de FAQ con IA para aspirantes |
| Equipo | `equipo-8` |
| Integrantes | Juan Esteban Valencia — 1004735345 · Juan Hineztroza — código pendiente |
| Curso | GTN-2026-2 · Ambiente `lab` · Región `us-east-1` |
| URL demo | _sale en el Output `UrlDemo` del stack_ |
| Costo mensual estimado | **≈ USD 7,15** con la EC2 encendida 8 h/día (objetivo: ≤ USD 10) |
| Despliegue | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-equipo-8 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides NombreEquipo=equipo-8 NumeroProyecto=08 EmailAlerta=<correo>` |

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
                 └── CloudWatch Logs
                        ▲
          AWS Budgets (tope 10 USD) + SNS
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

## 💰 Costos

Ver `docs/costos.md`. **≈ USD 7,15/mes** con la EC2 8 h/día; **≈ USD 17,30/mes** si queda 24/7.
Esa diferencia es la razón por la que la arquitectura objetivo es serverless: con Bedrock el mismo
tráfico cuesta ≈ USD 1,50 y sí puede estar 24/7.

## 🚀 Cómo levantar en local

```bash
cd app
cp .env.example .env
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct
# http://localhost:8000/health
```

## ☁️ Cómo desplegar en AWS

```bash
cfn-lint iac/*.yaml
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-equipo-8 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides NombreEquipo=equipo-8 NumeroProyecto=08 EmailAlerta=<correo>
```

Detalle, costos, cómo detener y cómo destruir en `iac/README.md`.

## 📅 Estado de hitos

| Hito | Estado |
|---|---|
| 0 — Ficha del caso | ✅ README, decisiones, costos, backlog e IaC |
| 6–7 — Servicio en línea | 🔄 EC2 + Docker + Ollama desplegados; chat en implementación |
| 9–10 — Arquitectura (Nota 2) | ⏳ diagrama + 6 pilares |
| 11–12 — Automatización | ⏳ CI/CD + stack completo |
| 13–14 — Seguridad y costos | ⏳ auditoría IAM + FinOps |
| 16 — Sustentación | ⏳ demo |

## 🗂️ Estructura

```
app/         app Flask + Dockerfile + compose (app + Ollama) + tests
docs/        decisiones.md · costos.md
iac/         main.yaml (CloudFormation) + README de despliegue
.github/     plantilla de historia de usuario y CI (cfn-lint + tests + build)
```

## 🔀 Flujo de trabajo

- Una rama por historia (`hu-01-chat`), PR contra `main`, CI en verde y revisión del compañero antes de mezclar.
- Cada PR referencia su issue (`Closes #NN`).
- Historias en issues con criterios Dado/Cuando/Entonces y el hito al que pertenecen.
