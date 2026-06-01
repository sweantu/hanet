from typing import Annotated, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from llm import llm
from models import RAGRouterDecision
from rag import rag_retrieve
from typing_extensions import TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    db: Any
    rag_messages: list[str]
    should_retrieve: bool


async def route_intent(state: ChatState) -> dict:
    query = state["messages"][-1].content
    router_llm = llm.with_structured_output(RAGRouterDecision)
    decision: RAGRouterDecision = await router_llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "You decide whether the user's message requires retrieving past conversation history. "
                    "Return should_retrieve=true only if the user is explicitly asking about something from a "
                    "previous conversation, referencing past messages, or asking you to recall prior context. "
                    "For all other messages return should_retrieve=false."
                )
            ),
            HumanMessage(content=query),
        ]
    )
    print(
        f"[RAG router] should_retrieve={decision['should_retrieve']} | query={query[:80]}"
    )
    return {"should_retrieve": decision["should_retrieve"]}


async def retrieve_rag(state: ChatState) -> dict:
    query = state["messages"][-1].content
    rag_messages = await rag_retrieve(query, 5, state["db"])
    print(f"[RAG retrieve] {len(rag_messages)} message(s) retrieved")
    return {"rag_messages": rag_messages}


def _call_model(state: ChatState) -> dict:
    messages = list(state["messages"])
    rag_messages = state.get("rag_messages") or []

    if rag_messages:
        retrieved_block = "\n\n---\n\n".join(rag_messages)
        system_content = (
            "You are a helpful assistant.\n\n"
            "The following are your own responses retrieved from previous conversations. "
            "Use them as memory to answer the user's question:\n\n"
            f"{retrieved_block}"
        )
        messages = [SystemMessage(content=system_content)] + messages[1:]
        print(f"[agent] injected {len(rag_messages)} RAG message(s) into system prompt")

    return {"messages": [llm.invoke(messages)]}


def _route_edge(state: ChatState) -> str:
    return "retrieve_rag" if state.get("should_retrieve") else "agent"


_builder = StateGraph(ChatState)
_builder.add_node("route_intent", route_intent)
_builder.add_node("retrieve_rag", retrieve_rag)
_builder.add_node("agent", _call_model)
_builder.add_edge(START, "route_intent")
_builder.add_conditional_edges(
    "route_intent", _route_edge, {"retrieve_rag": "retrieve_rag", "agent": "agent"}
)
_builder.add_edge("retrieve_rag", "agent")
_builder.add_edge("agent", END)
graph = _builder.compile()
