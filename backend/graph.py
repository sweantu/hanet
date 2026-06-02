import os
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from llm import llm
from rag import search_database_impl
from tavily import TavilyClient
from typing_extensions import TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    db: Any


@tool
async def search_database(
    query: str,
    db: Annotated[Any, InjectedState("db")],
) -> str:
    """Search the conversation database for relevant past messages."""
    results = await search_database_impl(query, 5, db)
    return (
        "\n\n".join(results)
        if results
        else "No relevant information found in database."
    )


@tool
def search_web(query: str) -> str:
    """Search the web for current information."""
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query, max_results=5)
    results = response.get("results", [])
    if not results:
        return "No web results found."
    return "\n\n".join(f"Source: {r['url']}\n{r['content']}" for r in results)


_tools = [search_database, search_web]
_llm_with_tools = llm.bind_tools(_tools)
_tool_node = ToolNode(_tools)


async def agent(state: ChatState) -> dict:
    messages = state["messages"]
    response = await _llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


_builder = StateGraph(ChatState)
_builder.add_node("agent", agent)
_builder.add_node("tools", _tool_node)
_builder.add_edge(START, "agent")
_builder.add_conditional_edges("agent", tools_condition)
_builder.add_edge("tools", "agent")
graph = _builder.compile()
