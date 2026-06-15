import os
import uuid
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
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


# ── Read tools ────────────────────────────────────────────────────────────────

@tool
async def search_database(query: str, config: RunnableConfig) -> str:
    """Search the conversation database for relevant past messages. Use a rich, descriptive query — include specific keywords, context, and synonyms (e.g. 'Python async await concurrency performance issue slow' rather than just 'Python performance') to improve recall."""
    db = config["configurable"]["db"]
    results = await search_database_impl(query, 5, db)
    return (
        "\n\n".join(results)
        if results
        else "No relevant information found in database."
    )


@tool
def search_web(query: str) -> str:
    """Search the web for current information. Use a rich, descriptive query with specific keywords and context (e.g. 'Python asyncio event loop blocking call best practices 2024' rather than just 'Python async') to get more targeted results."""
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query, max_results=5)
    results = response.get("results", [])
    if not results:
        return "No web results found."
    return "\n\n".join(f"Source: {r['url']}\n{r['content']}" for r in results)


@tool
async def retrieve_memories(query: str, config: RunnableConfig) -> str:
    """Search stored memories (hot and cold) for information relevant to the query. Use a rich, descriptive query — include specific keywords, context, and synonyms (e.g. 'food meal restaurant expense cost price VND' rather than just 'foods expense') to improve recall."""
    db = config["configurable"]["db"]
    results = await search_memories_impl(query, 5, db)
    return "\n\n".join(results) if results else "No relevant memories found."


@tool
async def find_memory(description: str, config: RunnableConfig) -> str:
    """Search for existing memories matching a description. Returns matches with their IDs and content. Always call this before delete_memory or update_memory to obtain the exact memory_id and current content. Use a rich, descriptive query with specific keywords and synonyms (e.g. 'food meal restaurant expense cost price VND' rather than just 'food expense') to improve recall."""
    db = config["configurable"]["db"]
    matches = await search_memories_with_ids_impl(description, 5, db)
    if not matches:
        return "No matching memories found."
    return "\n".join(f"[ID: {m['memory_id']}] {m['content']}" for m in matches)


# ── Write tools ───────────────────────────────────────────────────────────────

class _Keywords(PydanticBaseModel):
    keywords: list[str]


_keywords_llm = llm.with_structured_output(_Keywords)


async def _extract_keywords(content: str) -> list[str]:
    result = await _keywords_llm.ainvoke(
        [HumanMessage(content="Extract 5-10 keywords from the text below.\n\n" + content)]
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
    """Save a new memory. Use 'hot' ONLY for persistent identity facts (name, preferences). Use 'cold' for everything else: events, meals, expenses, activities, or any time-bound information."""
    from db import save_memory as db_save_memory
    from db import save_memory_embedding

    keywords = await _extract_keywords(content)
    db = config["configurable"]["db"]
    memory_id = await db_save_memory(db, type, content)
    await save_memory_embedding(db, memory_id, type, content, keywords)
    return f"Saved {type} memory."


@tool
async def delete_memory(
    memory_id: Annotated[str, "The exact UUID from find_memory results"],
    content: Annotated[str, "The current content of the memory (copy from find_memory output) — used for confirmation display only"],
    config: RunnableConfig,
) -> str:
    """Delete a memory by its exact ID. Always call find_memory first to get the memory_id and content."""
    from db import delete_memories as db_delete_memories

    try:
        uuid.UUID(memory_id)
    except ValueError:
        return "Invalid memory_id — not a valid UUID. Call find_memory first to get the correct memory_id."

    db = config["configurable"]["db"]
    count = await db_delete_memories(db, [memory_id])
    return f"Deleted {count} memory." if count else "Memory not found."


@tool
async def update_memory(
    memory_id: Annotated[str, "The exact UUID from find_memory results"],
    old_content: Annotated[str, "The current content of the memory (copy from find_memory output) — used for confirmation display only"],
    new_content: Annotated[str, "The replacement content"],
    config: RunnableConfig,
) -> str:
    """Update an existing memory by its exact ID. Always call find_memory first to get the memory_id and old_content."""
    from db import update_memory as db_update_memory

    try:
        uuid.UUID(memory_id)
    except ValueError:
        return "Invalid memory_id — not a valid UUID. Call find_memory first to get the correct memory_id."

    keywords = await _extract_keywords(new_content)
    db = config["configurable"]["db"]
    count = await db_update_memory(db, memory_id, new_content, keywords)
    if not count:
        return "Memory not found. Call find_memory first to get the correct memory_id."
    return "Updated memory."


# ── Graph nodes ───────────────────────────────────────────────────────────────

WRITE_TOOLS = {"save_memory", "delete_memory", "update_memory"}
_WRITE_TOOL_MAP = {"save_memory": save_memory, "delete_memory": delete_memory, "update_memory": update_memory}

_read_tools = [search_database, search_web, retrieve_memories, find_memory]
_write_tools = [save_memory, delete_memory, update_memory]
_llm_with_tools = llm.bind_tools(_read_tools + _write_tools)


async def agent(state: ChatState) -> dict:
    response = await _llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}


async def _summarize_write_calls(write_calls: list) -> str:
    import json

    ops = json.dumps(
        [{"tool": name, "args": args} for name, _, args in write_calls],
        indent=2,
    )
    msg = await llm.ainvoke(
        [
            HumanMessage(
                content=(
                    "The assistant wants to perform the following memory operations. "
                    "Write a concise, plain-English summary (2-4 sentences) describing "
                    "what will change, so the user can decide whether to approve or deny.\n\n"
                    + ops
                )
            )
        ]
    )
    return msg.content


async def hitl_node(state: ChatState, config: RunnableConfig) -> dict:
    last_msg = state["messages"][-1]

    has_read = any(tc["name"] not in WRITE_TOOLS for tc in last_msg.tool_calls)
    if has_read:
        return {
            "messages": [
                ToolMessage(
                    content="Error: do not mix read and write tool calls in one message. Call read tools first, then write tools in a separate turn.",
                    tool_call_id=call["id"],
                )
                for call in last_msg.tool_calls
            ]
        }

    write_calls = [
        (call["name"], call["id"], call["args"])
        for call in last_msg.tool_calls
        if call["name"] in WRITE_TOOLS
    ]

    summary = await _summarize_write_calls(write_calls)
    resume_value = interrupt({"summary": summary})

    # Support both legacy bool and new dict form
    if isinstance(resume_value, bool):
        action = "approve" if resume_value else "deny"
        replan_message = None
    else:
        action = resume_value.get("action", "deny")
        replan_message = resume_value.get("message")

    result_messages = []
    for name, call_id, args in write_calls:
        if action == "approve":
            result = await _WRITE_TOOL_MAP[name].ainvoke(args, config=config)
            result_messages.append(ToolMessage(content=result, tool_call_id=call_id))
        else:
            result_messages.append(
                ToolMessage(content="Operation denied by user.", tool_call_id=call_id)
            )

    if action == "replan" and replan_message:
        result_messages.append(HumanMessage(content=replan_message))

    return {"messages": result_messages}


def tools_router(state: ChatState):
    last_msg = state["messages"][-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return END
    if any(tc["name"] in WRITE_TOOLS for tc in last_msg.tool_calls):
        return "hitl"
    return "read_tools"


def build_graph(checkpointer=None):
    builder = StateGraph(ChatState)
    builder.add_node("agent", agent)
    builder.add_node("hitl", hitl_node)
    builder.add_node("read_tools", ToolNode(_read_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_router, ["hitl", "read_tools", END])
    builder.add_edge("hitl", "agent")
    builder.add_edge("read_tools", "agent")
    return builder.compile(checkpointer=checkpointer)
