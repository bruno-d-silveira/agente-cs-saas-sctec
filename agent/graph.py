"""Grafo do agente no LangGraph.

    START -> agente -> (tem chamada de ferramenta?) -> validacao -> (aprovada?) -> ferramentas -> agente
                    |-> resposta -> END                          |-> agente (com a recusa)

- agente: o LLM raciocina e decide a próxima ferramenta (ou responde).
- validacao: confere as regras de negócio ANTES de incluir créditos, fora do LLM.
- ferramentas: executa as chamadas aprovadas e grava os dados operacionais no estado.
- resposta: fecha a execução; se o limite de iterações estourou, explica isso.
"""

import json
import os
import re
from functools import partial

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent.prompts import SYSTEM_PROMPT
from agent.state import AgentState
from agent.tools import FERRAMENTAS, MAX_CREDITOS

MAX_ITERACOES = int(os.getenv("MAX_ITERACOES", "6"))
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "25"))

FERRAMENTAS_POR_NOME = {f.name: f for f in FERRAMENTAS}


def criar_llm():
    """LLM da Groq com as ferramentas acopladas. Só é criado quando o grafo roda."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b"), temperature=0)
    return llm.bind_tools(FERRAMENTAS)


# ---------- Regras de negócio (fora do LLM) ----------

def checar_inclusao(args: dict, estado: AgentState) -> str | None:
    """Devolve o motivo do bloqueio, ou None se a inclusão pode seguir."""
    quantidade = args.get("quantidade")
    if not isinstance(quantidade, int) or quantidade <= 0:
        return "A quantidade de créditos precisa ser um número inteiro positivo."
    if quantidade > MAX_CREDITOS:
        return f"{quantidade} créditos passam do teto de {MAX_CREDITOS} por operação."
    if estado.get("assinatura_id") is None:
        return "A assinatura ainda não foi consultada; consulte antes de incluir créditos."
    if args.get("assinatura_id") != estado["assinatura_id"]:
        return "O assinatura_id pedido não é o da assinatura consultada nesta execução."
    status = (estado.get("status_assinatura") or "").upper()
    if status != "ATIVA":
        return f"A assinatura está com status '{status or 'desconhecido'}'; só se inclui crédito em assinatura ATIVA."
    return None


def chamadas_pendentes(state: AgentState) -> list:
    """Chamadas de ferramenta da última mensagem do LLM (vazio se não houver)."""
    ultima = state["messages"][-1]
    return ultima.tool_calls if isinstance(ultima, AIMessage) else []


# ---------- Nós (o LangGraph exige o parâmetro com o nome "state") ----------

def no_agente(state: AgentState, llm) -> dict:
    mensagens = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    resposta = llm.invoke(mensagens)
    return {"messages": [resposta], "iteracoes": state.get("iteracoes", 0) + 1}


def no_validacao(state: AgentState) -> dict:
    chamadas = chamadas_pendentes(state)
    for chamada in chamadas:
        if chamada["name"] != "incluir_creditos":
            continue
        quantidade = chamada["args"].get("quantidade")
        motivo = checar_inclusao(chamada["args"], state)
        if motivo:
            # responde TODAS as chamadas desta rodada, para o LLM receber a recusa e explicar
            recusas = [
                ToolMessage(
                    content=json.dumps(
                        {"ok": False, "erro": "bloqueado_pela_validacao", "detalhe": motivo}
                        if c["id"] == chamada["id"]
                        else {"ok": False, "erro": "nao_executada", "detalhe": "Rodada bloqueada pela validação."},
                        ensure_ascii=False,
                    ),
                    tool_call_id=c["id"],
                )
                for c in chamadas
            ]
            return {"messages": recusas, "bloqueio": motivo, "creditos_solicitados": quantidade}
        return {"bloqueio": None, "creditos_solicitados": quantidade}
    return {"bloqueio": None}


def no_ferramentas(state: AgentState) -> dict:
    saidas, dados = [], {}
    for chamada in chamadas_pendentes(state):
        ferramenta = FERRAMENTAS_POR_NOME.get(chamada["name"])
        if ferramenta is None:
            resultado = {"ok": False, "erro": "ferramenta_inexistente", "detalhe": chamada["name"]}
        else:
            try:
                resultado = ferramenta.invoke(chamada["args"])
            except ValidationError as erro:
                resultado = {"ok": False, "erro": "parametros_invalidos", "detalhe": str(erro.errors()[0]["msg"])}

        if resultado.get("ok"):
            if chamada["name"] == "buscar_empresa":
                dados["empresa_id"] = resultado["empresa_id"]
            elif chamada["name"] == "consultar_assinatura":
                dados.update(
                    assinatura_id=resultado["assinatura_id"],
                    status_assinatura=resultado["status"],
                    saldo_atual=resultado["saldo_atual"],
                )
            elif chamada["name"] == "incluir_creditos":
                dados.update(creditos_incluidos=resultado["creditos_incluidos"], saldo_atual=resultado["saldo_atual"])

        saidas.append(ToolMessage(content=json.dumps(resultado, ensure_ascii=False), tool_call_id=chamada["id"]))
    return {"messages": saidas, **dados}


def no_resposta(state: AgentState) -> dict:
    ultima = state["messages"][-1]
    if isinstance(ultima, AIMessage) and not ultima.tool_calls:
        return {}
    aviso = (
        f"Execução encerrada: o limite de {MAX_ITERACOES} iterações foi atingido sem uma resposta final. "
        "Nenhuma operação além das já registradas foi feita."
    )
    return {"messages": [AIMessage(content=aviso)]}


# ---------- Arestas condicionais ----------

def depois_do_agente(estado: AgentState) -> str:
    ultima = estado["messages"][-1]
    if estado.get("iteracoes", 0) >= MAX_ITERACOES:
        return "resposta"
    if isinstance(ultima, AIMessage) and ultima.tool_calls:
        return "validacao"
    return "resposta"


def depois_da_validacao(estado: AgentState) -> str:
    return "agente" if estado.get("bloqueio") else "ferramentas"


# ---------- Montagem ----------

def construir_grafo(llm=None):
    llm = llm or criar_llm()
    grafo = StateGraph(AgentState)
    grafo.add_node("agente", partial(no_agente, llm=llm))
    grafo.add_node("validacao", no_validacao)
    grafo.add_node("ferramentas", no_ferramentas)
    grafo.add_node("resposta", no_resposta)

    grafo.add_edge(START, "agente")
    grafo.add_conditional_edges("agente", depois_do_agente, {"validacao": "validacao", "resposta": "resposta"})
    grafo.add_conditional_edges("validacao", depois_da_validacao, {"agente": "agente", "ferramentas": "ferramentas"})
    grafo.add_edge("ferramentas", "agente")
    grafo.add_edge("resposta", END)
    return grafo.compile()


def quantidade_pedida(instrucao: str) -> int | None:
    """Lê do pedido do analista a quantidade de créditos (ex.: '1.500 créditos', '5000 creditos')."""
    achado = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)\s*(?:cr[ée]ditos?)", instrucao, re.IGNORECASE)
    if not achado:
        return None
    return int(re.sub(r"[.\s]", "", achado.group(1)))


def motivo_da_recusa(final: dict) -> str | None:
    """Quando houve pedido de créditos e nada foi incluído, diz qual regra explica a recusa."""
    pedido = final.get("creditos_solicitados")
    if final.get("bloqueio"):
        return final["bloqueio"]
    if pedido is None or final.get("creditos_incluidos"):
        return None
    if pedido <= 0:
        return "A quantidade de créditos precisa ser um número inteiro positivo."
    if pedido > MAX_CREDITOS:
        return f"{pedido} créditos passam do teto de {MAX_CREDITOS} por operação."
    if final.get("empresa_id") is None:
        return "A empresa não foi identificada (inexistente ou nome ambíguo)."
    status = (final.get("status_assinatura") or "").upper()
    if status and status != "ATIVA":
        return f"A assinatura está com status '{status}'; só se inclui crédito em assinatura ATIVA."
    return "O agente não executou a inclusão; veja o parecer."


def estado_inicial(instrucao: str) -> AgentState:
    return {
        "messages": [HumanMessage(content=instrucao)],
        "empresa_id": None,
        "assinatura_id": None,
        "status_assinatura": None,
        "saldo_atual": None,
        "creditos_solicitados": quantidade_pedida(instrucao),
        "creditos_incluidos": None,
        "bloqueio": None,
        "iteracoes": 0,
    }


def executar(instrucao: str, grafo=None) -> dict:
    """Roda o agente para uma instrução e devolve o resultado estruturado."""
    grafo = grafo or construir_grafo()
    final = grafo.invoke(estado_inicial(instrucao), config={"recursion_limit": RECURSION_LIMIT})

    motivo = motivo_da_recusa(final)
    if final.get("creditos_incluidos"):
        status_inclusao = "concluida"
    elif motivo:
        status_inclusao = "recusada"
    else:
        status_inclusao = "nao_solicitada"

    return {
        "parecer": final["messages"][-1].content,
        "dados": {
            "empresa_id": final.get("empresa_id"),
            "assinatura_id": final.get("assinatura_id"),
            "status_assinatura": final.get("status_assinatura"),
            "saldo_atual": final.get("saldo_atual"),
            "creditos_solicitados": final.get("creditos_solicitados"),
            "creditos_incluidos": final.get("creditos_incluidos"),
        },
        "status_inclusao": status_inclusao,
        "motivo_bloqueio": motivo,
        "iteracoes": final.get("iteracoes", 0),
    }
