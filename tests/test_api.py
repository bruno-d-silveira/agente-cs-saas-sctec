"""API FastAPI: saúde, validação da entrada e falta de chave."""

from fastapi.testclient import TestClient

from api.server import app

cliente = TestClient(app)


def test_health():
    assert cliente.get("/health").json() == {"status": "ok"}


def test_instrucao_curta_da_422():
    assert cliente.post("/agent/executar", json={"instrucao": "oi"}).status_code == 422


def test_painel_abre_e_chama_o_agente():
    resposta = cliente.get("/painel")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    assert 'fetch("/agent/executar"' in resposta.text


def test_painel_fora_do_swagger():
    assert "/painel" not in cliente.get("/openapi.json").json()["paths"]


def test_sem_chave_da_503(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert cliente.post("/agent/executar", json={"instrucao": "Consulte a Logística Sul"}).status_code == 503
