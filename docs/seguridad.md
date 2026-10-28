# Seguridad (RNF-03)

Auditoría del proyecto: qué se protege, con qué control, qué se verificó y qué queda como riesgo
aceptado. Complementa `docs/arquitectura.md` (sección 5) y `docs/decisiones.md`.

**Fecha de la revisión:** 28 de octubre de 2026 · cuenta `287834270100` · `us-east-1`.

---

## 1. Resumen

| Requisito del RNF-03 | Estado | Dónde |
|---|---|---|
| Ninguna credencial en el repositorio | ✅ cumplido | §2.1 |
| Token de administración en SSM SecureString | ✅ cumplido | §2.2 |
| Sin puerto 22 abierto; acceso por SSM | ✅ cumplido | §3 |
| Bucket S3 con acceso público bloqueado | ✅ no aplica: no hay buckets | §4 |
| Rol con permisos solo sobre lo necesario | ⚠️ **no cumplido**: el laboratorio impone `LabRole` | §5 |
| Auditoría de permisos con IAM Access Analyzer | ⚠️ **no disponible**: acción denegada en el laboratorio | §5.3 |
| Revisión de secretos en cada PR | ✅ cumplido (`.gitignore` + revisión + CI) | §2.1 |

Conclusión honesta: los controles que dependen del código y de la configuración del stack están
implementados y verificados. Los que dependen de IAM **no se pueden cumplir** en AWS Academy; se
documentan con controles compensatorios y con la política que se usaría en una cuenta real.

---

## 2. Secretos

### 2.1 Nada de credenciales en el repositorio

Verificado:

```bash
cd /tmp/opencode/gtn
cat .gitignore                 # ignora .env, .env.*, .aws/, *.pem, *.key
git log --all --oneline -- app/.env     # sin resultados: nunca se versionó
grep -rn "AKIA\|ASIA" --include="*.py" --include="*.yaml" --include="*.json" .   # solo el ejemplo "ASIA..." de la guía
grep -n "secrets\." .github/workflows/ci.yml    # sin resultados: el CI no usa secretos de AWS
```

- El `.env` se genera **en la EC2** durante el primer arranque, a partir de `UserData`; no está en git.
- El CI no necesita credenciales: los tests usan mocks y la evaluación de calidad corre sin modelo.
- `git-secrets` no está instalado; el control equivalente es la revisión del PR + `.gitignore` + el
  hecho de que ningún flujo escribe secretos en archivos versionados.

### 2.2 Token del panel

| Aspecto | Implementación |
|---|---|
| Generación | `secrets.token_urlsafe(24)` en el arranque del contenedor (192 bits) |
| Almacenamiento | SSM Parameter Store, tipo `SecureString` (cifrado con KMS `aws/ssm`) |
| Ruta | `/gtn/equipo-8/admin-token` (Output `ParametroTokenAdmin`) |
| Transporte | Cabecera `X-Admin-Token`; **nunca** en la URL ni en logs |
| Comparación | `hmac.compare_digest` (tiempo constante, evita ataques de temporización) |
| Cliente | `sessionStorage`, se borra al cerrar la pestaña |
| Sin token / inválido | `401` en todos los endpoints `/api/admin/*` |
| Rotación | `put-parameter --overwrite` + `docker compose restart app` |

```bash
# verificar que está cifrado
aws ssm describe-parameters --parameter-filters "Key=Name,Values=/gtn/equipo-8/admin-token" \
  --query 'Parameters[0].[Name,Type,LastModifiedDate]' --output table
# debe decir SecureString
```

El `Dockerfile` ejecuta `python -c 'import auth; auth.token()'` antes de gunicorn: el token existe
desde el primer segundo y los dos workers leen el mismo valor de SSM.

> `ADMIN_TOKEN` (variable de entorno) solo se usa en pruebas locales; no está definida en la EC2.

---

## 3. Red

| Control | Implementación | Evidencia |
|---|---|---|
| Puertos abiertos | Solo **TCP 80** desde `0.0.0.0/0` | `describe-security-groups` (§6) |
| SSH | **No existe**: puerto 22 cerrado, sin llaves ni key pair | Igual |
| Administración | SSM Session Manager (la EC2 inicia la conexión hacia afuera) | `aws ssm start-session --target i-02569431925a36c13` |
| Salida | Libre, necesaria para `dnf`, Docker Hub y la descarga del modelo | Regla egress `-1` |
| Metadatos | **IMDSv2 obligatorio** (`HttpTokens: required`) y `hop limit 2` para el contenedor | `MetadataOptions` en `iac/main.yaml` |
| Servicios expuestos | Solo la app; Ollama **no publica puertos** (solo red interna de compose) | `docker-compose.yml` |
| Punto de entrada del modelo | Inalcanzable desde Internet | `ollama` sin `ports:` |

Riesgo aceptado: el sitio va por **HTTP sin TLS**. En producción se pondría ALB + certificado ACM
(o CloudFront), lo que además permite WAF y ocultar la IP.

---

## 4. Datos

| Control | Implementación |
|---|---|
| Cifrado en reposo | `SSESpecification: SSEEnabled: true` en las 4 tablas |
| Cifrado del disco | Volumen EBS gp3 `Encrypted: true` |
| Retención | Historial con TTL (`expira`, 7 días) → se borra solo |
| Datos personales | No se piden nombre, correo ni documento; solo el texto de la pregunta y un `sesion` aleatorio del navegador |
| Acceso | Solo la app, con el instance profile; no hay acceso público a las tablas |
| Borrado | `DeletionPolicy: Delete` en las tablas + `DeleteOnTermination` en el disco |
| Buckets | **No hay** bucket S3 en el stack (se eliminó en el PR #19): nada que exponer |

```bash
aws dynamodb describe-table --table-name gtn-equipo-8-faq \
  --query 'Table.SSEDescription.Status' --output text     # ENABLED
aws dynamodb describe-time-to-live --table-name gtn-equipo-8-conversaciones \
  --query 'TimeToLiveDescription.[TimeToLiveStatus,AttributeName]' --output text
```

---

## 5. Identidad y permisos (el hallazgo principal)

### 5.1 Qué hace la app

La aplicación solo necesita:

| Acción | Recurso |
|---|---|
| `dynamodb:GetItem` `PutItem` `UpdateItem` `DeleteItem` `Query` `Scan` | las 4 tablas `gtn-equipo-8-*` |
| `ssm:GetParameter` `PutParameter` (`WithDecryption`) | `/gtn/equipo-8/admin-token` |
| `kms:Decrypt` (implícito) | clave administrada `aws/ssm` |

### 5.2 Qué tiene en realidad

La EC2 usa `LabInstanceProfile` → `LabRole`, un rol **preexistente y amplio** del laboratorio:

```
VocLabPolicy1 · VocLabPolicy2 · VocLabPolicy3
AmazonSSMManagedInstanceCore · AmazonEC2ContainerRegistryReadOnly
AmazonEKSClusterPolicy · AmazonEKSWorkerNodePolicy
```

No se puede crear un rol propio: `iam:CreateRole` responde `AccessDenied` en esta cuenta. Por eso el
template no crea roles y recibe el perfil por parámetro (`InstanceProfileName`, default
`LabInstanceProfile`).

**Controles compensatorios aplicados:**

1. La app nunca usa credenciales fijas: obtiene las del instance profile y solo llama a las 4 tablas
   y al parámetro del token (revisado en `store.py` y `auth.py`).
2. No hay usuarios IAM creados para el proyecto ni claves de acceso a largo plazo.
3. El contenedor corre como usuario sin privilegios (`uid 10001`), no `root`, sin `--privileged`.
4. IMDSv2 obligatorio: un proceso externo no puede pedir credenciales sin token de sesión.
5. La superficie de red es mínima (§3), así que el rol amplio no es alcanzable desde Internet.

### 5.3 Auditoría con IAM Access Analyzer

```bash
aws accessanalyzer list-analyzers --region us-east-1
# AccessDeniedException: no autorizado a access-analyzer:ListAnalyzers
```

La cuenta del laboratorio **no permite** Access Analyzer. La auditoría se hizo de forma manual:

```bash
aws iam list-attached-role-policies --role-name LabRole --output table
aws iam list-role-policies --role-name LabRole --output table
aws iam get-instance-profile --instance-profile-name LabInstanceProfile
```

No se encontraron roles, usuarios ni claves creados por el proyecto. El rol amplio es el único
hallazgo y es **impuesto por el entorno**, no una decisión de diseño.

### 5.4 Política que se usaría en una cuenta real

Documentada, no aplicada (el laboratorio no permite crear roles):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TablasDelProyecto",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                 "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:287834270100:table/gtn-equipo-8-faq",
        "arn:aws:dynamodb:us-east-1:287834270100:table/gtn-equipo-8-conversaciones",
        "arn:aws:dynamodb:us-east-1:287834270100:table/gtn-equipo-8-sin-respuesta",
        "arn:aws:dynamodb:us-east-1:287834270100:table/gtn-equipo-8-uso"
      ]
    },
    {
      "Sid": "TokenDelPanel",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:PutParameter"],
      "Resource": "arn:aws:ssm:us-east-1:287834270100:parameter/gtn/equipo-8/admin-token"
    },
    {
      "Sid": "DescifrarToken",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:287834270100:alias/aws/ssm"
    }
  ]
}
```

---

## 6. Evidencia de la revisión

```bash
# 1. Security group: solo 80, sin 22
aws ec2 describe-security-groups --filters "Name=tag:Equipo,Values=equipo-8" \
  --query 'SecurityGroups[].[GroupName,IpPermissions[].FromPort]' --output text
# gtn-equipo-8-GrupoSeguridadWeb-...   80

# 2. Sin buckets (nada que exponer)
aws s3api list-buckets --query 'Buckets[].Name' --output text
# (vacío)

# 3. Tablas cifradas y con TTL
aws dynamodb describe-table --table-name gtn-equipo-8-faq \
  --query 'Table.SSEDescription.Status' --output text          # ENABLED

# 4. Token como SecureString
aws ssm describe-parameters --parameter-filters "Key=Name,Values=/gtn/equipo-8/admin-token" \
  --query 'Parameters[0].Type' --output text                   # SecureString

# 5. SNS sin suscriptores (no se envía correo)
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-east-1:287834270100:gtn-equipo-8-alertas-gasto
# (vacío)

# 6. Sin secretos versionados
git log --all --oneline -- app/.env        # sin resultados
```

---

## 7. Riesgos aceptados y plan

| Riesgo | Impacto | Mitigación actual | Qué haría en producción |
|---|---|---|---|
| `LabRole` amplio | Un compromiso de la EC2 tendría más permisos de los necesarios | Red mínima, IMDSv2, contenedor sin privilegios, sin claves | Rol propio con la política de §5.4 + Access Analyzer |
| HTTP sin TLS | Interceptación del tráfico y del token del panel | Red del laboratorio, uso académico | ALB + ACM o CloudFront; forzar HTTPS |
| Token compartido | Sin trazabilidad por persona ni revocación individual | 192 bits, SSM cifrado, `401`, rotación documentada | Cognito o firma, roles y auditoría por usuario |
| Rate limit en memoria | Se reinicia con el contenedor y no es distribuido | Suficiente para una instancia | API Gateway / WAF con límites por API key |
| Dependencias con rango (`flask==3.*`) | Una versión nueva podría romper el build | CI construye la imagen en cada PR | Fijar versiones exactas + Dependabot |
| Sin WAF ni protección DDoS | Abuso del endpoint público | Tope de gasto y rate limit | AWS WAF + Shield (capa gratuita/estándar) |
| Evaluación de calidad offline | No mide la latencia real | Se corre aparte contra el servicio | Job de humo post-despliegue |

---

## 8. Respuesta ante incidentes (procedimiento corto)

```bash
# 1. Rotar el token del panel
aws ssm put-parameter --name /gtn/equipo-8/admin-token --type SecureString \
  --value "$(openssl rand -base64 24)" --overwrite
# 2. Aplicarlo (por SSM)
#    cd /opt/gtn/src/app && docker compose restart app

# 3. Si se comprometió la instancia: aislarla y recrearla
aws ec2 stop-instances --instance-ids i-02569431925a36c13
aws ec2 modify-instance-attribute --instance-id i-02569431925a36c13 \
  --groups sg-xxxxxxxx          # SG sin reglas de entrada
aws cloudformation delete-stack --stack-name gtn-equipo-8    # recrear desde el template

# 4. Si se filtró una credencial del laboratorio: End Lab y volver a iniciar
# 5. Revisar qué se gastó
aws budgets describe-budget --account-id 287834270100 \
  --budget-name gtn-equipo-8-tope10-alertas \
  --query 'Budget.CalculatedSpend'
```

---

## 9. Checklist para el PR de cualquier cambio

- [ ] No se agregó ningún `.env`, llave, token ni credencial.
- [ ] Si se agregó un recurso, tiene los 4 tags y el permiso mínimo necesario.
- [ ] Si se agregó un endpoint, valida entrada y responde `401`/`400` cuando corresponde.
- [ ] `cfn-lint iac/*.yaml` y `pytest` en verde.
- [ ] Si cambia el modelo o el prompt, la evaluación sigue en ≥ 8/10 y sin alucinaciones.
