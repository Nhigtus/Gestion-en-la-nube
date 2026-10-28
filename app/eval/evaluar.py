#!/usr/bin/env python3
"""Evaluación automática de calidad del chat de FAQ.

Dos modos:

* `offline` (por defecto, el que corre en CI): evalúa la recuperación y el
  guardarraíl con `app/src/retrieval.py` sobre `app/data/faq.json`. No usa red,
  ni modelo, ni credenciales: es determinista y tarda menos de un segundo.
* `--url http://host`: llama al endpoint `/api/chat` real y comprueba las
  fuentes citadas y el mensaje fijo de las preguntas fuera de la base.

Un acierto exige que la FAQ esperada esté entre las 5 que recibe el modelo.
Una pregunta fuera de la base sólo acierta si el guardarraíl la descarta; si
supera el umbral se cuenta como **alucinación** (el modelo respondería sin
evidencia). El proceso sale con código 1 si el puntaje es menor al mínimo
(8/10 por defecto), para que el pipeline se ponga rojo ante una regresión.

Uso:
    python app/eval/evaluar.py
    python app/eval/evaluar.py --json resultado.json --historial docs/eval/historial.md
    python app/eval/evaluar.py --url http://44.203.80.187
    python app/eval/evaluar.py --simular-regresion   # demuestra el pipeline en rojo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "app" / "src"))

import retrieval  # noqa: E402

RUTA_PREGUNTAS = RAIZ / "tests" / "eval" / "preguntas.json"
RUTA_FAQ = RAIZ / "app" / "data" / "faq.json"
CABECERA_HISTORIAL = """# Historial de evaluación de calidad

Cada fila la agrega el pipeline (`.github/workflows/ci.yml`) al correr en `main`.
El umbral mínimo es **8/10**: por debajo, el job falla y el PR queda en rojo.
El modo `offline` evalúa recuperación + guardarraíl (sin modelo) y el modo
`en-linea` evalúa el endpoint real de la EC2.

| Fecha (UTC) | Commit | Modo | Puntaje | Alucinaciones |
|---|---|---|---|---|
"""


def faqs_locales() -> list[dict]:
    datos = json.loads(RUTA_FAQ.read_text(encoding="utf-8"))
    return [{"id": f"faq-{i:03d}", **faq} for i, faq in enumerate(datos["faqs"], 1)]


def evaluar_offline(caso: dict, faqs: list[dict]) -> tuple[str, float, list[str]]:
    seleccion, puntaje = retrieval.seleccionar(caso["pregunta"], faqs, k=5)
    ids = [f["id"] for f in seleccion]
    if caso.get("fuera"):
        return ("alucinacion" if puntaje >= retrieval.UMBRAL else "acierto"), puntaje, ids
    if set(ids) & set(caso.get("esperadas", [])):
        return "acierto", puntaje, ids
    return "fallo", puntaje, ids


def evaluar_en_linea(caso: dict, url: str) -> tuple[str, float, list[str]]:
    cuerpo = json.dumps(
        {"mensaje": caso["pregunta"], "sesion": f"eval-{int(time.time())}"}
    ).encode("utf-8")
    peticion = urllib.request.Request(
        f"{url.rstrip('/')}/api/chat",
        data=cuerpo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=300) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    ids = [f["id"] for f in datos.get("fuentes", [])]
    puntaje = float(datos.get("puntaje", 0.0))
    if caso.get("fuera"):
        return ("alucinacion" if ids else "acierto"), puntaje, ids
    if set(ids) & set(caso.get("esperadas", [])):
        return "acierto", puntaje, ids
    return "fallo", puntaje, ids


def escribir_historial(ruta: Path, fila: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        ruta.write_text(CABECERA_HISTORIAL, encoding="utf-8")
    ruta.write_text(ruta.read_text(encoding="utf-8").rstrip("\n") + "\n" + fila + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa la calidad del chat de FAQ")
    parser.add_argument("--url", help="Evalúa el endpoint real, ej. http://44.203.80.187")
    parser.add_argument("--json", dest="salida", help="Guarda el reporte JSON en esta ruta")
    parser.add_argument("--historial", help="Agrega el resultado a este archivo markdown")
    parser.add_argument("--version", default="local", help="Commit o etiqueta de la versión evaluada")
    parser.add_argument("--umbral", type=int, default=None, help="Aciertos mínimos para aprobar")
    parser.add_argument(
        "--simular-regresion",
        action="store_true",
        help="Desactiva el guardarraíl para demostrar que el pipeline falla",
    )
    args = parser.parse_args()

    datos = json.loads(RUTA_PREGUNTAS.read_text(encoding="utf-8"))
    casos = datos["preguntas"]
    minimo = args.umbral if args.umbral is not None else int(datos.get("umbral_minimo", 8))
    modo = "en-linea" if args.url else "offline"

    if args.simular_regresion:
        retrieval.UMBRAL = 0.0
        retrieval.SINONIMOS = {}
        modo = "simulacion-regresion"

    faqs = faqs_locales() if not args.url else []

    detalle = []
    for caso in casos:
        if args.url:
            resultado, puntaje, ids = evaluar_en_linea(caso, args.url)
        else:
            resultado, puntaje, ids = evaluar_offline(caso, faqs)
        detalle.append(
            {
                "id": caso["id"],
                "pregunta": caso["pregunta"],
                "resultado": resultado,
                "puntaje": round(float(puntaje), 4),
                "fuentes": ids,
                "esperadas": caso.get("esperadas", []),
                "fuera_de_la_base": bool(caso.get("fuera")),
            }
        )

    aciertos = sum(1 for d in detalle if d["resultado"] == "acierto")
    alucinaciones = sum(1 for d in detalle if d["resultado"] == "alucinacion")
    aprobado = aciertos >= minimo

    print(f"\nEvaluación de calidad — modo {modo} — versión {args.version}")
    print(f"{'ID':<5}{'RESULTADO':<14}{'PUNTAJE':>8}  PREGUNTA")
    for d in detalle:
        print(f"{d['id']:<5}{d['resultado']:<14}{d['puntaje']:>8.2f}  {d['pregunta']}")
        if d["resultado"] != "acierto":
            print(f"     fuentes={d['fuentes']} esperadas={d['esperadas']}")
    print(f"\nResultado: {aciertos}/{len(casos)} aciertos · alucinaciones: {alucinaciones} · mínimo: {minimo}")
    print("APROBADO" if aprobado else "FALLIDO: la calidad bajó del mínimo")

    reporte = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": args.version,
        "modo": modo,
        "aciertos": aciertos,
        "total": len(casos),
        "puntaje": round(aciertos / len(casos), 3) if casos else 0,
        "umbral_minimo": minimo,
        "alucinaciones": alucinaciones,
        "aprobado": aprobado,
        "detalle": detalle,
    }

    if args.salida:
        Path(args.salida).write_text(
            json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Reporte JSON: {args.salida}")

    if args.historial:
        fila = (
            f"| {reporte['fecha']} | `{args.version}` | {modo} | "
            f"{aciertos}/{len(casos)} | {alucinaciones} |"
        )
        escribir_historial(Path(args.historial), fila)
        print(f"Histórico: {args.historial}")

    return 0 if aprobado else 1


if __name__ == "__main__":
    sys.exit(main())
