"""Chat de FAQ con IA — API y frontend.

Hito 6-7: la app corre en la EC2 con Docker Compose, usa Ollama como modelo
(contenedor) y DynamoDB para la base de FAQ, el historial y el uso.
"""

from __future__ import annotations

import os
import re
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

import auth
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

    faqs = [f for f in store.listar_faq() if f.get("activa", True)]
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


# ------------------------------------------------------------------ admin
# El panel se protege con un token que no está en el repo: se genera al azar
# y se guarda cifrado en SSM (ver app/src/auth.py).
def _token_peticion() -> str | None:
    return (
        request.headers.get("X-Admin-Token")
        or (request.get_json(silent=True) or {}).get("token")
        or request.args.get("token")
    )


def _exigir_admin():
    if not auth.autorizado(_token_peticion()):
        return jsonify(error="Token de administración inválido o ausente"), 401
    return None


def _validar_faq(datos: dict, actual: dict | None = None) -> tuple[str, str, str, bool]:
    base = actual or {}
    pregunta = " ".join(str(datos.get("pregunta", base.get("pregunta", ""))).split())
    respuesta = " ".join(str(datos.get("respuesta", base.get("respuesta", ""))).split())
    categoria = str(datos.get("categoria", base.get("categoria", "general"))).strip().lower()
    if not 5 <= len(pregunta) <= 300:
        raise ValueError("La pregunta debe tener entre 5 y 300 caracteres")
    if not 5 <= len(respuesta) <= 2000:
        raise ValueError("La respuesta debe tener entre 5 y 2000 caracteres")
    if not re.fullmatch(r"[a-z0-9-]{2,30}", categoria):
        raise ValueError("La categoría debe ser una palabra corta en minúsculas (ej. admision)")
    activa = bool(datos.get("activa", base.get("activa", True)))
    return pregunta, respuesta, categoria, activa


@app.get("/admin")
def admin_panel():
    return send_from_directory(app.static_folder, "admin.html")


@app.get("/api/admin/faqs")
def admin_listar_faqs():
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    seed.cargar_si_vacia()
    return jsonify(faqs=store.listar_faq(), umbral=retrieval.UMBRAL)


@app.post("/api/admin/faqs")
def admin_crear_faq():
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    try:
        pregunta, respuesta, categoria, activa = _validar_faq(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    faq = {
        "id": store.siguiente_id(),
        "pregunta": pregunta,
        "respuesta": respuesta,
        "categoria": categoria,
        "activa": activa,
    }
    store.guardar_faq(faq)
    app.logger.info("FAQ creada %s", faq["id"])
    return jsonify(faq=faq), 201


@app.put("/api/admin/faqs/<faq_id>")
def admin_editar_faq(faq_id: str):
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    actual = store.obtener_faq(faq_id)
    if not actual:
        return jsonify(error=f"No existe la FAQ {faq_id}"), 404
    try:
        pregunta, respuesta, categoria, activa = _validar_faq(
            request.get_json(silent=True) or {}, actual
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    faq = {
        "id": faq_id,
        "pregunta": pregunta,
        "respuesta": respuesta,
        "categoria": categoria,
        "activa": activa,
    }
    store.guardar_faq(faq)
    app.logger.info("FAQ editada %s", faq_id)
    return jsonify(faq=faq)


@app.delete("/api/admin/faqs/<faq_id>")
def admin_borrar_faq(faq_id: str):
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    if not store.obtener_faq(faq_id):
        return jsonify(error=f"No existe la FAQ {faq_id}"), 404
    store.borrar_faq(faq_id)
    app.logger.info("FAQ borrada %s", faq_id)
    return jsonify(borrada=faq_id)


@app.get("/api/admin/sin-respuesta")
def admin_sin_respuesta():
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    limite = min(max(request.args.get("limite", 50, type=int) or 50, 1), 100)
    items = store.listar_sin_respuesta(limite)
    return jsonify(
        total=len(items),
        top5=[{"pregunta": i["pregunta"], "veces": i["veces"]} for i in items[:5]],
        preguntas=items,
    )


@app.post("/api/admin/sin-respuesta/<ident>/convertir")
def admin_convertir_sin_respuesta(ident: str):
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    item = store.obtener_sin_respuesta(ident)
    if not item:
        return jsonify(error=f"No existe la pregunta sin respuesta {ident}"), 404
    datos = request.get_json(silent=True) or {}
    datos.setdefault("pregunta", item.get("pregunta", ""))
    try:
        pregunta, respuesta, categoria, activa = _validar_faq(datos)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    faq = {
        "id": store.siguiente_id(),
        "pregunta": pregunta,
        "respuesta": respuesta,
        "categoria": categoria,
        "activa": activa,
    }
    store.guardar_faq(faq)
    store.borrar_sin_respuesta(ident)
    app.logger.info("Pregunta sin respuesta %s convertida en %s", ident, faq["id"])
    return jsonify(faq=faq, convertida=ident), 201


@app.get("/api/admin/reporte")
def admin_reporte():
    no_autorizado = _exigir_admin()
    if no_autorizado:
        return no_autorizado
    faqs = store.listar_faq()
    sin = store.listar_sin_respuesta(100)
    return jsonify(
        faqs_total=len(faqs),
        faqs_activas=sum(1 for f in faqs if f.get("activa", True)),
        sin_respuesta_total=len(sin),
        top5=[{"pregunta": i["pregunta"], "veces": i["veces"]} for i in sin[:5]],
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
