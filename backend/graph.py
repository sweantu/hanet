import os
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from llm import llm
from pydantic import BaseModel as PydanticBaseModel
from rag import (
    search_database_impl,
    search_memories_impl,
    search_memories_with_ids_impl,
)
from tavily import TavilyClient
from typing_extensions import TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


@tool
async def search_database(query: str, config: RunnableConfig) -> str:
    """Search the conversation database for relevant past messages."""
    db = config["configurable"]["db"]
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


class _Keywords(PydanticBaseModel):
    keywords: list[str]


_keywords_llm = llm.with_structured_output(_Keywords)


async def _extract_keywords(content: str) -> list[str]:
    result = await _keywords_llm.ainvoke(
        [
            HumanMessage(
                content="Extract 5-10 keywords from the text below.\n\n" + content
            )
        ]
    )
    return result.keywords


@tool
async def save_memory(
    type: Annotated[
        str,
        "Memory type: 'hot' for timeless identity facts that are always relevant (user's name, language, persistent preferences); 'cold' for events, activities, purchases, logs, or anything time-specific or situational",
    ],
    content: str,
    config: RunnableConfig,
) -> str:
    """Save a memory. Use 'hot' ONLY for persistent identity facts (name, preferences). Use 'cold' for everything else: events, meals, expenses, activities, or any time-bound information."""
    from db import save_memory as db_save_memory
    from db import save_memory_embedding

    keywords = await _extract_keywords(content)
    approved = interrupt(
        {
            "tool": "save_memory",
            "summary": f"Save {type} memory",
            "content": content,
            "keywords": keywords,
        }
    )
    if not approved:
        return "Memory save declined."

    db = config["configurable"]["db"]
    memory_id = await db_save_memory(db, type, content)
    await save_memory_embedding(db, memory_id, type, content, keywords)
    return f"Saved {type} memory."


@tool
async def retrieve_memories(query: str, config: RunnableConfig) -> str:
    """Search stored memories (hot and cold) for information relevant to the query."""
    db = config["configurable"]["db"]
    results = await search_memories_impl(query, 5, db)
    return "\n\n".join(results) if results else "No relevant memories found."


@tool
async def delete_memory(
    description: Annotated[str, "Natural language description of the memory to delete"],
    config: RunnableConfig,
) -> str:
    """Delete the single closest matching memory. Use when the user asks to forget or remove something you remember."""
    from db import delete_memories as db_delete_memories

    db = config["configurable"]["db"]
    matches = await search_memories_with_ids_impl(description, 5, db)
    if not matches:
        return "No matching memory found."
    best = matches[:1]
    approved = interrupt(
        {
            "tool": "delete_memory",
            "summary": "Delete memory",
            "content": best[0]["content"],
            "keywords": [],
        }
    )
    if not approved:
        return "Memory deletion declined."
    ids = [m["memory_id"] for m in best]
    count = await db_delete_memories(db, ids)
    deleted = "\n".join(f"- {m['content']}" for m in best)
    return f"Deleted {count} memory:\n{deleted}"


@tool
async def update_memory(
    description: Annotated[str, "Natural language description of the memory to update"],
    new_content: Annotated[str, "The new content to replace the matched memory with"],
    config: RunnableConfig,
) -> str:
    """Update an existing memory. Use when the user wants to change or correct something you remember (name change, preference update). Finds the single closest match and replaces its content."""
    from db import update_memory as db_update_memory

    db = config["configurable"]["db"]
    matches = await search_memories_with_ids_impl(description, 5, db)
    if not matches:
        return "No matching memory found to update."
    best = matches[0]
    keywords = await _extract_keywords(new_content)
    approved = interrupt(
        {
            "tool": "update_memory",
            "summary": "Update memory",
            "content": new_content,
            "keywords": keywords,
            "old_content": best["content"],
        }
    )
    if not approved:
        return "Memory update declined."
    await db_update_memory(db, best["memory_id"], new_content, keywords)
    return f"Updated memory:\n- Old: {best['content']}\n- New: {new_content}"


_tools = [
    search_database,
    search_web,
    save_memory,
    retrieve_memories,
    delete_memory,
    update_memory,
]
_llm_with_tools = llm.bind_tools(_tools)
_tool_node = ToolNode(_tools)


async def agent(state: ChatState) -> dict:
    messages = state["messages"]
    response = await _llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


def build_graph(checkpointer=None):
    builder = StateGraph(ChatState)
    builder.add_node("agent", agent)
    builder.add_node("tools", _tool_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
