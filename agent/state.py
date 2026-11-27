"""Estado compartilhado entre os nós do grafo.

Duas partes separadas:
- messages: o histórico da conversa (analista, agente e ferramentas);
- dados operacionais: o que foi descoberto na execução atual.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # histórico: cada nó devolve mensagens novas e o add_messages soma ao que já existe
    messages: Annotated[list[AnyMessage], add_messages]

    # dados operacionais da execução atual
    empresa_id: int | None
    assinatura_id: int | None
    status_assinatura: str | None
    saldo_atual: int | None
    creditos_solicitados: int | None
    creditos_incluidos: int | None
    bloqueio: str | None

    # controle de execução: quantas vezes o LLM já raciocinou
    iteracoes: int
