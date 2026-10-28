# Arquitectura (hito 9–10)

Documento de arquitectura del chat de FAQ: vista de componentes, flujo de una consulta, decisiones
y revisión de los seis pilares de AWS Well-Architected. El detalle de cada decisión está en
`docs/decisiones.md`; el paso a paso de la construcción, en `docs/como-se-construyo.md`.

---

## 1. Vista de contexto

```
┌──────────────┐        HTTP :80         ┌───────────────────────────────────────────┐
│  Aspirante   │ ──────────────────────► │  AWS · us-east-1 · cuenta del laboratorio │
│  (navegador) │ ◄────────────────────── │  stack gtn-equipo-8                       │
└──────────────┘                         └───────────────────────────────────────────┘

┌──────────────┐        HTTP :80         ┌───────────────────────────────────────────┐
│  Asistente   │ ──────────────────────► │  Panel /admin (token en SSM)              │
│  del programa│                         └───────────────────────────────────────────┘

┌──────────────┐                         ┌───────────────────────────────────────────┐
│  Director    │ ──────────────────────► │  /api/uso + AWS Budgets (tope USD 10)     │
└──────────────┘                         └───────────────────────────────────────────┘
```

## 2. Vista de contenedores

```
                    Internet
                       │  TCP 80 (único puerto abierto; sin 22)
                       ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ EC2 t3.small · Amazon Linux 2023 · VPC 10.0.0.0/16           │
        │ Subred pública · IP pública · disco gp3 20 GB cifrado        │
        │                                                              │
        │  Docker Compose (red interna)                                │
        │  ┌────────────────────────────┐      ┌────────────────────┐  │
        │  │ app                        │      │ ollama             │  │
        │  │ Flask + gunicorn (2 w.)    │─────►│ qwen2.5:1.5b       │  │
        │  │ :8000 → publicado en :80   │ HTTP │ :11434 (interno)   │  │
        │  │                            │      │ volumen del modelo │  │
        │  │ · retrieval TF-IDF         │      └────────────────────┘  │
        │  │ · guardrail (umbral 0.34)  │                              │
        │  │ · rate limit por IP        │                              │
        │  │ · tope de gasto            │                              │
        │  │ · panel /admin             │                              │
        │  └──────────┬─────────────────┘                              │
        │             │ boto3 (credenciales del instance profile)      │
        └─────────────┼────────────────────────────────────────────────┘
                      │
        ┌─────────────▼───────────────┐   ┌──────────────────────────┐
        │ DynamoDB (on-demand)        │   │ SSM Parameter Store      │
        │ FAQ · Conversaciones        │   │ /gtn/equipo-8/admin-token│
        │ SinRespuesta · Uso          │   │ (SecureString cifrado)   │
        └─────────────────────────────┘   └──────────────────────────┘

        AWS Budgets ──► SNS (sin suscriptores)   ·   CloudFormation (todo el stack)
```

### Componentes

| Componente | Tecnología | Responsabilidad | Por qué así |
|---|---|---|---|
| Entrada | Security Group | Solo TCP 80 desde Internet; sin SSH | Superficie mínima; acceso admin por SSM |
| Servidor | EC2 t3.small | Hospeda los contenedores | Único sitio donde cabe un modelo local; Bedrock está bloqueado |
| API/UI | Flask + gunicorn (2 workers) | Chat, historial, panel, métricas | Simple, sin servidor de aplicaciones extra |
| Recuperación | TF-IDF + stemming + sinónimos | Elegir 3 FAQ relevantes | 26–50 FAQ caben en el prompt; sin embeddings ni costo |
| Guardrail | Umbral 0.34 + regla de vocabulario | Decidir "no sé" antes del modelo | Evita alucinaciones por diseño, no por instrucción |
| LLM | Ollama + qwen2.5:1.5b-instruct | Redactar la respuesta | Entra en 2 GB de RAM; costo por consulta USD 0 |
| Persistencia | DynamoDB (4 tablas) | FAQ, historial, no respondidas, uso | Sin servidor, on-demand, TTL en historial |
| Secretos | SSM SecureString | Token del panel | Cero secretos en el repo; rotación sin desplegar |
| Control de gasto | Budgets + contador + rate limit | Avisar, cortar y amortiguar | Tres capas independientes |
| Entrega | GitHub Actions | Lint, tests, build, evaluación | Calidad medida en cada PR |
| Infraestructura | CloudFormation (`iac/main.yaml`) | Reproducir todo desde cero | Un comando crea y destruye el entorno |

## 3. Flujo de una consulta

```
POST /api/chat {mensaje, sesion}
  │
  ├─ 1. rate limit por IP (30/min) ──────────────► 429 + Retry-After
  ├─ 2. tope del mes (Uso ≥ USD 10 o ≥ 5000) ────► 429 sin llamar al modelo
  ├─ 3. validación del mensaje (≤ 500 caracteres) ► 400
  ├─ 4. retrieval: TF-IDF sobre las FAQ
  │       ├─ mejor puntaje < 0.34 ──► respuesta "no tengo esa información"
  │       │                            + fila en SinRespuesta (sin LLM)
  │       └─ vocabulario desconocido y no coincide la pregunta ► igual que arriba
  ├─ 5. prompt = reglas + 3 FAQ + últimos 4 turnos
  ├─ 6. Ollama (timeout 120 s, 300 tokens, temperatura 0.2)
  ├─ 7. guardar turno (Conversaciones, TTL 7 días) y sumar tokens/costo (Uso)
  └─ 8. responder {respuesta, latencia_ms, tokens, costo_usd, fuentes}
```

### Flujo de administración

```
/admin  ──token──►  X-Admin-Token  ──►  comparación en tiempo constante (hmac.compare_digest)
   │                                        │
   │                                        ├─ inválido/ausente → 401
   │                                        └─ válido → CRUD de FAQ / convertir SinRespuesta / Consumo
   └─ token en sessionStorage (se borra al cerrar la pestaña)
```

### Flujo de despliegue

```
git push → PR → CI (cfn-lint · pytest · build · evaluación 10 preguntas)
        → merge a main
        → (si cambia infra) aws cloudformation deploy --stack-name gtn-equipo-8
        → (si cambia código) SSM: git pull && docker compose up -d --build
```

El `UserData` de la EC2 (solo en el primer arranque) instala Docker + compose + buildx, crea 2 GB de
swap, clona el repo, escribe el `.env`, levanta los contenedores y descarga el modelo.

## 4. Capacidad y rendimiento (medido)

| Métrica | Valor | Nota |
|---|---|---|
| Latencia primera consulta | 20–40 s | carga del modelo en RAM |
| Latencia consultas siguientes | ~20 s | inferencia en CPU (sin GPU) |
| Trabajos concurrentes del modelo | 1 | `OLLAMA_NUM_PARALLEL=1` |
| Workers de la app | 2 | gunicorn |
| Throughput sostenido | ≈ 3 consultas/min | cuello de botella: CPU |
| Contexto por consulta | 3 FAQ + 4 turnos | acota tokens y latencia |

**El RNF "p95 < 8 s" no se cumple** con inferencia en CPU. Se documenta como limitación, no se
esconde: el diseño sí lo cumpliría con un proveedor gestionado (Bedrock), que el laboratorio bloquea.

## 5. Revisión de los 6 pilares (Well-Architected)

| Pilar | Cómo se cumple | Riesgo y mitigación |
|---|---|---|
| **Excelencia operativa** | Todo en un template; `cfn-lint` + tests + evaluación en cada PR; deploy y destroy de un comando; guía de operación | El despliegue de código es manual por SSM → documentado en `docs/guia-operacion.md`; automatizarlo requiere credenciales AWS en GitHub, que el laboratorio no permite de forma segura |
| **Seguridad** | Sin secretos en el repo; token en SSM cifrado; sin puerto 22; IMDSv2 obligatorio; SG solo 80; `.env` ignorado | `LabRole` es amplio (impuesto por el laboratorio) y el sitio va por HTTP. Ver `docs/seguridad.md` con hallazgos y plan |
| **Fiabilidad** | DynamoDB on-demand; `restart: unless-stopped`; health check de contenedor; guardrail que evita respuestas sin evidencia; tope de gasto que degrada con mensaje claro | Un solo servidor: si la EC2 cae, el chat no responde. Mitigación: health check + reinicio automático + guía de recuperación. La arquitectura objetivo elimina el punto único |
| **Eficiencia de rendimiento** | Contexto acotado (3 FAQ, 300 tokens); una sola instancia del modelo; respuesta sin llamar al LLM cuando no hay evidencia | ~20 s por consulta en CPU. Mitigación: calentamiento antes de la demo y, a futuro, Bedrock |
| **Optimización de costos** | EC2 apagada fuera de clase; sin NAT ni ALB; S3 y CloudWatch eliminados; DynamoDB on-demand; tope en 3 capas | 24/7 con EC2 cuesta ≈ USD 16,81 > 10. Mitigación: apagado programado y arquitectura objetivo serverless (≈ USD 1,50) |
| **Sostenibilidad** | Escala a cero al apagar; sin almacenamiento ni logs ociosos; TTL en historial; contexto corto | La EC2 consume aun ociosa mientras esté encendida: apagarla es parte del procedimiento |

## 6. Decisiones y alternativas

| Decisión | Elegido | Descartado | Motivo |
|---|---|---|---|
| Cómputo | EC2 + Docker Compose | Lambda + API Gateway | El modelo local no cabe en Lambda; Bedrock bloqueado |
| Modelo | Ollama qwen2.5:1.5b | Bedrock Nova Micro | `bedrock:InvokeModel` denegado en el laboratorio |
| Recuperación | TF-IDF | Embeddings + vector DB | 50 FAQ no justifican otra pieza; cero costo |
| Base de datos | DynamoDB on-demand | RDS | Sin servidor ni costo fijo |
| Acceso | SSM Session Manager | SSH con llave | Sin puerto abierto ni llaves que rotar |
| Tokens del panel | SSM SecureString | Cognito | Sin costo y suficiente para el alcance |
| Infra | Un `main.yaml` plano | Stacks por capa | La rúbrica exige el comando exacto con `iac/main.yaml`; las capas están separadas por secciones y tags |

## 7. Arquitectura objetivo (fuera del laboratorio)

```
CloudFront + S3 (frontend) ──► API Gateway ──► Lambda (Python)
                                                  ├─► Bedrock (modelo gestionado)
                                                  ├─► DynamoDB (4 tablas)
                                                  └─► CloudWatch (logs, alarmas 5xx y p95)
```

Ventajas: 24/7 real sin servidor encendido, escala a cero, p95 bajo, ≈ USD 1,50/mes. El código ya
está preparado (`PROVEEDOR_LLM=bedrock|ollama`), solo falta que la cuenta permita Bedrock.

## 8. Limitaciones conocidas

| Limitación | Impacto | Estado |
|---|---|---|
| Latencia ~20 s por consulta | No cumple p95 < 8 s | Aceptada y documentada; se resuelve con Bedrock |
| Un solo servidor | Punto único de falla | Mitigado con reinicio automático; se resuelve con serverless |
| 24/7 depende de dejar la EC2 encendida | Costo ≈ USD 16,81/mes si no se apaga | Procedimiento de apagado en la guía |
| Token compartido en el panel | Sin usuarios ni roles | Suficiente para el alcance; Cognito en la versión objetivo |
| HTTP sin TLS | Tráfico en claro | Demo académica; en producción ALB + ACM o CloudFront |
| `LabRole` amplio | No hay mínimo privilegio real | Impuesto por el laboratorio; ver `docs/seguridad.md` |
