"""Peças comuns dos testes: API SaaS simulada e LLM roteirizado.

Nada aqui chama a rede: os testes rodam sem chave da Groq e sem Docker.
"""

import pytest
from langchain_core.messages import AIMessage

import agent.tools as tools

EMPRESAS = [
    {"id": 1, "nome_fantasia": "Logística Sul"},
    {"id": 2, "nome_fantasia": "TechFlow Soluções"},
    {"id": 3, "nome_fantasia": "Alpha Varejo Brasil"},
    {"id": 4, "nome_fantasia": "Alpha Cloud Sistemas"},
]
ASSINATURAS = {
    1: {"id": 10, "plano": "STARTER", "status": "ATIVA", "saldo_creditos_api": 1200},
    2: {"id": 11, "plano": "PRO", "status": "INATIVA", "saldo_creditos_api": 300},
}


class ApiSaasFalsa:
    """Responde como a API SaaS e guarda cada inclusão de créditos pedida."""

    def __init__(self):
        self.inclusoes = []

    def __call__(self, metodo, rota, **kwargs):
        if rota == "/empresas":
            nome = kwargs["params"]["nome"].lower()
            return {"ok": True, "dados": [e for e in EMPRESAS if nome in e["nome_fantasia"].lower()]}
        if metodo == "GET" and rota.startswith("/assinaturas/"):
            assinatura = ASSINATURAS.get(int(rota.split("/")[2]))
            if assinatura is None:
                return {"ok": False, "erro": "http_404", "detalhe": "Nenhuma assinatura encontrada."}
            return {"ok": True, "dados": [assinatura]}
        if metodo == "POST" and rota.endswith("/creditos"):
            self.inclusoes.append(kwargs["json"])
            saldo = ASSINATURAS[1]["saldo_creditos_api"] + kwargs["json"]["quantidade"]
            return {"ok": True, "dados": {**ASSINATURAS[1], "saldo_creditos_api": saldo}}
        return {"ok": False, "erro": "rota_desconhecida", "detalhe": rota}


class LLMRoteirizado:
    """Faz o papel do LLM: devolve, em ordem, as chamadas de ferramenta ou o texto final do roteiro."""

    def __init__(self, passos):
        self.passos = list(passos)

    def invoke(self, mensagens):
        passo = self.passos.pop(0)
        if isinstance(passo, str):
            return AIMessage(content=passo)
        nome, args = passo
        return AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": f"chamada_{len(self.passos)}"}])


@pytest.fixture
def api_saas(monkeypatch):
    falsa = ApiSaasFalsa()
    monkeypatch.setattr(tools, "_requisitar", falsa)
    return falsa
