"""Chat de FAQ con IA — API y frontend.

Hito 6-7: la app corre en la EC2 con Docker Compose, usa Ollama como modelo
(contenedor) y DynamoDB para la base de FAQ, el historial y el uso.
"""

from __future__ import annotations

import os
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

import llm
import retrieval
import seed
import store

app = Flask(__name__, static_folder="static", static_url_path="")

VERSION = "0.2.0"
SIN_RESPUESTA = (
    "No tengo esa información en la base del programa. "
    "Escríbenos a admisiones@programa.edu.co y te respondemos."
)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="gtn-faq-chat",
        version=VERSION,
        modelo=llm.MODELO,
        proveedor=llm.PROVEEDOR,
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    datos = request.get_json(silent=True) or {}
    pregunta = " ".join(str(datos.get("mensaje", "")).split())
    sesion = str(datos.get("sesion") or uuid.uuid4())

    if not pregunta:
        return jsonify(error="La pregunta está vacía"), 400
    if len(pregunta) > 500:
        return jsonify(error="La pregunta es demasiado larga (máximo 500 caracteres)"), 400

    seed.cargar_si_vacia()

    if not store.dentro_de_presupuesto():
        uso = store.uso_del_mes()
        return (
            jsonify(
                error="El servicio alcanzó el tope de gasto del mes. Intenta de nuevo el próximo mes.",
                uso=uso,
            ),
            429,
        )

    faqs = store.listar_faq()
    seleccion, puntaje = retrieval.seleccionar(pregunta, faqs)
    historial = store.historial(sesion, limite=4)

    inicio = time.time()
    if not seleccion or puntaje < retrieval.UMBRAL:
        texto, tokens_in, tokens_out, proveedor = SIN_RESPUESTA, 0, 0, "ninguno"
        fuentes: list[dict] = []
        store.registrar_sin_respuesta(pregunta, sesion)
    else:
        try:
            texto, tokens_in, tokens_out, proveedor = llm.responder(
                pregunta, retrieval.contexto(seleccion), historial
            )
        except llm.ErrorLLM as exc:
            app.logger.exception("Fallo del modelo")
            return (
                jsonify(error="El asistente no está disponible en este momento. Intenta de nuevo."),
                503,
            )
        fuentes = [{"id": f["id"], "pregunta": f["pregunta"]} for f in seleccion]

    latencia_ms = int((time.time() - inicio) * 1000)
    costo = store.calcular_costo(tokens_in, tokens_out, proveedor)

    store.guardar_turno(sesion, "user", pregunta)
    store.guardar_turno(sesion, "bot", texto, fuentes, latencia_ms)
    store.sumar_uso(tokens_in, tokens_out, costo)

    return jsonify(
        respuesta=texto,
        fuentes=fuentes,
        sesion=sesion,
        proveedor=proveedor,
        puntaje=puntaje,
        latencia_ms=latencia_ms,
        tokens={"entrada": tokens_in, "salida": tokens_out},
        costo_usd=float(costo),
    )


@app.get("/api/historial/<sesion>")
def historial(sesion: str):
    turnos = store.historial(sesion, limite=30)
    return jsonify(
        sesion=sesion,
        mensajes=[
            {
                "rol": t.get("rol"),
                "texto": t.get("texto"),
                "ts": t.get("ts"),
                "fuentes": t.get("fuentes", []),
                "latencia_ms": t.get("latencia_ms"),
            }
            for t in turnos
        ],
    )


@app.get("/api/uso")
def uso():
    return jsonify(store.uso_del_mes())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
