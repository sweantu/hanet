# Project History

## 2026-06-16 (session 17)

Replaced the hard 10-message context window with LangGraph-native stateful history and rolling summarization.

**Context window — stateful checkpointer (`routers/chat.py`):**

`POST /chat` no longer re-seeds the LangGraph graph from scratch on every turn. It checks `state.values.get("messages")`: if the checkpointer already holds state for the thread, only the new `HumanMessage` is injected and the full history is restored from the checkpoint. For new conversations (or existing ones migrating to this behaviour for the first time), all messages are loaded from the DB ordered ASC and used as the seed — `maybe_summarize` compacts them immediately if they exceed the threshold. The manual hot-memories and system-prompt construction in `chat.py` was removed; the `agent` node now owns it.

**Rolling summarization (`graph.py`):**

`ChatState` gained a `summary: str` field persisted automatically by `AsyncPostgresSaver`. A new `maybe_summarize` node fires at `START` of every user turn (before `agent`). When `len(messages) > SUMMARIZE_THRESHOLD` (20), it walks back from `len - KEEP_RECENT` (8) to the nearest `HumanMessage` boundary, summarizes all older messages via a dedicated LLM call (folding in any existing summary), removes them from state with `RemoveMessage`, and stores the new summary. Tool-loop edges (`hitl → agent`, `read_tools → agent`) bypass `maybe_summarize` so summarization does not fire mid-turn.

**System prompt moved into `agent` node (`graph.py`):**

`agent` now accepts `config: RunnableConfig`, fetches hot memories from the DB directly, and prepends a fresh `SystemMessage` (base prompt + hot memories + summary if present) on every LLM call. This keeps the system message out of persisted state and ensures hot memories are always current.

Constants: `SUMMARIZE_THRESHOLD = 20`, `KEEP_RECENT = 8`.

## 2026-06-15 (session 16)

Hardened memory write tool robustness and improved LLM relevance scoring.

**Memory write tool hardening (`graph.py`, `db.py`):**

`db.update_memory` now returns `int` (rows affected) using the same `result.split()[-1]` pattern as `delete_memories`. The `update_memory` tool in `graph.py` checks this count and returns `"Memory not found. Call find_memory first to get the correct memory_id."` when 0 rows were updated — instead of silently succeeding on a hallucinated or stale UUID (as `"Updated memory."` was returned unconditionally before).

Both `update_memory` and `delete_memory` tools now validate the `memory_id` argument with `uuid.UUID(memory_id)` before touching the DB. Hallucinated placeholders like `'memory_id_1'` now return a graceful error ToolMessage instead of crashing asyncpg with a `DataError`.

`hitl_node` now detects mixed read+write tool calls in a single AIMessage. Previously, when the model emitted both `find_memory` and `save_memory` in the same turn, the node only processed write calls and left the read call ID without a `ToolMessage`, causing OpenAI to reject the next agent call with a 400. Now, if any read tool is present alongside write tools, all call IDs receive an error ToolMessage and `interrupt()` is skipped entirely — the model retries with reads and writes in separate turns.

**LLM relevance scoring (`rag.py`):**

`_llm_score` prompt replaced. The previous bare prompt ("Rate each passage 0–10 for relevance") caused the LLM to default to 5 when uncertain — e.g. "coffee" and "lemon tea" passages scored 5 for the query "drinking expense cost" and were dropped by the ≥7 filter. The new prompt defines the full scale (9–10 exact match, 7–8 clearly relevant, 4–6 tangential, 0–3 unrelated) and instructs the LLM to recognise semantic categories ("coffee", "tea", "juice" are drinks; "rice", "noodles", "buns" are food; etc.).

## 2026-06-11 (session 15)

Added a third "Re-plan" action to the HITL interrupt flow, and improved memory retrieval recall.

**HITL Re-plan:** The interrupt card now has three actions — Deny, Re-plan, Approve. Clicking Re-plan expands a textarea; Deny and Approve are hidden and replaced by Cancel and Submit. On submit, all write tools are denied and the user's guidance is injected as a `HumanMessage` into the graph state so the agent re-plans. Cancel collapses the textarea and restores the original three buttons.

`backend/models.py`: `ResumeRequest` changed from `approved: bool` to `action: Literal["approve","deny","replan"]` + `message: Optional[str]`; a `model_validator` enforces that replan requires a non-empty message.

`backend/graph.py`: `hitl_node` normalises the resume value (supports dict or legacy bool). For "approve" it executes write tools; for "deny" or "replan" it returns denied `ToolMessage`s. For "replan" it also appends a `HumanMessage(content=replan_message)` to the returned messages, which the `add_messages` reducer appends to state before the graph loops back to `agent`.

`backend/routers/chat.py`: resume endpoint saves the replan user message to DB (and document chunks for search) before streaming, builds `resume_payload = {"action": ..., "message": ...}` and passes it to `Command(resume=...)`.

`frontend/src/types/index.ts`: added `ResumeAction = "approve" | "deny" | "replan"`.

`frontend/src/hooks/useChat.ts`: `resolveInterrupt(action: ResumeAction, message?: string)` — injects a user bubble for replan before the assistant placeholder; POST body changed to `{conversation_id, action, message?}`.

`frontend/src/components/MessageList.tsx`: extracted internal `InterruptCard` component with local `showReplan`/`replanText` state. Default view: Deny | Re-plan | Approve. Expanded view: textarea + Cancel | Submit (Submit disabled when blank; Enter submits, Shift+Enter inserts newline).

**Memory retrieval improvements:** Lowered `search_memories_impl` threshold from 8 to 7 (matching the linter-adjusted value; `search_database_impl` also adjusted to 7) so scores in the 5–7 range are no longer silently dropped. Updated all four read tool descriptions (`search_database`, `search_web`, `retrieve_memories`, `find_memory`) to instruct the agent to use rich, keyword-dense queries with synonyms and context rather than short two-word queries.

## 2026-06-11 (session 14)

Refactored HITL into a dedicated `hitl_node` and separated write tool logic from the approval flow.

**Architecture change:** Write tools (`save_memory`, `delete_memory`, `update_memory`) are now purely deterministic `@tool` functions containing only DB logic — no `interrupt()` calls, no embedded search. A new `find_memory` read tool allows the agent to look up existing memories (returning `[ID: uuid] content` lines) before calling delete or update. The HITL interrupt and approval gate lives entirely in `hitl_node`.

`graph.py`: replaced the single `_tool_node` + `tools_condition` pattern with a `tools_router` conditional edge that routes to `"hitl"` when any write tool is called, `"read_tools"` (ToolNode of read tools) otherwise, or `END`. New `find_memory` tool wraps `search_memories_with_ids_impl`. Write tools gain `memory_id`/`content`/`old_content` parameters so the agent explicitly passes the data retrieved from `find_memory`; DB logic (including `_extract_keywords`) runs inside the tool functions. `hitl_node`: reads pending write tool calls from the last AIMessage, calls `_summarize_write_calls(write_calls)` — which serializes the operations as JSON and asks the LLM to produce a concise plain-English summary — then calls `interrupt({"summary": text})`; on approval invokes each write tool via `_WRITE_TOOL_MAP[name].ainvoke(args, config=config)` and collects `ToolMessage` results; on denial returns denied `ToolMessage`s. Edge `hitl → agent` (unconditional — no `after_hitl_router` needed). `_WRITE_TOOL_MAP` dict dispatches by tool name.

`frontend/src/types/index.ts`: simplified `InterruptData` to `{ summary: string }` — removed `tool`, `content`, `keywords`, `old_content` fields.

`frontend/src/components/MessageList.tsx`: amber approval card now renders just the LLM-generated summary text (removed keyword chips, old-content strikethrough, and separate content line).

## 2026-06-10 (session 13)

Added Human-in-the-Loop (HITL) approval flow for all memory write tools. Before any write executes, the graph pauses and the chat UI shows an amber approval card with the resolved content and keywords. User clicks Approve or Deny; the graph resumes via `Command(resume=bool)`. Interrupt state is persisted in Postgres via `AsyncPostgresSaver`, so pending approvals survive page reloads.

**Architecture:** LangGraph `interrupt(payload)` → checkpoint saved to Postgres → SSE `{"interrupt": {...}}` event → frontend shows card → `POST /chat/resume` with `Command(resume=approved)` → graph continues.

`requirements.txt`: added `langgraph-checkpoint-postgres>=2.0.0` and `psycopg[binary,pool]>=3.1.0`.

`graph.py`: removed `db` from `ChatState` (live asyncpg connections can't be checkpointed); switched all six tools from `InjectedState("db")` to `RunnableConfig` — `db = config["configurable"]["db"]`. Added `interrupt(payload)` calls before DB writes in `save_memory` (after keyword extraction — payload includes `{tool, summary, content, keywords}`), `delete_memory` (after finding the best match — payload shows the matched content), and `update_memory` (after finding match and extracting new keywords — payload also includes `old_content`). If `approved` is falsy, returns a declined message. Replaced module-level `graph = _builder.compile()` with `build_graph(checkpointer=None)` factory function.

`main.py`: lifespan uses `async with AsyncPostgresSaver.from_conn_string(pg_conn_string) as checkpointer`; calls `await checkpointer.setup()` (creates `langgraph_checkpoints` and related tables); calls `build_graph(checkpointer)` and stores result in `app.state.graph`.

`models.py`: added `ResumeRequest(conversation_id: str, approved: bool)`.

`routers/chat.py`: extracted `_stream_graph(graph, input_data, config, results)` async generator — streams `on_chat_model_stream` events as SSE `{"text": chunk}`, calls `aget_state` after the loop to detect interrupts, yields `{"interrupt": payload}` if paused, appends `(full_response_str, interrupt_payload)` to the `results` list before yielding `[DONE]`. `POST /chat` now takes `Request`, reads `app.state.graph`, builds `config = {"configurable": {"thread_id": conv_id, "db": db}}`, guards against pending interrupts with `aget_state` (returns 409 if `state.next` is non-empty), and only saves the assistant message + embeddings if no interrupt fired. New `POST /chat/resume` streams `Command(resume=body.approved)` through the same helper. New `GET /conversations/{id}/pending-interrupt` checks checkpoint state without executing any nodes — returns `{"interrupt": payload}` or `{"interrupt": null}`.

`frontend/src/types/index.ts`: added `InterruptData {tool, summary, content, keywords, old_content?}`; extended `Message.role` to include `"interrupt"` and added `interrupt?: InterruptData` field.

`frontend/src/hooks/useChat.ts`: added `pendingInterrupt` state; extracted `parseStream(reader)` callback that handles both `{text}` and `{interrupt}` SSE events (removes trailing empty assistant placeholder on interrupt); added `resolveInterrupt(approved)` — clears interrupt message, POSTs to `/chat/resume`, streams response via `parseStream`; added `setInterruptFromReload(payload)` for page-reload recovery; `sendMessage` guards on `pendingInterrupt`.

`frontend/src/components/MessageList.tsx`: renders amber interrupt cards for `role="interrupt"` messages — shows summary, optional `old_content` (strikethrough), new content, keyword chips, and Approve/Deny buttons (disabled when `!pendingInterrupt`).

`frontend/src/app/page.tsx`: added `setInterruptFromReloadRef` (ref pattern to call `setInterruptFromReload` from `selectConversation` which is defined before `useChat`); `selectConversation` fetches `/conversations/{id}/pending-interrupt` after `loadMessages` and calls `setInterruptFromReload` if a pending interrupt is found; passes `pendingInterrupt` and `resolveInterrupt` to `MessageList`; passes `isStreaming || pendingInterrupt` to `ChatInput`.

## 2026-06-04 (session 12)

Added memory CRUD tools and refactored memory search scoring.

`rag.py`: extracted shared `_llm_score(query, rows) → list[float]` helper — uses `llm.with_structured_output(_Scores)` (Pydantic `_Scores(scores: list[float])`) instead of the previous fragile regex-over-raw-string approach; falls back to RRF scores on any error. Applied to `search_database_impl` (replaces inline regex rerank block; `import re` removed), `search_memories_impl` (now filters by score ≥ 8), and new `search_memories_with_ids_impl` (filters by score ≥ 5, returns `list[{memory_id, content}]` for use by delete/update tools).

`db.py`: added `delete_memories(db, memory_ids: list[str]) → int` — deletes from `documents` by `metadata->>'memory_id' = ANY(...)` then from `memories` by UUID, returns row count. Added `update_memory(db, memory_id, new_content, keywords)` — re-embeds new content, updates both `memories.content` and `documents` (content, embedding, fts, keywords) in place.

`graph.py`: added `delete_memory` tool — searches top-3 candidates via `search_memories_with_ids_impl`, deletes only the single best match (`matches[:1]`); prevents collateral deletion of unrelated memories sharing a name/term. Added `update_memory` tool — finds single best match, re-extracts keywords via `_extract_keywords`, updates in place; preferred over delete+save for "change my name/preference" patterns. Fixed a bug where the old `delete_memory` deleted all matches above threshold (score ≥ 5), which caused unrelated memories (e.g., "Anh Tu is a backend engineer") to be wiped when deleting a name memory. All six tools registered in `_tools`.

## 2026-06-03 (session 11)

Added a persistent memory system. New `memories` table (migration `0004_add_memories`): `id UUID`, `type TEXT` (`'hot'`|`'cold'`), `content TEXT`, `created_at TIMESTAMPTZ`. Migration `0005_update_memories_remove_keywords`: truncated stale data, dropped `keywords` column from `memories` (keywords live exclusively in `documents`). Both hot and cold memories are indexed in `documents` with `collection='memory'`: single-row insert per memory, embedding from `aembed_query`, FTS built from extracted keywords (`to_tsvector('english', keywords_joined)`), `metadata` carries `memory_id` + `type`.

`db.py`: added `save_memory(db, type, content) → str`, `get_hot_memories(db) → list[str]`, `save_memory_embedding(db, memory_id, type, content, keywords)` (replaces old `save_cold_memory_embedding`; applies to both types). `rag.py`: added `search_memories_impl(query, limit, db)` — hybrid search scoped to `collection='memory'`, returns content strings directly (no rerank). `sql.py`: added `HYBRID_SEARCH_MEMORIES_SQL` — same RRF pattern as existing queries, filtered to `collection='memory'`, no join to `conversations`.

`graph.py`: two new LangGraph tools — `save_memory` (extracts keywords via `_extract_keywords`, saves to `memories` + `documents` for both hot and cold) and `retrieve_memories` (hybrid search across all memory types). `_extract_keywords` uses `llm.with_structured_output(_Keywords)` where `_Keywords` is a Pydantic model (`keywords: list[str]`). `_keywords_llm` bound at module level. Tool descriptions tuned: hot = timeless identity facts (name, persistent preferences); cold = events, activities, purchases, anything time-specific. `routers/chat.py`: fetches all hot memories via `get_hot_memories` before building the message list; appends them to the system prompt as "Things to always remember". Tool calls logged to stdout via `on_tool_start` / `on_tool_end` events in the `astream_events` loop. `models.py`: added `Memory` Pydantic model.

## 2026-06-02 (session 10)

Updated `documents` table schema and insert logic. Migration `0003_update_documents`: removed `GENERATED ALWAYS AS ... STORED` from the `fts` column via `ALTER TABLE documents ALTER COLUMN fts DROP EXPRESSION` (PG12+ — preserves existing values and GIN index, no backfill); added `keywords TEXT[] NOT NULL DEFAULT '{}'` column (for caller-supplied tags, not searched). `db.py`: `save_chunks` gains an optional `keywords: list[str] = []` parameter; INSERT now explicitly sets `fts = to_tsvector('english', $2)` and `keywords = $5::text[]`. Existing callers (`routers/chat.py`, `backfill_embeddings.py`) unchanged.

## 2026-06-02 (session 9)

Replaced the LangGraph intent-router pattern with a ReAct tool-calling loop. `graph.py` fully rewritten: `ChatState` simplified to `messages` + `db` (dropped `rag_messages` and `should_retrieve`); `route_intent`, `retrieve_rag`, `_call_model`, and `_route_edge` removed. Two `@tool` functions added: `search_database` wraps `search_database_impl` with `db` hidden from the LLM schema via `InjectedState("db")`; `search_web` calls Tavily (`TavilyClient`, max 5 results). LLM bound via `llm.bind_tools([search_database, search_web])`. Graph topology changed to `START → agent → tools_condition → tools → agent` (ReAct loop) or `→ END`. RAG context no longer injected into the system prompt — tool results are appended as `ToolMessage` turns and the LLM reads them naturally on the next iteration. `rag.py`: `rag_retrieve` renamed to `search_database_impl`. `models.py`: `RAGRouterDecision` removed. `requirements.txt`: added `tavily-python>=0.5.0`. `routers/chat.py`: removed `rag_messages`/`should_retrieve` from initial graph state. `routers/search.py`: updated import to alias `search_database_impl as rag_retrieve`.

## 2026-06-01 (session 8)

Added LangGraph RAG router to the chat pipeline. `llm.py` stripped to primitives (`llm`, `embeddings_model`) — graph definition moved to new `graph.py`. `graph.py` extends the LangGraph graph to three nodes with a conditional edge: `route_intent` uses `llm.with_structured_output(RAGRouterDecision)` (a `TypedDict`, not `BaseModel`, to avoid Pydantic serialization warnings) to classify whether the user intends to retrieve past context; `retrieve_rag` calls `rag_retrieve` only when `should_retrieve=True`; `agent` builds the final message list and calls the LLM. When RAG messages are available, they are injected into the system prompt as explicit memory context (not as orphaned `AIMessage` turns, which the LLM ignores). `routers/chat.py` no longer calls `rag_retrieve` directly — it passes `db` in the graph state and filters `on_chat_model_stream` events to the `agent` node only. RAG retrieval simplified: HyDE removed — user query is embedded directly. `rag_retrieve` now returns `list[str]` (all assistant messages scoring ≥ 8, up to `limit`) instead of a single `MessagePair`; qualifying messages are batch-fetched in one `WHERE id = ANY($1::uuid[])` query. `MessagePair` model deleted. `POST /search/rag/messages` updated to return `list[str]`.

## 2026-05-18 (session 7)

Pure structural refactor — no behaviour changes. Backend: split `main.py` (665 lines) into focused modules: `llm.py` (LLM + embeddings + LangGraph graph; owns `load_dotenv()` so OpenAI clients can initialise before `main.py` runs), `models.py` (all Pydantic models), `sql.py` (SQL constants), `db.py` (`chunk_text`, `save_chunks`, cursor helpers), `rag.py` (`rag_retrieve`), `dependencies.py` (`get_db` FastAPI dependency), and `routers/` package with `conversations.py`, `chat.py`, `search.py`. `main.py` reduced to ~30 lines of app setup. Frontend: split `page.tsx` (516 lines) into `types/index.ts` (shared interfaces), `lib/api.ts` (API_URL), four hooks (`useConversations`, `useMessages`, `useChat`, `useSearch`), and four pure-props components (`Sidebar`, `SearchModal`, `MessageList`, `ChatInput`). `page.tsx` reduced to ~80 lines of wiring. `useMessages` owns `activeId` to avoid stale closures in `loadOlderMessages`; uses `activeIdRef` pattern. `useSearch` takes `onGoToResult` callback; `page.tsx` wires it to set `targetMessageIdRef` then call `selectConversation`.

## 2026-05-18 (session 6)

Added RAG retrieval pipeline and injected it into the chat context window. New endpoints in `backend/main.py`: `POST /search/rag` (HyDE + hybrid search + LLM reranking — returns `hypothetical_answer` and ranked `chunks` with `relevance_score`); `POST /search/rag/messages` (same pipeline, returns a single `MessagePair | null` — only the best assistant chunk with `relevance_score >= 8`, paired with the user message that preceded it). Both endpoints search only `role='assistant'` chunks via `_HYBRID_SEARCH_ASSISTANT_SQL`. Shared retrieval logic extracted into `_rag_retrieve(query, limit, db)`. LLM reranking uses regex extraction (`re.search(r'\[[\d\s.,]+\]', ...)`) to parse scores from the model's response regardless of surrounding text. `POST /chat` now calls `_rag_retrieve` before building `lc_messages`: if a relevant pair is found and its `message_id` is not already in the 10 most recent context messages, the pair is prepended as a `HumanMessage`/`AIMessage` before the conversation history. New Pydantic models: `RagSearchRequest`, `RankedChunk`, `RagSearchResponse`, `MessagePair` (includes `message_id` for deduplication).

## 2026-05-15 (session 5)

Moved context window control to the backend and added cursor-based pagination. Backend: `ChatRequest` simplified to `{ message: str, conversation_id: str }` — history is no longer sent by the frontend. `POST /chat` saves the user message first, then fetches the 10 most recent messages from DB (`ORDER BY created_at DESC LIMIT 10`, reversed) to build LLM context. `GET /conversations` now returns `{ items, next_cursor }` with keyset cursor pagination (10/page, ordered by `updated_at DESC, id DESC`); cursor is a base64url-encoded `updated_at|id` string. `GET /conversations/{id}/messages` now returns `{ items, prev_cursor }` — default fetches newest 10 (reversed to oldest-first for UI); `?limit=0` bypasses pagination (used for search navigation); cursor param loads older pages. Added `_encode_cursor` / `_decode_cursor` helpers. Frontend: `sendMessage` sends only `{ message, conversation_id }`. `fetchConversations(cursor?)` appends on load-more, resets on initial; "Load more" button in sidebar when `convHasMore`. `selectConversation(id, loadAll?)` reads paginated response; `loadAll=true` used by `goToResult` so the target message is always in the DOM. New `loadOlderMessages()` prepends older messages and restores scroll position using `messagesContainerRef` + `scrollRestoreRef` (captures `scrollHeight` before state update, restores `scrollTop` in `useEffect` after re-render). "Load older messages" button at top of chat area. `newChat` resets cursor state.

## 2026-05-15 (session 4)

Added message search feature. Backend: `GET /conversations/{id}/messages` now returns `id` per message row (needed for DOM anchoring). All three search endpoints (`POST /search`, `/search/semantic`, `/search/keyword`) now join `conversations.created_at` and include it as `conversation_created_at` in every result. Frontend: added `SearchResult` interface; `Message` interface gained optional `id`; message divs rendered with `id={msg.id}` for stable scroll anchors. Added 🔍 button in the sidebar header that opens a centered modal popup (fixed overlay, `z-50`, click-backdrop-to-close, Escape-to-close). Modal contains a search input (auto-focused, Enter to search), scrollable results list (conversation title + date + 3-line content excerpt), and a Search button. Clicking a result calls `goToResult` which sets `targetMessageIdRef.current`, closes the modal, and awaits `selectConversation`. A single merged `useEffect([messages])` handles both scroll cases: if `targetMessageIdRef.current` is set it scrolls to that element with a 2-second indigo ring highlight and returns early; otherwise it scrolls to the bottom. Using a ref (not state) for the target prevents a re-render that would trigger the scroll-to-bottom path.

## 2026-05-14/15 (session 3)

Added hybrid search backend. Introduced a generic `documents` table (`collection text`, `content text`, `metadata jsonb`, `embedding vector(1536)`, generated `fts tsvector`) via Alembic migration `0002_add_documents`. Switched Docker image from `postgres:16-alpine` to `pgvector/pgvector:pg16` to enable the `vector` extension. Added `pgvector` and `tiktoken` to requirements. Implemented `chunk_text` (512-token window, 64-token overlap, `cl100k_base` encoder) and `save_chunks` helper. Modified `POST /chat` to chunk and embed both user and assistant messages into `documents` after each streaming round-trip (using `text-embedding-3-small`). Added three search endpoints: `POST /search` (hybrid RRF fusion), `POST /search/semantic` (pgvector cosine similarity with optional `threshold` param), `POST /search/keyword` (tsvector `ts_rank`). Added `backfill_embeddings.py` one-time script to chunk and embed existing messages.

## 2026-05-13 (session 2)

Added persistent chat history with sidebar. Introduced Docker Compose + PostgreSQL 16. Set up Alembic migrations (`0001_create_conversations_messages`). Added `asyncpg` pool to FastAPI via `lifespan`. New endpoints: `GET/POST /conversations`, `DELETE /conversations/{id}`, `GET /conversations/{id}/messages`. Modified `POST /chat` to accept `conversation_id`, persist both user and assistant messages, auto-title conversation from first user message. Redesigned frontend: sidebar (256px) with conversation list, "+ New Chat" button, delete-on-hover. Clicking a conversation loads its history; first send auto-creates a conversation.

## 2026-05-13 (session 1)

Switched the backend from direct OpenAI to LangGraph while keeping gpt-4o-mini, then updated CLAUDE.md with backend and frontend structure, architecture, and key symbols for faster future sessions. No code changes pending.
