# Cómo se construyó el proyecto, paso a paso

Este documento cuenta **qué se hizo, en qué orden y por qué**, explicando cada concepto la primera
vez que aparece. Sirve para la sustentación: cualquiera del equipo debería poder explicar el sistema
leyendo esto.

Para operarlo (encender, apagar, conectarse, modificar) está `docs/guia-operacion.md`.

---

## 1. Qué es el sistema en una frase

Un chat web que responde en lenguaje natural las preguntas frecuentes del programa **usando solo la
base de FAQ curada por el asistente**, recuerda el hilo de la conversación, guarda lo que no supo
responder y no puede gastar más de USD 10 al mes.

```
Navegador
   │  HTTP :80
   ▼
EC2 t3.small  (Amazon Linux 2023, Docker)
   ├── contenedor "app"    Flask + gunicorn, 2 workers, :8000
   │      ├─► DynamoDB   FAQ · Conversaciones · SinRespuesta · Uso
   │      └─► contenedor "ollama"  qwen2.5:1.5b-instruct, :11434 (red interna)
   └── contenedor "ollama"  modelo descargado en un volumen Docker
AWS Budgets (tope USD 10) · SNS (sin suscriptores) · SSM (token del panel)
```

### Qué pasa cuando alguien escribe una pregunta

1. El navegador hace `POST /api/chat` con `{mensaje, sesion}`.
2. La app revisa el **rate limit** por IP y el **tope de gasto** del mes; si se pasó, responde `429`
   sin llamar al modelo.
3. Busca en las FAQ con **TF-IDF** y elige las 3 más parecidas.
4. Si la mejor no supera el **umbral**, no llama al modelo: contesta "no tengo esa información" y
   guarda la pregunta en `SinRespuesta`.
5. Si hay contexto, arma el **prompt** (instrucciones + FAQ recuperadas + últimos turnos) y llama a
   Ollama por la red interna de Docker.
6. Guarda el turno en `Conversaciones`, suma tokens y costo en `Uso` y devuelve la respuesta con
   `latencia_ms`, `tokens` y `costo_usd`.

---

## 2. Conceptos que hay que saber explicar

| Concepto | Qué es | Dónde está en el proyecto |
|---|---|---|
| **CloudFormation** | Servicio de AWS que crea recursos a partir de un archivo de texto (infraestructura como código). Si el archivo describe 12 recursos, crea los 12 en orden y los borra juntos. | `iac/main.yaml` |
| **Stack** | Una instancia concreta de ese template, con nombre propio y estado (`CREATE_COMPLETE`, `UPDATE_COMPLETE`…). Permite actualizar y borrar todo como una unidad. | `gtn-equipo-8` |
| **Parameters** | Valores de entrada del template, para no repetir datos ni hardcodear. | `NombreEquipo`, `TopeGastoUSD`, `TipoInstancia`… |
| **Outputs** | Valores que el stack devuelve al terminar (URL, IP, nombre de tablas). Se leen con `describe-stacks`. | `UrlDemo`, `IpPublica`, `PanelAdmin`, `ParametroTokenAdmin` |
| **Tags** | Etiquetas clave/valor en cada recurso. Sirven para filtrar, auditar y para la rúbrica. | `Curso`, `Equipo`, `Proyecto`, `Ambiente` en **todos** los recursos |
| **UserData** | Script que la EC2 ejecuta **una sola vez**, en su primer arranque. Es el "instalador" del servidor. | Instala Docker, crea swap, clona el repo, escribe `.env`, hace `docker compose up` y descarga el modelo |
| **Instance Profile** | "Carné" que le da credenciales de IAM a la EC2 para hablar con otros servicios. | `LabInstanceProfile` (preexistente del laboratorio) |
| **IMDSv2** | Servicio de metadatos de la EC2, obligatorio en modo token. El contenedor necesita `HttpPutResponseHopLimit: 2` para alcanzarlo y obtener credenciales. | `MetadataOptions` de `InstanciaApp` |
| **Security Group** | Firewall por instancia. Solo se abre el puerto 80; **no hay puerto 22**. | `GrupoSeguridadWeb` |
| **Docker** | Empaqueta la app con sus dependencias en una **imagen**; al ejecutarla se vuelve un **contenedor** aislado. | `app/Dockerfile` |
| **Docker Compose** | Orquesta varios contenedores como un solo servicio, con red interna y volúmenes. | `app/docker-compose.yml` (app + ollama) |
| **Volumen** | Disco que sobrevive a los reinicios del contenedor. Evita volver a descargar el modelo. | `ollama:/root/.ollama` |
| **Ollama** | Servidor de modelos de lenguaje que corre local. Reemplaza a Bedrock, que está bloqueado en el laboratorio. | Contenedor `ollama`, modelo `qwen2.5:1.5b-instruct` |
| **DynamoDB on-demand** | Base de datos NoSQL sin servidor: se paga por lectura/escritura, no por hora. | 4 tablas `gtn-equipo-8-*` |
| **SSM Parameter Store** | Almacén de configuración y secretos. En modo `SecureString` el valor queda cifrado con KMS. | Token del panel en `/gtn/equipo-8/admin-token` |
| **SSM Session Manager** | Consola remota a la EC2 **sin abrir SSH ni tener llaves**. La EC2 se conecta hacia afuera al servicio. | Único mecanismo de administración |
| **TF-IDF + coseno** | Técnica de recuperación: da más peso a palabras raras de cada FAQ y compara vectores. Sin embeddings ni base vectorial. | `app/src/retrieval.py` |
| **Umbral (guardrail)** | Puntaje mínimo para considerar que una FAQ responde la pregunta. Si no se alcanza, el sistema **no inventa**. | `UMBRAL = 0.34` |
| **Prompt / contexto** | Texto que recibe el modelo: rol, reglas, FAQ recuperadas e historial. Es lo que limita las alucinaciones. | `docs/prompt.md` |
| **Costo por consulta** | Tokens de entrada/salida × precio del modelo, calculado en cada llamada y acumulado por mes. | `Uso` en DynamoDB + `/api/uso` |
| **AWS Budgets + SNS** | Presupuesto con alertas a un tema SNS. El tema existe **sin suscriptores**: no envía correos, pero deja la alerta configurada y auditable. | `Presupuesto` y `TopicAlertas` en el template |
| **Rate limit** | Límite de consultas por IP por minuto en memoria del proceso. Corta picos antes de llegar al modelo. | `RATE_MAX_POR_MINUTO=30` |
| **CI (GitHub Actions)** | Tubería que corre en cada PR: `cfn-lint`, tests y la evaluación de calidad. Si algo falla, no se mezcla. | `.github/workflows/ci.yml` |
| **Evaluación automática** | Set de 10 preguntas con respuesta esperada; mide aciertos y alucinaciones y falla bajo 8/10. | `app/eval/evaluar.py` + `tests/eval/preguntas.json` |

---

## 3. Construcción, en orden

### Paso 0 — Entender el laboratorio antes de diseñar

Lo primero no fue escribir código sino **probar qué permite la cuenta de AWS Academy**. Resultados
que cambiaron el diseño:

| Prueba | Resultado | Consecuencia |
|---|---|---|
| `bedrock:InvokeModel` | `AccessDeniedException` | El LLM va en contenedor (Ollama), que el enunciado permite |
| `iam:CreateRole` | Denegado | No se crean roles: se usa `LabRole` / `LabInstanceProfile` |
| `service-quotas` | Denegado | No se puede pedir aumento de cuota |
| Sesión | ~4 h y crédito limitado | Nada de NAT, ALB ni RDS; EC2 apagable |

Esto se documentó en `docs/decisiones.md` como **restricciones verificadas, no supuestas**.

### Paso 1 — Ficha, decisiones y alcance (Hito 0, PR #1)

Se escribieron `README.md` (problema, actores, arquitectura, costos), `docs/decisiones.md`,
`docs/costos.md`, `docs/prompt.md` y el backlog en issues con formato Dado/Cuando/Entonces.
Concepto: **antes de la infraestructura, el equipo acuerda qué va a construir y con qué límites**.

### Paso 2 — La app funcionando en local, sin AWS

Flask con:
- `/api/chat` (pregunta → respuesta),
- `/api/historial/<sesion>`,
- `/api/uso`,
- panel `/admin`.

Se separó en módulos: `app.py` (rutas), `retrieval.py` (búsqueda), `llm.py` (proveedor
intercambiable), `store.py` (DynamoDB), `auth.py` (token). Los tests (`app/tests/test_app.py`) usan
mocks, así que **corren sin credenciales ni modelo**: es lo que hace el CI.

Concepto: **separar la lógica del proveedor de nube** permite probar todo gratis y cambiar de
proveedor después (`PROVEEDOR_LLM=ollama|bedrock`).

### Paso 3 — Template: red (PR #12)

VPC propia (`10.0.0.0/16`), subred pública, Internet Gateway, tabla de rutas y asociación.
Security Group con **solo el puerto 80** abierto y salida libre (para `dnf`, Docker Hub y la
descarga del modelo).

Concepto: aunque es una sola EC2, la red se declara explícitamente para que el stack sea
reproducible y no dependa de la VPC por defecto.

### Paso 4 — Template: datos (PR #12)

Cuatro tablas DynamoDB, todas `PAY_PER_REQUEST`, cifradas y con `DeletionPolicy: Delete`:

| Tabla | Clave | Para qué |
|---|---|---|
| `gtn-equipo-8-faq` | `id` | Base de conocimiento que edita el asistente |
| `gtn-equipo-8-conversaciones` | `sesion` + `ts` | Historial por sesión, con TTL (`expira`) |
| `gtn-equipo-8-sin-respuesta` | `id` | Preguntas que el sistema no supo responder |
| `gtn-equipo-8-uso` | `mes` | Tokens, consultas y costo acumulado del mes |

Concepto: `DeletionPolicy: Delete` evita que al borrar el stack queden tablas cobrando; en un
laboratorio eso importa.

### Paso 5 — Template: cómputo (PR #12)

`InstanciaApp` es una `t3.small` (2 GB de RAM, mínimo para el modelo de 1,5B) con:
- AMI resuelta desde SSM (`/aws/service/ami-amazon-linux-latest/...`) → siempre la última AL2023;
- `IamInstanceProfile: LabInstanceProfile`;
- `MetadataOptions` con IMDSv2 obligatorio y **hop limit 2**;
- disco gp3 de 20 GB cifrado, `DeleteOnTermination: true`;
- `UserData` que instala Docker + compose + buildx, crea **2 GB de swap**, clona el repo en
  `/opt/gtn/src`, escribe el `.env` con los nombres de tablas y arranca `docker compose up -d --build`,
  y por último descarga el modelo (`ollama pull`).

Concepto: **UserData = instalación automática**. La EC2 no se configura a mano: si se destruye el
stack y se vuelve a desplegar, queda igual.

### Paso 6 — El primer despliegue y los tropiezos reales

| Síntoma | Causa | Solución aplicada |
|---|---|---|
| Bedrock negado | Cuenta de laboratorio | Ollama en contenedor |
| `docker compose build` falla | AL2023 no trae `buildx` | Se instala el plugin en `UserData` |
| La app no ve credenciales | El contenedor queda a 2 saltos del IMDS | `HttpPutResponseHopLimit: 2` |
| El modelo no cabe en RAM | `t3.micro` = 1 GB | `t3.small` + swap de 2 GB |
| El deploy falla al actualizar con la EC2 apagada | Los Outputs usan `PublicIp`, que no existe si está detenida | Encender antes de desplegar (documentado en `iac/README.md`) |

Concepto: **los errores se documentan**. Cada uno de estos quedó escrito para que no se repita.

### Paso 7 — Chat con recuperación y guardrail (PR #13–#15)

`retrieval.py` convierte las FAQ y la pregunta en vectores **TF-IDF** con stemming en español y un
mapa de sinónimos ("vale" → "costo", "inscripción" → "matrícula"). Se comparan con similitud de
coseno y se toman las 3 mejores.

Dos reglas evitan alucinaciones:
1. Si la mejor no llega a `UMBRAL = 0.34`, **no se llama al modelo**.
2. Si la pregunta trae vocabulario que **no existe** en la base (por ejemplo "cafetería"), el
   acierto tiene que ser contra la **pregunta** de la FAQ, no contra la respuesta.

Concepto: **recuperación primero, generación después (RAG)**. El modelo solo redacta sobre el texto
que se le entrega; la decisión de "no sé" la toma el código, no el modelo.

### Paso 8 — Historial y costo por consulta (PR #15)

Cada turno se guarda con `sesion` + `ts` y TTL de 7 días. El prompt incluye los últimos turnos para
que se entiendan los seguimientos ("¿y el de posgrado?"). En `Uso` se acumulan tokens de entrada y
salida, consultas y costo, y el chat muestra el gasto del mes en el pie.

Concepto: **costo por consulta = tokens × precio**. Con el modelo local el costo real es USD 0, pero
la fórmula y el contador quedan implementados para cuando se use un proveedor pago.

### Paso 9 — Panel de administración + HU-04 (PR #16)

`/admin` (HTML + JS simple) con tres pestañas: **FAQ** (crear/editar/borrar), **Sin respuesta**
(convertir una pregunta no respondida en FAQ) y, más adelante, **Consumo**.

El token **no está en el repo ni en el template**: al arrancar, el contenedor genera uno aleatorio y
lo guarda cifrado en SSM (`SecureString`). El panel lo pide; sin token, la API responde `401`.

Concepto: **los secretos no se versionan**. Se generan en ejecución y se guardan cifrados; se
consultan con `--with-decryption` solo cuando se necesitan.

### Paso 10 — Endurecer el guardrail y el arranque del token (PR #17)

Se ajustó la regla de vocabulario desconocido (que la "cafetería" no pase por parecerse a otra
respuesta) y el `Dockerfile` ejecuta `python -c 'import auth; auth.token()'` **antes** de gunicorn,
para que el token exista desde el primer segundo y no dependa de la primera petición.

### Paso 11 — Quitar lo que no se usaba (PR #19)

Se eliminaron un bucket S3 y un log group de CloudWatch que no aportaban a la demo. Los logs viven
en la EC2 (`docker logs`) y el costo bajó a **≈ USD 6,62/mes** con 8 h/día.

Concepto: **cada recurso se justifica**. Lo que no se usa se borra, incluso si "suena bien" tenerlo.

### Paso 12 — HU-03: tope de gasto con tres barreras (PR #20 y #21)

1. **AWS Budgets** `gtn-equipo-8-tope10-alertas` con dos alertas (`ACTUAL > 80 %`,
   `FORECASTED > 100 %`) hacia un tema SNS **sin suscriptores** (cumple el requisito sin mandar
   correos).
2. **Tope duro en la app**: la tabla `Uso` acumula el costo del mes; al llegar a `TOPE_GASTO_USD`
   (o 5 000 consultas) el chat responde `429` **sin llamar al modelo**.
3. **Rate limit** de 30 consultas/min por IP, también `429` con `Retry-After`.

Además, el panel ganó la pestaña **Consumo** (gastado, % del tope, restante, costo promedio,
consultas restantes) y `/api/uso` expuso esos campos.

Concepto: **defensa en capas**. El presupuesto avisa, el contador corta y el rate limit amortigua.
Ninguna capa depende de las otras.

> Detalle del nombre: CloudFormation **reemplaza** un `AWS::Budgets::Budget` cuando cambian sus
> notificaciones. Si el nombre no cambia, el alta choca con el anterior (`AlreadyExists`). Por eso el
> nombre incluye el monto y, si solo cambian las alertas, se cambia el sufijo.

### Paso 13 — CI con evaluación de calidad (PR #12, #16, #18)

Tres jobs en GitHub Actions:

| Job | Qué hace | Falla si |
|---|---|---|
| `lint-iac` | `cfn-lint iac/*.yaml` | hay un error de plantilla |
| `tests` | `pytest` con mocks | un test no pasa |
| `evaluacion` | corre las 10 preguntas y mide aciertos/alucinaciones | hay menos de 8/10 o alguna alucinación |

El resultado se publica como artefacto, se comenta en el PR y se agrega una fila al historial
(`docs/eval/historial.md`). Ese es el **punto extra** del enunciado.

Concepto: **calidad medida, no opinada**. Si un cambio de prompt empeora las respuestas, el PR se
pone rojo antes de mezclarse.

---

## 4. Resultado y límites (para decir la verdad en la sustentación)

| Aspecto | Estado |
|---|---|
| HU-01 chat con historial | ✅ en línea |
| HU-02 base de FAQ editable | ✅ panel `/admin` |
| HU-04 preguntas sin respuesta | ✅ pestaña + conversión a FAQ |
| HU-03 tope de gasto | ✅ presupuesto + contador + rate limit, probado en vivo |
| Evaluación automática | ✅ 10/10, 0 alucinaciones, en el CI |
| Costo | ✅ ≈ USD 6,62/mes con 8 h/día (≤ USD 10) |
| RNF p95 < 8 s | ❌ no se cumple con inferencia en CPU: ~20 s por respuesta, 20–40 s la primera |
| 24/7 real | ⚠️ depende de dejar la EC2 encendida; la arquitectura objetivo (Lambda + Bedrock) sí lo permite |

Los riesgos abiertos están en los issues #7 (RNF-01), #8 (RNF-02), #9 (RNF-03) y #10 (RNF-04).

---

## 5. Archivos que hay que saber ubicar

| Archivo | Qué contiene |
|---|---|
| `iac/main.yaml` | Todo el stack: red, tablas, EC2, presupuesto, SNS |
| `iac/README.md` | Desplegar, actualizar, detener, destruir, costos |
| `app/src/app.py` | Rutas del chat, panel y rate limit |
| `app/src/retrieval.py` | TF-IDF, sinónimos, umbral y guardrail |
| `app/src/llm.py` | Ollama / Bedrock, prompt y cálculo de costo |
| `app/src/store.py` | DynamoDB y contador de gasto |
| `app/src/auth.py` | Token del panel en SSM |
| `app/docker-compose.yml` | Contenedores `app` + `ollama` |
| `.github/workflows/ci.yml` | Los tres jobs del CI |
| `docs/prompt.md` · `docs/costos.md` · `docs/decisiones.md` | Prompt, costos medidos y decisiones |
