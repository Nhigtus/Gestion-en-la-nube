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
  --stack-name gtn-juanes \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      NombreEquipo=juanes \
      NumeroProyecto=NN \
      EmailAlerta=director@ejemplo.com \
      TopeGastoUSD=10
```

Ver el progreso y los errores:

```bash
aws cloudformation describe-stack-events --stack-name gtn-juanes \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
  --output table

aws cloudformation describe-stacks --stack-name gtn-juanes \
  --query 'Stacks[0].Outputs' --output table
```

## Actualizar

```bash
aws cloudformation deploy ...   # mismo comando: es idempotente
```

Los cambios de infraestructura entran por PR; el CI corre `cfn-lint` y un `change set` manual antes de aplicar.

## Detener (ahorrar crédito)

Este stack no tiene cómputo permanente (hito 0). Cuando exista la EC2 del hito 6–7:

```bash
aws ec2 stop-instances --instance-ids <id>          # detener
aws ec2 start-instances --instance-ids <id>         # encender
```

## Destruir

```bash
aws cloudformation delete-stack --stack-name gtn-juanes
aws cloudformation wait stack-delete-complete --stack-name gtn-juanes
```

Comprobar que no quedó nada cobrando:

```bash
aws cloudformation list-stacks --stack-status-filter DELETE_FAILED --output table
aws ec2 describe-instances --filters "Name=tag:Equipo,Values=juanes" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
```

> El bucket S3 tiene versionado: si se guardaron objetos, hay que vaciarlo antes de borrar el stack
> (`aws s3 rm s3://<bucket> --recursive`) o el `delete-stack` fallará.

## Costo estimado

| Fase | Recursos con costo | USD/mes |
|---|---|---|
| Hito 0 (este stack) | DynamoDB on-demand (casi 0), S3 (centavos), Logs 7 días, Budgets (gratis) | ≈ 0,05 |
| Con API + Lambda + Bedrock (10k consultas) | + Bedrock ≈ 0,95, Logs ≈ 0,50 | ≈ 1,50 |
| Con EC2 del hito 6–7 (8 h/día) | + t3.micro 2,50 + EBS 0,64 | ≈ 4,64 |

Tope duro configurado: `TopeGastoUSD` (10) con alarma al 80 % y proyección al 100 %.
