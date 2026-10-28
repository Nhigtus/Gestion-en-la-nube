"""Carga inicial de la base de FAQ en DynamoDB (idempotente)."""

from __future__ import annotations

import json
from pathlib import Path

import store

RUTA = Path(__file__).resolve().parent / "data" / "faq.json"


def cargar_si_vacia() -> int:
    if store.listar_faq():
        return 0
    datos = json.loads(RUTA.read_text(encoding="utf-8"))
    items = [
        {
            "id": f"faq-{i:03d}",
            "pregunta": faq["pregunta"],
            "respuesta": faq["respuesta"],
            "categoria": faq.get("categoria", "general"),
            "activa": True,
        }
        for i, faq in enumerate(datos["faqs"], 1)
    ]
    return store.guardar_faqs(items)
