# 🤖 Equipo juanes — Chat de FAQ con IA

> **Ficha del caso** — Chat 24/7 que responde en lenguaje natural las preguntas frecuentes del programa, con la base de FAQ propia, historial de conversación y gasto acotado.

| Campo | Valor |
|---|---|
| Proyecto | Por asignar (caso: chat de FAQ con IA para aspirantes) |
| Equipo | `juanes` |
| Integrantes | Juan Esteban Valencia — 1004735345 · Juan Hineztroza — 99999999 (código por confirmar) |
| Curso | GTN-2026-2 · Ambiente `lab` |
| URL demo | _pendiente (hito 6–7)_ |
| Costo mensual estimado | **USD 1,60** (objetivo del enunciado: ≤ USD 10) |
| Región | `us-east-1` |
| Despliegue | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-juanes --capabilities CAPABILITY_NAMED_IAM --parameter-overrides NombreEquipo=juanes NumeroProyecto=<NN> EmailAlerta=<correo>` |

## 🧩 El problema

Las mismas ~50 preguntas llegan cada semestre al asistente del programa (fechas, requisitos, calendario). Hoy responden a mano por correo y el aspirante espera días. Queremos un chat en la web que responda 24/7 **a partir de la base de FAQ curada por el asistente**, sin inventar, con historial y con un tope de gasto mensual que el director pueda vigilar.

## 👥 Actores

| Actor | Qué necesita |
|---|---|
| Estudiante aspirante | Preguntar en lenguaje natural y recibir respuesta útil al instante (HU-01) |
| Asistente del programa | Editar la base de FAQ sin programar y ver qué no se supo responder (HU-02, HU-04) |
| Director | Tope de gasto mensual y visibilidad del costo por consulta (HU-03) |

## 🏗️ Arquitectura (objetivo)

```
Navegador ──► CloudFront + S3 (chat web estático)
                   │
                   ▼
            API Gateway (HTTP API, throttle)
                   │
                   ▼
        Lambda (Python 3.12) ──► DynamoDB  FAQ · Conversaciones · SinRespuesta · Uso
                   │
                   ├──► Bedrock (Nova Micro) — respuesta con contexto de las FAQ
                   └──► CloudWatch + Budgets (alarma de gasto)
```

- **Recuperación sin embeddings**: con ~50 FAQ se seleccionan las 6 más parecidas por coincidencia de términos (TF-IDF en la Lambda, costo 0). Se documenta la alternativa con embeddings y por qué se descartó.
- **Tope de gasto en dos capas**: presupuesto/alarma en AWS Budgets (aviso al director) + contador de tokens en DynamoDB que corta el servicio al llegar al límite (`Uso`), más throttling en API Gateway como techo técnico.
- **EC2 sólo donde el hito lo exige**: el hito 6–7 pide servidor propio con la app en Docker; se usa una `t3.micro` con la app dockerizada y se apaga fuera de clase. La arquitectura final es serverless porque 24/7 en EC2 no cabe en USD 10.

El diagrama exportado vivirá en `docs/arquitectura.png` (hito 9–10).

## 🔑 Decisiones (resumen — detalle en `docs/decisiones.md`)

| Decisión | Elegimos | Alternativa descartada | Por qué |
|---|---|---|---|
| Cómputo de la API | Lambda + API Gateway | ECS/EC2 24/7 | Pago por uso; 24/7 en EC2 se come el presupuesto |
| Modelo | Bedrock Nova Micro | Contenedor con modelo local | USD 0,035/M tokens de entrada vs. EC2 permanente; mejor calidad en español |
| Base de FAQ | DynamoDB on-demand | RDS | Sin servidor ni costo fijo; 50 ítems no justifican RDS |
| Recuperación | TF-IDF local en la Lambda | Embeddings + vector DB | 50 FAQ caben en el prompt; cero costo y menos piezas |
| Historial | DynamoDB (sesión + timestamp) | Sólo memoria del navegador | Persistencia y evidencia para la demo |
| CI | GitHub Actions | Jenkins en la EC2 | Gratis para repo público, sin servidor que mantener |
| Tope de gasto | Budgets + contador en DynamoDB + throttle | Sólo confiar en el panel de AWS | Tres barreras independientes |

## 💰 Costos

Ver `docs/costos.md`. Estimado con 10 000 consultas/mes: **≈ USD 1,60/mes** sin EC2 y **≈ USD 3,10/mes** en las semanas con la EC2 del hito 6–7 encendida 8 h/día.

## 🚀 Cómo levantar en local

```bash
cd app
docker compose up --build     # http://localhost:8000/health
```

## ☁️ Cómo desplegar en AWS

```bash
# 1) credenciales del laboratorio en el entorno (nunca en el repo)
aws sts get-caller-identity

# 2) lint + despliegue
cfn-lint iac/*.yaml
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-juanes \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides NombreEquipo=juanes NumeroProyecto=<NN> EmailAlerta=<correo>
```

Detalle, costos y destrucción del stack en `iac/README.md`.

## 📅 Estado de hitos

| Hito | Estado |
|---|---|
| 0 — Ficha del caso | ✅ README, decisiones, costos, backlog y esqueleto de IaC |
| 6–7 — Servicio en línea | ⏳ EC2 + Docker + app |
| 9–10 — Arquitectura (Nota 2) | ⏳ diagrama + 6 pilares |
| 11–12 — Automatización | ⏳ CloudFormation completo + CI/CD |
| 13–14 — Seguridad y costos | ⏳ auditoría IAM + FinOps |
| 16 — Sustentación | ⏳ demo |

## 🗂️ Estructura

```
app/         aplicación (Flask + Dockerfile + compose); luego handler de Lambda
docs/        decisiones.md · costos.md
iac/         main.yaml (CloudFormation) + README de despliegue
.github/     plantilla de historia de usuario y CI (cfn-lint + tests)
```

## 🔀 Flujo de trabajo

- Una rama por historia (`hu-01-chat`), PR contra `main`, CI en verde y revisión del compañero antes de mezclar.
- Cada PR referencia su issue (`Closes #NN`).
- Historias en issues con criterios Dado/Cuando/Entonces y el hito al que pertenecen.
