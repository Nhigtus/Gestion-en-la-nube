# Guía de operación — encender, apagar, conectarse y modificar

Todo lo necesario para operar el proyecto **sin ayuda de nadie**. Si algo falla, salta a la sección 8.

> Regla de oro: **la EC2 es lo único que cobra por hora**. Si terminas de probar, apágala.
> Y las credenciales del laboratorio duran ~4 h: si un comando dice `ExpiredToken`, vuelve a copiarlas.

---

## 0. Antes de empezar

### 0.1 Credenciales del laboratorio (cada ~4 h)

1. Entra al aula virtual → **AWS Academy Learner Lab** → **Start Lab** (espera el punto verde).
2. Botón **AWS Details** → **AWS CLI: Show**.
3. Copia el bloque en `~/.aws/credentials` o expórtalo:

```bash
export AWS_ACCESS_KEY_ID="ASIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
```

Comprobar que sirven:

```bash
aws sts get-caller-identity
# Debe decir la cuenta 287834270100 y el rol voclabs
```

### 0.2 Herramientas

```bash
aws --version            # AWS CLI v2
git --version
cfn-lint --version       # pipx install cfn-lint  (solo si vas a tocar iac/)
```

Para conectarte a la EC2 hace falta el **plugin de Session Manager** (una sola vez):

```bash
curl -sSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/linux_64bit/session-manager-plugin.rpm" -o /tmp/sm.rpm
sudo dnf install -y /tmp/sm.rpm     # en Ubuntu/Debian usa el .deb del mismo sitio
session-manager-plugin --version
```

### 0.3 Los tres datos que siempre necesitas

```bash
# ID de la instancia (no cambia nunca)
ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Equipo,Values=equipo-8" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
echo "$ID"     # i-02569431925a36c13
```

| Dato | Valor / cómo obtenerlo |
|---|---|
| Stack | `gtn-equipo-8` |
| Instancia | `i-02569431925a36c13` |
| IP pública | **cambia en cada encendido** → se lee con el comando de la sección 1 |
| Token del panel | `aws ssm get-parameter --name /gtn/equipo-8/admin-token --with-decryption --query Parameter.Value --output text` |

---

## 1. Encender

```bash
export AWS_REGION=us-east-1
ID=i-02569431925a36c13

aws ec2 start-instances --instance-ids $ID
aws ec2 wait instance-running --instance-ids $ID

# IP nueva
IP=$(aws ec2 describe-instances --instance-ids $ID \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "Chat:  http://$IP/"
echo "Panel: http://$IP/admin"
```

Los contenedores arrancan solos (Docker está habilitado en el boot y `restart: unless-stopped`),
pero tardan **1–2 minutos**. Espera a que el health check responda:

```bash
for i in $(seq 1 30); do
  H=$(curl -sS -m 5 "http://$IP/health" 2>/dev/null)
  echo "$H" | grep -q '"status":"ok"' && { echo "LISTO: $H"; break; }
  echo "[$i] esperando..."; sleep 10
done
```

Cuando salga `{"status":"ok", ...}` ya puedes entrar.

> **La primera pregunta tarda 20–40 s** porque el modelo se carga en RAM. Las siguientes ~20 s.
> Si quieres que la demo se sienta rápida, haz una consulta de calentamiento antes de presentar.

---

## 2. Entrar al chat y al panel

| Qué | URL | Qué hacer |
|---|---|---|
| Chat | `http://<IP>/` | Escribir la pregunta y enviar |
| Panel | `http://<IP>/admin` | Pegar el token cuando lo pida |

Token:

```bash
aws ssm get-parameter --name /gtn/equipo-8/admin-token \
  --with-decryption --query Parameter.Value --output text
```

El panel tiene tres pestañas: **FAQ**, **Sin respuesta** y **Consumo**.

Pruebas recomendadas para la demo:

| Pregunta | Resultado esperado |
|---|---|
| ¿Cuánto vale el semestre? | Responde con matrícula de pregrado y posgrado |
| ¿Cuándo son las inscripciones? | Responde con fechas |
| ¿Tienen cafetería en el campus? | Dice que no tiene esa información (no inventa) |
| ¿Quién ganó el mundial de fútbol? | Rechaza por estar fuera de la base |

---

## 3. Apagar

```bash
aws ec2 stop-instances --instance-ids i-02569431925a36c13
aws ec2 wait instance-stopped --instance-ids i-02569431925a36c13
aws ec2 describe-instances --instance-ids i-02569431925a36c13 \
  --query 'Reservations[0].Instances[0].State.Name' --output text   # stopped
```

Qué pasa al apagar:
- La IP pública **se pierde**; al encender hay una nueva.
- El disco (EBS) y el volumen del modelo **se conservan**.
- Los datos viven en DynamoDB, no en la EC2: nada se pierde.
- El costo baja a ≈ USD 0,03/mes (solo DynamoDB).

---

## 4. Conectarse a la EC2 (SSM, sin SSH)

El puerto 22 está cerrado y no hay llaves. Se entra por **Session Manager**:

```bash
aws ssm start-session --target i-02569431925a36c13
```

Ya dentro (el usuario es `ssm-user`):

```bash
sudo -i                                   # pasar a root
cd /opt/gtn/src/app

docker compose ps                         # ¿están app y ollama arriba?
docker compose logs --tail=100 app        # logs de la aplicación
docker compose logs --tail=50 ollama
docker compose exec -T ollama ollama list # modelos descargados
curl -s localhost/health                  # salud desde el propio servidor
free -h && df -h                          # RAM/swap y disco
cat /var/log/gtn-bootstrap.log            # qué hizo el UserData en el primer arranque
```

Para salir: `exit` dos veces, o `Ctrl+D`.

> Si `start-session` falla con `TargetNotConnected`, la instancia aún está arrancando o el agente SSM
> no ha levantado: espera 1–2 min. Si falla con `ExpiredToken`, renueva las credenciales.

---

## 5. Modificar

### 5.1 Cambiar la base de FAQ (lo normal, sin desplegar nada)

1. Abre `http://<IP>/admin` y pega el token.
2. Pestaña **FAQ** → *Nueva* / editar / borrar.
3. Los cambios son inmediatos: la app lee DynamoDB en cada consulta.
4. Pestaña **Sin respuesta** → botón *Convertir en FAQ* para las preguntas que no supo contestar.

No hay que reiniciar, ni desplegar, ni tocar código.

### 5.2 Cambiar el código de la app (flujo correcto)

El cambio se hace en el repo y se aplica en la EC2 **sin recrear la instancia**.

```bash
# 1) en tu máquina
git pull                                   # el CI commitea historial de evaluación en main
git checkout -b fix/mi-cambio
# ... editas app/...
pytest app/tests -q
git add -A && git commit -m "fix: ..."
git push -u origin fix/mi-cambio
# 2) abres el PR; espera CI en verde (cfn-lint + tests + evaluación) y mezcla
```

```bash
# 3) en la EC2, por SSM
sudo -i
cd /opt/gtn/src
git pull --ff-only
cd app
docker compose up -d --build
docker compose logs --tail=50 app
```

El `--build` reconstruye la imagen con el código nuevo y reinicia solo el contenedor `app`.
El modelo y las FAQ no se tocan.

> Si `git pull` se queja de cambios locales, fuerza el estado del repo **sin borrar el `.env`**
> (es un archivo ignorado, sobrevive):
>
> ```bash
> cd /opt/gtn/src && git fetch origin main && git reset --hard origin/main
> ```

### 5.3 Cambiar infraestructura (CloudFormation)

Se edita `iac/main.yaml`, se valida y se despliega. **Siempre por PR.**

```bash
cfn-lint iac/*.yaml
git checkout -b infra/mi-cambio && git add -A && git commit -m "infra: ..." && git push -u origin infra/mi-cambio
# PR → CI verde → merge
```

```bash
# ¡La EC2 debe estar encendida! Si está apagada, los Outputs con PublicIp hacen fallar el update.
aws ec2 start-instances --instance-ids i-02569431925a36c13
aws ec2 wait instance-running --instance-ids i-02569431925a36c13

aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-equipo-8 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides NombreEquipo=equipo-8 NumeroProyecto=08
```

```bash
# si algo falla, mirar el evento exacto
aws cloudformation describe-stack-events --stack-name gtn-equipo-8 \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`||ResourceStatus==`UPDATE_FAILED`].[Timestamp,LogicalResourceId,ResourceStatusReason]' \
  --output table

# al terminar, apagar
aws ec2 stop-instances --instance-ids i-02569431925a36c13
```

Cosas que **no** se pueden hacer en este laboratorio: crear roles IAM (`iam:CreateRole` denegado) ni
usar Bedrock. Por eso el template usa `LabInstanceProfile` y `ProveedorLLM=ollama`.

> **Presupuesto:** CloudFormation reemplaza `AWS::Budgets::Budget` cuando cambian las alertas. Si el
> nombre no cambia, el deploy falla con `AlreadyExists`. Si cambias **solo las alertas**, cambia el
> sufijo del nombre en `iac/main.yaml` (por ejemplo `-alertas2`) antes de desplegar.

### 5.4 Cambiar el modelo de lenguaje

El modelo se descarga en un volumen, así que se puede cambiar en caliente:

```bash
# en la EC2, por SSM
sudo -i && cd /opt/gtn/src/app
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct     # o el que quieras
sed -i 's/^MODELO=.*/MODELO=qwen2.5:3b-instruct/' .env
docker compose up -d          # recrea la app con el nuevo MODELO
curl -s localhost/health
```

Para que quede reproducible, actualiza también `ModeloOllama` en `iac/main.yaml` y despliega. Ojo:
`t3.small` tiene 2 GB de RAM; un modelo de 3B puede ir muy lento o quedarse sin memoria (hay 2 GB
de swap). Si necesitas más, cambia `TipoInstancia` a `t3.medium`.

### 5.5 Rotar el token del panel

```bash
aws ssm put-parameter --name /gtn/equipo-8/admin-token --type SecureString \
  --value "$(openssl rand -base64 24)" --overwrite
```

```bash
# en la EC2: el contenedor relee el parámetro al reiniciar
sudo -i && cd /opt/gtn/src/app && docker compose restart app
```

### 5.6 Cambiar comportamiento sin tocar código

El `.env` de la EC2 (`/opt/gtn/src/app/.env`) controla la app. Variables útiles:

| Variable | Default | Para qué |
|---|---|---|
| `RATE_MAX_POR_MINUTO` | 30 | consultas por IP por minuto (×2 workers ≈ 60 efectivas) |
| `RATE_VENTANA_SEGUNDOS` | 60 | ventana del rate limit |
| `TOPE_GASTO_USD` | 10 | tope duro del mes; al llegar responde `429` |
| `MAX_CONSULTAS_MES` | 5000 | tope de consultas del mes |
| `MAX_TOKENS` | 300 | longitud máxima de la respuesta |
| `LLM_TIMEOUT` | 120 | segundos de espera al modelo |
| `MODELO` | qwen2.5:1.5b-instruct | modelo de Ollama |

```bash
sudo -i && cd /opt/gtn/src/app
nano .env
docker compose up -d          # recrea el contenedor con las variables nuevas
```

> Ese `.env` lo escribió el UserData **solo en el primer arranque**. Si lo editas a mano, el cambio
> vive en la EC2 pero no en el template: anótalo o refléjalo en `iac/main.yaml` para no perderlo al
> recrear la instancia.

---

## 6. Ver costos y el tope

```bash
# gasto real y proyectado del presupuesto
aws budgets describe-budget --account-id 287834270100 \
  --budget-name gtn-equipo-8-tope10-alertas \
  --query 'Budget.{Nombre:BudgetName,Limite:BudgetLimit.Amount,Real:CalculatedSpend.ActualSpend.Amount,Proyectado:CalculatedSpend.ForecastedSpend.Amount}' \
  --output table

# alertas configuradas (deben ser ACTUAL 80 y FORECASTED 100)
aws budgets describe-notifications-for-budget --account-id 287834270100 \
  --budget-name gtn-equipo-8-tope10-alertas --output table

# el tema SNS no tiene suscriptores: no se envía ningún correo
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-east-1:287834270100:gtn-equipo-8-alertas-gasto
```

Dentro de la app:

```bash
curl -s http://<IP>/api/uso | jq
```

Devuelve gasto, `porcentaje_usado`, `restante_usd`, `costo_promedio`, `consultas_restantes`.

---

## 7. Ver el estado general en un comando

```bash
aws cloudformation describe-stacks --stack-name gtn-equipo-8 \
  --query 'Stacks[0].[StackStatus,Outputs]' --output yaml
```

Outputs esperados: `UrlDemo`, `IpPublica`, `PanelAdmin`, `ParametroTokenAdmin`, nombres de tablas.

---

## 8. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| El navegador no conecta / `502` | contenedores aún arrancando | esperar 1–2 min y repetir el bucle de `/health` |
| `/health` responde pero el chat tarda muchísimo | el modelo se está cargando (cold start) | esperar; la primera consulta tarda 20–40 s |
| `429` al preguntar rápido | rate limit (30/min por IP) | esperar el `Retry-After`; es intencional |
| `429` con mensaje de tope de gasto | se alcanzó `TOPE_GASTO_USD` o 5 000 consultas | revisar `/api/uso`; el contador está en la tabla `Uso` |
| Panel responde `401` | token ausente o incorrecto | sacarlo de SSM y volver a pegarlo |
| El token de SSM no existe | se borró el parámetro | reiniciar `app` (lo regenera) o `put-parameter` |
| `aws cloudformation deploy` falla con `Attribute 'PublicIp' does not exist` | la EC2 está apagada y los Outputs leen su IP | encender la instancia, desplegar, apagar |
| El deploy falla con `AlreadyExists` en el presupuesto | cambió la alerta pero no el nombre | cambiar el sufijo del nombre en `iac/main.yaml` |
| `aws ssm start-session` → `ExpiredToken` | credenciales de laboratorio vencidas | volver a copiarlas desde AWS Details |
| `docker compose up` falla por `buildx` | plugin ausente en AL2023 | volver a correr el bloque de `UserData` o instalar el plugin |
| La app no accede a DynamoDB | IMDS inalcanzable desde el contenedor | verificar `HttpPutResponseHopLimit: 2` en `MetadataOptions` |
| Disco lleno | imágenes viejas + modelo | `docker system prune -af` (cuidado: borra imágenes; el modelo está en un volumen aparte) |
| Cambié el código pero no se refleja | no se reconstruyó la imagen | `cd /opt/gtn/src/app && docker compose up -d --build` |

---

## 9. Destruir todo (fin del semestre)

```bash
# 1) borrar el stack (red, EC2, tablas, presupuesto, SNS, alertas)
aws cloudformation delete-stack --stack-name gtn-equipo-8
aws cloudformation wait stack-delete-complete --stack-name gtn-equipo-8

# 2) el token lo creó la app, no el stack: borrarlo aparte
aws ssm delete-parameter --name /gtn/equipo-8/admin-token

# 3) comprobar que no quedó nada cobrando
aws cloudformation list-stacks --stack-status-filter DELETE_FAILED --output table
aws ec2 describe-instances --filters "Name=tag:Equipo,Values=equipo-8" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
```

Las tablas tienen `DeletionPolicy: Delete`, así que se van con el stack. No hay bucket ni log group
que vaciar (se eliminaron en el PR #19).

> **No tocar** los recursos que ya existían en la cuenta y no son del proyecto: la instancia
> `t3.micro` "JJ" (`i-06060fd521552fb1e`) y las Lambda `RedshiftSNS` / `RedshiftOverwatch`.

---

## 10. Checklist de cada sesión

**Al empezar**
1. Start Lab y copiar credenciales → `aws sts get-caller-identity`.
2. `aws ec2 start-instances` → esperar → leer la IP nueva.
3. Bucle de `/health` hasta `"status":"ok"`.
4. Sacar el token de SSM y abrir chat + panel.

**Al terminar**
1. `aws ec2 stop-instances --instance-ids i-02569431925a36c13`.
2. Confirmar `stopped` con `describe-instances`.
3. Si tocaste infraestructura: `git status` limpio, PR mezclado y CI en verde.
