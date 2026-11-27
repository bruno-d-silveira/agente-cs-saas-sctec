"""API FastAPI: saúde, validação da entrada e falta de chave."""

from fastapi.testclient import TestClient

from api.server import app

cliente = TestClient(app)


def test_health():
    assert cliente.get("/health").json() == {"status": "ok"}


def test_instrucao_curta_da_422():
    assert cliente.post("/agent/executar", json={"instrucao": "oi"}).status_code == 422


def test_sem_chave_da_503(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert cliente.post("/agent/executar", json={"instrucao": "Consulte a Logística Sul"}).status_code == 503
