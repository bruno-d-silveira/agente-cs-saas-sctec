"""API do agente: recebe o pedido do analista em linguagem natural e devolve JSON estruturado.

Rodar:  uv run uvicorn api.server:app --reload --port 8010
Swagger: http://localhost:8010/docs
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

from agent.graph import executar  # noqa: E402  (depois do load_dotenv)

app = FastAPI(
    title="Agente de CS B2B",
    description="Consulta assinaturas e inclui créditos extras na API SaaS, com validação de regras.",
    version="0.1.0",
)


class PedidoAgente(BaseModel):
    instrucao: str = Field(
        min_length=3,
        max_length=1000,
        description="Pedido do analista. Ex.: 'Consulte a Logística Sul e adicione 1.500 créditos extras'",
    )


class DadosOperacionais(BaseModel):
    empresa_id: int | None = None
    assinatura_id: int | None = None
    status_assinatura: str | None = None
    saldo_atual: int | None = None
    creditos_solicitados: int | None = None
    creditos_incluidos: int | None = None


class RespostaAgente(BaseModel):
    parecer: str
    dados: DadosOperacionais
    status_inclusao: str = Field(description="concluida | recusada | nao_solicitada")
    motivo_bloqueio: str | None = None
    iteracoes: int


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/agent/executar", response_model=RespostaAgente)
def executar_agente(pedido: PedidoAgente):
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=503, detail="GROQ_API_KEY não configurada no .env.")
    try:
        return executar(pedido.instrucao)
    except Exception as erro:  # o agente nunca derruba a API
        raise HTTPException(status_code=500, detail=f"Falha ao executar o agente: {type(erro).__name__}") from erro
