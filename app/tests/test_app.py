import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import app  # noqa: E402
import retrieval  # noqa: E402


@pytest.fixture()
def cliente():
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def test_health(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    cuerpo = r.get_json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["proveedor"] in {"ollama", "bedrock"}


def test_index_sirve_la_interfaz(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Asistente del programa" in html
    assert "/api/chat" in html


def test_pregunta_vacia(cliente):
    r = cliente.post("/api/chat", json={"mensaje": "   "})
    assert r.status_code == 400


def test_pregunta_muy_larga(cliente):
    r = cliente.post("/api/chat", json={"mensaje": "a" * 501})
    assert r.status_code == 400


# --------------------------------------------------------------- retrieval
FAQS = [
    {
        "id": "faq-001",
        "pregunta": "¿Cuándo abre la inscripción?",
        "respuesta": "La inscripción abre el 15 de abril y cierra el 30 de mayo.",
    },
    {
        "id": "faq-002",
        "pregunta": "¿Cuánto cuesta el semestre?",
        "respuesta": "La matrícula cuesta 4.850.000 pesos para pregrado.",
    },
    {
        "id": "faq-003",
        "pregunta": "¿Hay becas o descuentos?",
        "respuesta": "Hay beca de excelencia y descuento por hermanos.",
    },
]


def test_recupera_la_faq_correcta():
    seleccion, puntaje = retrieval.seleccionar("¿hasta cuándo puedo inscribirme?", FAQS)
    assert seleccion
    assert seleccion[0]["id"] == "faq-001"
    assert puntaje >= retrieval.UMBRAL


def test_pregunta_fuera_de_la_base():
    seleccion, puntaje = retrieval.seleccionar("¿cómo preparo una pizza napolitana?", FAQS)
    assert puntaje < retrieval.UMBRAL


def test_normaliza_tildes_y_mayusculas():
    assert retrieval.terminos("¿CUÁNDO Abre la INSCRIPCIÓN?") == retrieval.terminos(
        "cuando abre inscripcion"
    )


def test_contexto_incluye_pregunta_y_respuesta():
    seleccion, _ = retrieval.seleccionar("becas", FAQS)
    texto = retrieval.contexto(seleccion)
    assert "P:" in texto and "R:" in texto
