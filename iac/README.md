# IaC — CloudFormation

Todo el entorno entregable vive en este directorio y se reproduce desde cero con un comando.

## Convenciones

- YAML de CloudFormation, un template principal (`main.yaml`) y stacks anidados por capa cuando crezca:
  `main.yaml` (orquesta) → `red.yaml` · `datos.yaml` · `computo.yaml` · `frontend.yaml`.
- **Todo lo variable va en `Parameters`**; lo que consumen otras capas, en `Outputs` (con `Export`).
- **Tags obligatorios en todos los recursos**: `Curso: GTN-2026-2`, `Equipo`, `Proyecto`, `Ambiente`.
- `DeletionPolicy: Delete` en recursos de laboratorio para que `delete-stack` no deje basura cobrando.
- Validar antes de cada PR: `cfn-lint iac/*.yaml` (el CI lo corre igual).

## Requisitos

- AWS CLI v2 y credenciales válidas (`aws sts get-caller-identity` debe responder).
- `cfn-lint` (`pipx install cfn-lint` o `pip install --user cfn-lint`).
- Permiso para crear los recursos del stack; el despliegue usa `CAPABILITY_NAMED_IAM`.

## Desplegar

```bash
export AWS_REGION=us-east-1

aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-equipo-8 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      NombreEquipo=equipo-8 \
      NumeroProyecto=NN \
      TopeGastoUSD=10
```

Ver el progreso y los errores:

```bash
aws cloudformation describe-stack-events --stack-name gtn-equipo-8 \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
  --output table

aws cloudformation describe-stacks --stack-name gtn-equipo-8 \
  --query 'Stacks[0].Outputs' --output table
```

## Actualizar

```bash
aws cloudformation deploy ...   # mismo comando: es idempotente
```

Los cambios de infraestructura entran por PR; el CI corre `cfn-lint` y un `change set` manual antes de aplicar.

> La EC2 exige **IMDSv2** (`HttpTokens: required`) con `HttpPutResponseHopLimit: 2`, definido en
> `MetadataOptions`. Es lo que permite que el contenedor de la app obtenga las credenciales de
> `LabRole` para hablar con DynamoDB.

## Panel de administración (token fuera del repo)

La plantilla no contiene ningún token: la primera vez que la app atiende una petición de
administración genera uno al azar y lo guarda cifrado (`SecureString`) en SSM, en la ruta del
Output `ParametroTokenAdmin` (`/gtn/equipo-8/admin-token`).

```bash
aws ssm get-parameter --name /gtn/equipo-8/admin-token \
  --with-decryption --query Parameter.Value --output text
# abrir http://<IpPublica>/admin y pegar el token
```

Rotarlo cuando haga falta (el contenedor lo relee al reiniciar):

```bash
aws ssm put-parameter --name /gtn/equipo-8/admin-token --type SecureString \
  --value "$(openssl rand -base64 24)" --overwrite
docker compose -f /opt/gtn/src/app/docker-compose.yml restart app
```

## Evaluación de calidad

El set de 10 preguntas vive en `tests/eval/` y lo corre el job `evaluacion` del CI (mínimo 8/10).
En local, sin modelo:

```bash
python app/eval/evaluar.py
python app/eval/evaluar.py --simular-regresion   # debe salir con código 1
```

## Detener (ahorrar crédito)

La EC2 es el único recurso que cobra por tiempo. Apágala al terminar cada sesión:

```bash
aws ec2 stop-instances --instance-ids <IdInstancia>
aws ec2 start-instances --instance-ids <IdInstancia>
aws ec2 describe-instances --instance-ids <IdInstancia> \
  --query 'Reservations[].Instances[].[State.Name,PublicIpAddress]' --output table
```

> La IP pública cambia al detener/encender: el Output `UrlDemo` se consulta después de arrancar.
> Los contenedores vuelven solos (`restart: unless-stopped` + Docker habilitado en el arranque),
> pero la app puede tardar 1-2 min y el modelo se recarga en la primera consulta.

## Destruir

```bash
aws cloudformation delete-stack --stack-name gtn-equipo-8
aws cloudformation wait stack-delete-complete --stack-name gtn-equipo-8
```

Comprobar que no quedó nada cobrando:

```bash
aws cloudformation list-stacks --stack-status-filter DELETE_FAILED --output table
aws ec2 describe-instances --filters "Name=tag:Equipo,Values=equipo-8" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
```

> El bucket S3 tiene versionado: si se guardaron objetos, hay que vaciarlo antes de borrar el stack
> (`aws s3 rm s3://<bucket> --recursive`) o el `delete-stack` fallará.

## Costo estimado

| Fase | Recursos con costo | USD/mes |
|---|---|---|
| Stack completo, EC2 8 h/día | t3.small 240 h (4,99) + EBS 20 GB (1,60) + DynamoDB/S3/Logs (~0,54) | **≈ 7,13** |
| Stack completo, EC2 24/7 | t3.small 730 h (15,18) + EBS (1,60) + resto | ≈ 17,32 |
| Sólo datos (EC2 apagada todo el mes) | DynamoDB/S3/Logs | ≈ 0,55 |
| Arquitectura objetivo con Bedrock | Lambda + API Gateway + DynamoDB + Bedrock | ≈ 1,50 |

Tope configurado: `TopeGastoUSD` (10) en AWS Budgets, sin suscripciones ni correos.
El laboratorio tiene además su propio límite de crédito por cuenta.

## Límites del laboratorio (importante)

| Límite | Cómo lo resuelve el template |
|---|---|
| No se pueden crear roles IAM (`iam:CreateRole` denegado) | Parámetro `InstanceProfileName` (default `LabInstanceProfile`) y Lambda con `LabRole` |
| Bedrock denegado | Parámetro `ProveedorLLM=ollama` y modelo en contenedor |
| Sesión de 4 h y crédito limitado | `DeletionPolicy: Delete`, EC2 apagable, logs de 7 días, sin NAT ni ALB |
| La IP pública cambia | El Output `UrlDemo` se lee después de cada arranque |
| No se pueden crear roles IAM | El token del panel y las credenciales de la app usan `LabRole` + SSM |
