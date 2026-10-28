import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import app  # noqa: E402
import auth  # noqa: E402
import retrieval  # noqa: E402
import seed  # noqa: E402
import store  # noqa: E402


@pytest.fixture()
def cliente():
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


@pytest.fixture()
def token_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "token-de-prueba")
    auth._cache = None
    yield "token-de-prueba"
    auth._cache = None


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


def test_una_sola_palabra_en_comun_no_alcanza():
    """Regresión: "campus" hacía pasar "¿Tienen cafetería en el campus?" y el modelo inventaba."""
    import json

    datos = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "faq.json").read_text(encoding="utf-8")
    )
    faqs = [{"id": f"faq-{i:03d}", **faq} for i, faq in enumerate(datos["faqs"], 1)]
    seleccion, puntaje = retrieval.seleccionar("¿Tienen cafetería en el campus?", faqs)
    assert seleccion == []
    assert puntaje == 0.0


def test_normaliza_tildes_y_mayusculas():
    assert retrieval.terminos("¿CUÁNDO Abre la INSCRIPCIÓN?") == retrieval.terminos(
        "cuando abre inscripcion"
    )


def test_contexto_incluye_pregunta_y_respuesta():
    seleccion, _ = retrieval.seleccionar("becas", FAQS)
    texto = retrieval.contexto(seleccion)
    assert "P:" in texto and "R:" in texto


# ------------------------------------------------------------------- admin
def test_admin_sin_token_responde_401(cliente):
    for ruta in ("/api/admin/faqs", "/api/admin/sin-respuesta", "/api/admin/reporte"):
        assert cliente.get(ruta).status_code == 401


def test_admin_token_invalido_responde_401(cliente, token_admin):
    r = cliente.get("/api/admin/faqs", headers={"X-Admin-Token": "otro"})
    assert r.status_code == 401


def test_admin_lista_faqs(cliente, token_admin, monkeypatch):
    monkeypatch.setattr(seed, "cargar_si_vacia", lambda: 0)
    monkeypatch.setattr(store, "listar_faq", lambda: [{"id": "faq-001", "pregunta": "p", "respuesta": "r"}])
    r = cliente.get("/api/admin/faqs", headers={"X-Admin-Token": token_admin})
    assert r.status_code == 200
    assert r.get_json()["faqs"][0]["id"] == "faq-001"


def test_admin_crea_faq(cliente, token_admin, monkeypatch):
    guardadas = []
    monkeypatch.setattr(store, "siguiente_id", lambda: "faq-027")
    monkeypatch.setattr(store, "guardar_faq", guardadas.append)
    r = cliente.post(
        "/api/admin/faqs",
        headers={"X-Admin-Token": token_admin},
        json={"pregunta": "¿Hay descuento por egresados?", "respuesta": "Sí, del 10%.", "categoria": "costos"},
    )
    assert r.status_code == 201
    assert guardadas[0]["id"] == "faq-027"
    assert guardadas[0]["categoria"] == "costos"


def test_admin_rechaza_faq_invalida(cliente, token_admin, monkeypatch):
    monkeypatch.setattr(store, "guardar_faq", lambda item: pytest.fail("no debió guardar"))
    r = cliente.post(
        "/api/admin/faqs",
        headers={"X-Admin-Token": token_admin},
        json={"pregunta": "ok?", "respuesta": "r"},
    )
    assert r.status_code == 400


def test_admin_edita_y_borra(cliente, token_admin, monkeypatch):
    actual = {"id": "faq-001", "pregunta": "¿Cuándo abre?", "respuesta": "Abre pronto.", "categoria": "admision"}
    guardadas, borradas = [], []
    monkeypatch.setattr(store, "obtener_faq", lambda _id: actual)
    monkeypatch.setattr(store, "guardar_faq", guardadas.append)
    monkeypatch.setattr(store, "borrar_faq", borradas.append)

    r = cliente.put(
        "/api/admin/faqs/faq-001",
        headers={"X-Admin-Token": token_admin},
        json={"respuesta": "Abre el 15 de abril."},
    )
    assert r.status_code == 200
    assert guardadas[0]["respuesta"] == "Abre el 15 de abril."
    assert guardadas[0]["pregunta"] == "¿Cuándo abre?"

    assert cliente.delete("/api/admin/faqs/faq-001", headers={"X-Admin-Token": token_admin}).status_code == 200
    assert borradas == ["faq-001"]


def test_admin_404_en_faq_inexistente(cliente, token_admin, monkeypatch):
    monkeypatch.setattr(store, "obtener_faq", lambda _id: None)
    assert cliente.delete("/api/admin/faqs/faq-999", headers={"X-Admin-Token": token_admin}).status_code == 404


def test_admin_convierte_sin_respuesta_en_faq(cliente, token_admin, monkeypatch):
    guardadas, borradas = [], []
    monkeypatch.setattr(
        store,
        "obtener_sin_respuesta",
        lambda _id: {"id": "abc123", "pregunta": "¿Hay bus de la universidad?", "veces": 3},
    )
    monkeypatch.setattr(store, "siguiente_id", lambda: "faq-027")
    monkeypatch.setattr(store, "guardar_faq", guardadas.append)
    monkeypatch.setattr(store, "borrar_sin_respuesta", borradas.append)

    r = cliente.post(
        "/api/admin/sin-respuesta/abc123/convertir",
        headers={"X-Admin-Token": token_admin},
        json={"respuesta": "Sí, hay ruta desde el centro.", "categoria": "contacto"},
    )
    assert r.status_code == 201
    assert guardadas[0]["pregunta"] == "¿Hay bus de la universidad?"
    assert borradas == ["abc123"]
