"""Ferramentas do agente: conversam com a API SaaS por HTTP.

O agente só tem acesso a estas três ações (menor privilégio):
buscar empresa, consultar assinatura e incluir créditos.
Nenhuma ferramenta altera plano, cancela conta ou faz estorno.
"""

import os

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

SAAS_API_URL = os.getenv("SAAS_API_URL", "http://localhost:8002")
SAAS_TIMEOUT = float(os.getenv("SAAS_TIMEOUT", "10"))
MAX_CREDITOS = int(os.getenv("MAX_CREDITOS_POR_OPERACAO", "3000"))


# ---------- Schemas de entrada (validados antes de qualquer requisição) ----------

class BuscarEmpresaInput(BaseModel):
    nome: str = Field(
        min_length=2,
        description="Nome fantasia (ou parte dele) da empresa cliente. Ex.: 'Logística Sul'",
    )


class ConsultarAssinaturaInput(BaseModel):
    empresa_id: int = Field(gt=0, description="ID numérico da empresa, obtido em buscar_empresa")


class IncluirCreditosInput(BaseModel):
    assinatura_id: int = Field(gt=0, description="ID numérico da assinatura, obtido em consultar_assinatura")
    quantidade: int = Field(
        gt=0,
        le=MAX_CREDITOS,
        description=f"Quantidade de créditos extras, de 1 a {MAX_CREDITOS} por operação",
    )
    motivo: str = Field(min_length=3, description="Justificativa da inclusão, informada pelo analista")


# ---------- Chamada HTTP com tratamento de erro ----------

def _requisitar(metodo: str, rota: str, **kwargs) -> dict:
    """Faz a requisição e devolve sempre um dicionário, sem quebrar a aplicação."""
    try:
        resposta = httpx.request(metodo, f"{SAAS_API_URL}{rota}", timeout=SAAS_TIMEOUT, **kwargs)
    except httpx.TimeoutException:
        return {"ok": False, "erro": "timeout", "detalhe": "A API SaaS demorou demais para responder."}
    except httpx.RequestError:
        return {"ok": False, "erro": "conexao", "detalhe": "Não foi possível conectar à API SaaS."}

    if resposta.status_code >= 400:
        try:
            detalhe = resposta.json().get("detail", resposta.text)
        except ValueError:
            detalhe = resposta.text
        return {"ok": False, "erro": f"http_{resposta.status_code}", "detalhe": str(detalhe)}

    return {"ok": True, "dados": resposta.json()}


# ---------- Ferramentas ----------

@tool(args_schema=BuscarEmpresaInput)
def buscar_empresa(nome: str) -> dict:
    """Busca empresas clientes pelo nome fantasia e devolve o empresa_id.

    Use sempre como primeiro passo, porque o analista informa só o nome.
    Se vier mais de uma empresa, a busca é ambígua: peça ao analista para especificar.
    Se não vier nenhuma, a empresa não existe no cadastro.
    """
    resultado = _requisitar("GET", "/empresas", params={"nome": nome})
    if not resultado["ok"]:
        return resultado

    empresas = resultado["dados"]
    if not empresas:
        return {"ok": False, "erro": "nao_encontrada", "detalhe": f"Nenhuma empresa encontrada com o nome '{nome}'."}
    if len(empresas) > 1:
        nomes = [e["nome_fantasia"] for e in empresas]
        return {"ok": False, "erro": "ambigua", "detalhe": "Mais de uma empresa encontrada.", "opcoes": nomes}

    empresa = empresas[0]
    return {"ok": True, "empresa_id": empresa["id"], "nome_fantasia": empresa["nome_fantasia"]}


@tool(args_schema=ConsultarAssinaturaInput)
def consultar_assinatura(empresa_id: int) -> dict:
    """Consulta a assinatura de uma empresa: assinatura_id, plano, status e saldo de créditos.

    Use depois de buscar_empresa. Créditos só podem ser incluídos se o status for ATIVA.
    """
    resultado = _requisitar("GET", f"/assinaturas/{empresa_id}")
    if not resultado["ok"]:
        return resultado

    assinatura = resultado["dados"][0]
    return {
        "ok": True,
        "assinatura_id": assinatura["id"],
        "plano": assinatura["plano"],
        "status": assinatura["status"],
        "saldo_atual": assinatura["saldo_creditos_api"],
    }


@tool(args_schema=IncluirCreditosInput)
def incluir_creditos(assinatura_id: int, quantidade: int, motivo: str) -> dict:
    """Inclui créditos extras de API numa assinatura ATIVA.

    Regras: quantidade de 1 a 3.000 por operação e assinatura com status ATIVA.
    Use só depois de consultar_assinatura e confirmar que as regras são atendidas.
    """
    resultado = _requisitar(
        "POST",
        f"/assinaturas/{assinatura_id}/creditos",
        json={"quantidade": quantidade, "motivo": motivo},
    )
    if not resultado["ok"]:
        return resultado

    assinatura = resultado["dados"]
    return {
        "ok": True,
        "assinatura_id": assinatura["id"],
        "creditos_incluidos": quantidade,
        "saldo_atual": assinatura["saldo_creditos_api"],
    }


FERRAMENTAS = [buscar_empresa, consultar_assinatura, incluir_creditos]
