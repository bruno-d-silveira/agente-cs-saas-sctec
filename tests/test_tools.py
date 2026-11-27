"""Ferramentas: validação Pydantic antes do HTTP e respostas da API SaaS."""

import httpx
import pytest
from pydantic import ValidationError

import agent.tools as tools
from agent.tools import buscar_empresa, consultar_assinatura, incluir_creditos


def test_busca_unica_devolve_empresa_id(api_saas):
    assert buscar_empresa.invoke({"nome": "Logística Sul"}) == {
        "ok": True, "empresa_id": 1, "nome_fantasia": "Logística Sul"}


def test_busca_ambigua_lista_as_opcoes(api_saas):
    resultado = buscar_empresa.invoke({"nome": "Alpha"})
    assert resultado["erro"] == "ambigua"
    assert resultado["opcoes"] == ["Alpha Varejo Brasil", "Alpha Cloud Sistemas"]


def test_busca_sem_resultado(api_saas):
    assert buscar_empresa.invoke({"nome": "Zeta"})["erro"] == "nao_encontrada"


def test_consulta_devolve_status_e_saldo(api_saas):
    assert consultar_assinatura.invoke({"empresa_id": 2}) == {
        "ok": True, "assinatura_id": 11, "plano": "PRO", "status": "INATIVA", "saldo_atual": 300}


def test_consulta_404_nao_quebra(api_saas):
    assert consultar_assinatura.invoke({"empresa_id": 99})["erro"] == "http_404"


@pytest.mark.parametrize("quantidade", [0, -5, 3001, 5000])
def test_quantidade_fora_da_regra_e_barrada_antes_do_http(api_saas, quantidade):
    with pytest.raises(ValidationError):
        incluir_creditos.invoke({"assinatura_id": 10, "quantidade": quantidade, "motivo": "teste"})
    assert api_saas.inclusoes == []


def test_motivo_curto_e_barrado(api_saas):
    with pytest.raises(ValidationError):
        incluir_creditos.invoke({"assinatura_id": 10, "quantidade": 100, "motivo": "ok"})


def test_teto_exato_e_aceito(api_saas):
    resultado = incluir_creditos.invoke({"assinatura_id": 10, "quantidade": 3000, "motivo": "bônus"})
    assert resultado["ok"] and resultado["creditos_incluidos"] == 3000


def test_timeout_vira_erro_tratado(monkeypatch):
    def estoura(*args, **kwargs):
        raise httpx.TimeoutException("lento")
    monkeypatch.setattr(httpx, "request", estoura)
    assert tools._requisitar("GET", "/empresas")["erro"] == "timeout"


def test_api_fora_do_ar_vira_erro_tratado(monkeypatch):
    def recusa(*args, **kwargs):
        raise httpx.ConnectError("recusada")
    monkeypatch.setattr(httpx, "request", recusa)
    assert tools._requisitar("GET", "/empresas")["erro"] == "conexao"


@pytest.mark.parametrize("codigo", [404, 422, 500])
def test_erro_http_vira_dicionario(monkeypatch, codigo):
    def responde(*args, **kwargs):
        return httpx.Response(codigo, json={"detail": "falhou"})
    monkeypatch.setattr(httpx, "request", responde)
    assert tools._requisitar("GET", "/empresas") == {"ok": False, "erro": f"http_{codigo}", "detalhe": "falhou"}
