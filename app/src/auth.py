"""Token del panel de administración.

No vive en el repositorio ni en la plantilla: la primera vez se genera al azar
y se guarda cifrado (SecureString) en SSM Parameter Store. Para verlo:

    aws ssm get-parameter --name /gtn/equipo-8/admin-token --with-decryption \
        --query Parameter.Value --output text

Si la variable ADMIN_TOKEN está definida (solo para pruebas locales), se usa esa.
"""

from __future__ import annotations

import hmac
import os
import secrets

import boto3
from botocore.config import Config

PARAMETRO = os.getenv("PARAMETRO_TOKEN_ADMIN", "/gtn/equipo-8/admin-token")
REGION = os.getenv("AWS_REGION", "us-east-1")

_cache: str | None = None
_cliente = None


def _ssm():
    global _cliente
    if _cliente is None:
        _cliente = boto3.client(
            "ssm",
            region_name=REGION,
            config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
        )
    return _cliente


def _leer() -> str:
    return _ssm().get_parameter(Name=PARAMETRO, WithDecryption=True)["Parameter"]["Value"]


def token() -> str:
    """Token vigente; lo crea si no existe (idempotente entre los workers)."""
    global _cache
    if _cache:
        return _cache
    if os.getenv("ADMIN_TOKEN"):
        _cache = os.environ["ADMIN_TOKEN"]
        return _cache

    try:
        _cache = _leer()
        return _cache
    except Exception:
        pass

    nuevo = secrets.token_urlsafe(24)
    try:
        _ssm().put_parameter(
            Name=PARAMETRO, Type="SecureString", Value=nuevo, Overwrite=False
        )
        _cache = nuevo
    except Exception:
        # Otro worker lo creó primero (ParameterAlreadyExists) o SSM no responde:
        # si existe se reutiliza el guardado; si no, sólo este worker lo conoce.
        try:
            _cache = _leer()
        except Exception:
            _cache = nuevo
    return _cache


def autorizado(valor: str | None) -> bool:
    """Compara en tiempo constante y nunca acepta un token vacío."""
    if not valor:
        return False
    return hmac.compare_digest(str(valor), token())
