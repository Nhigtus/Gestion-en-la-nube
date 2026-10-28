"""Acceso a DynamoDB: FAQ, historial, preguntas sin respuesta y contador de uso."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
TABLA_FAQ = os.getenv("TABLA_FAQ", "gtn-equipo-8-faq")
TABLA_CONV = os.getenv("TABLA_CONVERSACIONES", "gtn-equipo-8-conversaciones")
TABLA_SIN = os.getenv("TABLA_SIN_RESPUESTA", "gtn-equipo-8-sin-respuesta")
TABLA_USO = os.getenv("TABLA_USO", "gtn-equipo-8-uso")

TOPE_USD = Decimal(os.getenv("TOPE_GASTO_USD", "10"))
MAX_CONSULTAS_MES = int(os.getenv("MAX_CONSULTAS_MES", "5000"))
DIAS_HISTORIAL = 30

# Precios públicos por millón de tokens (us-east-1, octubre 2026).
PRECIOS = {
    "bedrock": (Decimal("0.035"), Decimal("0.14")),  # Amazon Nova Micro
    "ollama": (Decimal("0"), Decimal("0")),  # corre en la EC2, sin costo por token
}

_recurso = None


def _db():
    global _recurso
    if _recurso is None:
        _recurso = boto3.resource("dynamodb", region_name=REGION)
    return _recurso


def _tabla(nombre: str):
    return _db().Table(nombre)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _mes() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ------------------------------------------------------------------ FAQ
def listar_faq() -> list[dict]:
    items: list[dict] = []
    args = {}
    while True:
        r = _tabla(TABLA_FAQ).scan(**args)
        items.extend(r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            break
        args["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return sorted(items, key=lambda f: f.get("id", ""))


def guardar_faqs(items: list[dict]) -> int:
    with _tabla(TABLA_FAQ).batch_writer() as lote:
        for item in items:
            lote.put_item(Item=item)
    return len(items)


# ---------------------------------------------------------- conversaciones
def guardar_turno(
    sesion: str,
    rol: str,
    texto: str,
    fuentes: list[dict] | None = None,
    latencia_ms: int | None = None,
) -> None:
    item = {
        "sesion": sesion,
        "ts": _ahora(),
        "rol": rol,
        "texto": texto[:4000],
        "expira": int(time.time()) + DIAS_HISTORIAL * 86400,
    }
    if fuentes:
        item["fuentes"] = [{"id": f["id"], "pregunta": f["pregunta"]} for f in fuentes]
    if latencia_ms is not None:
        item["latencia_ms"] = latencia_ms
    _tabla(TABLA_CONV).put_item(Item=item)


def historial(sesion: str, limite: int = 20) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    r = _tabla(TABLA_CONV).query(
        KeyConditionExpression=Key("sesion").eq(sesion),
        ScanIndexForward=False,
        Limit=limite,
    )
    return list(reversed(r.get("Items", [])))


# ------------------------------------------------------- sin respuesta
def registrar_sin_respuesta(pregunta: str, sesion: str) -> None:
    limpia = " ".join(pregunta.lower().split())[:300]
    ident = hashlib.sha1(limpia.encode("utf-8")).hexdigest()[:16]
    _tabla(TABLA_SIN).update_item(
        Key={"id": ident},
        UpdateExpression=(
            "SET pregunta = :p, ultima_vez = :t, "
            "primera_vez = if_not_exists(primera_vez, :t) "
            "ADD veces :uno"
        ),
        ExpressionAttributeValues={
            ":p": pregunta[:300],
            ":t": _ahora(),
            ":uno": 1,
        },
    )


def listar_sin_respuesta(limite: int = 50) -> list[dict]:
    items = _tabla(TABLA_SIN).scan().get("Items", [])
    return sorted(items, key=lambda x: int(x.get("veces", 0)), reverse=True)[:limite]


# ------------------------------------------------------------------ uso
def calcular_costo(tokens_entrada: int, tokens_salida: int, proveedor: str) -> Decimal:
    precio_in, precio_out = PRECIOS.get(proveedor, (Decimal("0"), Decimal("0")))
    costo = (Decimal(tokens_entrada) * precio_in + Decimal(tokens_salida) * precio_out) / Decimal(
        1_000_000
    )
    return costo.quantize(Decimal("0.000001"))


def sumar_uso(tokens_entrada: int, tokens_salida: int, costo: Decimal) -> None:
    _tabla(TABLA_USO).update_item(
        Key={"mes": _mes()},
        UpdateExpression=(
            "ADD consultas :uno, tokens_entrada :tin, tokens_salida :tout, costo_usd :costo"
        ),
        ExpressionAttributeValues={
            ":uno": 1,
            ":tin": tokens_entrada,
            ":tout": tokens_salida,
            ":costo": costo,
        },
    )


def uso_del_mes() -> dict:
    r = _tabla(TABLA_USO).get_item(Key={"mes": _mes()})
    item = r.get("Item", {})
    return {
        "mes": _mes(),
        "consultas": int(item.get("consultas", 0)),
        "tokens_entrada": int(item.get("tokens_entrada", 0)),
        "tokens_salida": int(item.get("tokens_salida", 0)),
        "costo_usd": float(item.get("costo_usd", 0)),
        "tope_usd": float(TOPE_USD),
        "max_consultas": MAX_CONSULTAS_MES,
    }


def dentro_de_presupuesto() -> bool:
    uso = uso_del_mes()
    return uso["costo_usd"] < uso["tope_usd"] and uso["consultas"] < uso["max_consultas"]
