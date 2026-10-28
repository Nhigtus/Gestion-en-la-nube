import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import app  # noqa: E402


@pytest.fixture()
def cliente():
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def test_health(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_index_sirve_la_interfaz(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Asistente del programa" in r.get_data(as_text=True)


def test_ruta_inexistente(cliente):
    assert cliente.get("/api/chat").status_code == 404
