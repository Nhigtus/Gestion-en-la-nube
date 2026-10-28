"""Recuperación de contexto sin embeddings: TF-IDF sobre la base de FAQ.

Con ~50 documentos no hace falta una base vectorial: se puntúa cada FAQ por
cobertura de los términos de la pregunta (ponderados por IDF) y se envían las
mejores al modelo. Costo: cero. Ver docs/decisiones.md, decisión 4.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

import snowballstemmer

PALABRAS_VACIAS = {
    "que", "qué", "cual", "cuál", "cuales", "cuáles", "como", "cómo", "cuando",
    "cuándo", "donde", "dónde", "cuanto", "cuánto", "cuanta", "cuánta", "cuantos",
    "cuántos", "cuantas", "cuántas", "para", "por", "con", "sin", "los", "las",
    "una", "uno", "unos", "unas", "del", "al", "es", "son", "esta", "este",
    "hay", "puedo", "debo", "sirve", "hacer", "hago", "tiene", "tienen", "mas",
    "más", "pero", "sus", "sea", "ser", "mi", "mis", "yo", "me", "te", "se",
}

UMBRAL = 0.34
_RAIZ = snowballstemmer.stemmer("spanish")

# Normalización de vocabulario: el aspirante dice "vale" y la FAQ dice "cuesta".
SINONIMOS = {
    "vale": "cuesta", "valor": "cuesta", "precio": "cuesta", "costo": "cuesta", "coste": "cuesta",
    "inscribirme": "inscripcion", "inscribir": "inscripcion", "inscribo": "inscripcion",
    "inscripciones": "inscripcion",
    "graduarme": "grado", "graduacion": "grado", "graduar": "grado",
    "sabado": "finde", "sabados": "finde", "domingo": "finde",
    "clases": "horario", "clase": "horario", "horarios": "horario",
    "correos": "correo", "email": "correo", "mail": "correo",
    "pagar": "pago", "pagos": "pago",
    "telefonos": "telefono", "llamar": "telefono",
}


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y sin signos: '¿Cuándo?' -> 'cuando'."""
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]+", " ", texto)


def terminos(texto: str) -> list[str]:
    """Términos normalizados: sin vacías, con sinónimos y con raíz (stemming)."""
    salida = []
    for palabra in normalizar(texto).split():
        if len(palabra) <= 2 or palabra in PALABRAS_VACIAS:
            continue
        salida.append(_RAIZ.stemWord(SINONIMOS.get(palabra, palabra)))
    return salida


def _documento(faq: dict) -> list[str]:
    return terminos(f"{faq.get('pregunta', '')} {faq.get('respuesta', '')}")


def _idf(coleccion: list[list[str]]) -> dict[str, float]:
    n = len(coleccion)
    frecuencia = Counter()
    for doc in coleccion:
        frecuencia.update(set(doc))
    return {t: math.log((n + 1) / (df + 0.5)) for t, df in frecuencia.items()}


def seleccionar(pregunta: str, faqs: list[dict], k: int = 5) -> tuple[list[dict], float]:
    """Devuelve las k FAQ más relevantes y el puntaje de la mejor (0 a 1)."""
    if not faqs:
        return [], 0.0
    consulta = set(terminos(pregunta))
    if not consulta:
        return [], 0.0

    docs = [
        (faq, set(_documento(faq)), set(terminos(faq.get("pregunta", "")))) for faq in faqs
    ]
    pesos = _idf([list(doc) for _, doc, _ in docs])
    total = sum(pesos.get(t, 0.0) for t in consulta) or 1.0

    puntuadas = []
    for faq, doc, en_pregunta in docs:
        coincidencias = consulta & doc
        puntaje = sum(pesos.get(t, 0.0) for t in coincidencias) / total
        puntuadas.append((puntaje, len(coincidencias & en_pregunta), faq))

    # Si la pregunta trae vocabulario que no está en la base, la coincidencia
    # tiene que tocar la PREGUNTA de la FAQ y no sólo su respuesta. Sin esto,
    # "¿Tienen cafetería en el campus?" coincidía con "campus" en la respuesta
    # de otra FAQ, daba 1.0 y el modelo inventaba una cafetería.
    desconocidos = consulta - set(pesos)
    if desconocidos:
        puntuadas = [tupla for tupla in puntuadas if tupla[1] > 0]
        if not puntuadas:
            return [], 0.0

    puntuadas.sort(key=lambda par: par[0], reverse=True)
    mejor_puntaje = puntuadas[0][0]

    mejores = [faq for puntaje, _, faq in puntuadas[:k] if puntaje >= UMBRAL / 2]
    return mejores, round(mejor_puntaje, 4)


def contexto(seleccion: list[dict]) -> str:
    """Arma el bloque de contexto que se inyecta en el prompt."""
    partes = []
    for i, faq in enumerate(seleccion, 1):
        partes.append(f"[{i}] P: {faq['pregunta']}\n    R: {faq['respuesta']}")
    return "\n".join(partes)
