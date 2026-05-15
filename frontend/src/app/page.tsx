"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
}

interface Conversation {
  id: string;
  title: string;
  created_at: string;
}

interface SearchResult {
  id: string;
  content: string;
  conversation_title: string;
  conversation_created_at: string;
  metadata: { conversation_id: string; message_id: string; role: string };
  rrf_score: number;
}

const API_URL = "http://localhost:8000";

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const targetMessageIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const fetchConversations = useCallback(async () => {
    const res = await fetch(`${API_URL}/conversations`);
    if (res.ok) setConversations(await res.json());
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  useEffect(() => {
    if (targetMessageIdRef.current && messages.length > 0) {
      const el = document.getElementById(targetMessageIdRef.current);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-indigo-400", "rounded-2xl");
        setTimeout(() => el.classList.remove("ring-2", "ring-indigo-400", "rounded-2xl"), 2000);
        targetMessageIdRef.current = null;
        return;
      }
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  useEffect(() => {
    if (searchOpen) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else {
      setSearchQuery("");
      setSearchResults([]);
    }
  }, [searchOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setSearchOpen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const selectConversation = useCallback(async (id: string) => {
    setActiveId(id);
    const res = await fetch(`${API_URL}/conversations/${id}/messages`);
    if (res.ok) setMessages(await res.json());
  }, []);

  const newChat = useCallback(() => {
    setActiveId(null);
    setMessages([]);
    setInput("");
  }, []);

  const deleteConversation = useCallback(
    async (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      await fetch(`${API_URL}/conversations/${id}`, { method: "DELETE" });
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
      fetchConversations();
    },
    [activeId, fetchConversations]
  );

  const runSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    const res = await fetch(`${API_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: searchQuery, limit: 10 }),
    });
    if (res.ok) setSearchResults(await res.json());
    setSearchLoading(false);
  }, [searchQuery]);

  const goToResult = useCallback(
    async (result: SearchResult) => {
      setSearchOpen(false);
      targetMessageIdRef.current = result.metadata.message_id;
      await selectConversation(result.metadata.conversation_id);
    },
    [selectConversation]
  );

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    let currentId = activeId;
    if (!currentId) {
      const res = await fetch(`${API_URL}/conversations`, { method: "POST" });
      const conv: Conversation = await res.json();
      currentId = conv.id;
      setActiveId(currentId);
    }

    const newMessages: Message[] = [
      ...messages,
      { role: "user", content: text },
    ];
    setMessages(newMessages);
    setInput("");
    setIsStreaming(true);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: newMessages, conversation_id: currentId }),
      });

      if (!res.ok || !res.body) throw new Error("Request failed");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;

          try {
            const { text: chunk } = JSON.parse(data) as { text: string };
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = {
                ...last,
                content: last.content + chunk,
              };
              return updated;
            });
          } catch {
            // ignore malformed events
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Something went wrong. Please try again.",
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
      fetchConversations();
    }
  }, [input, isStreaming, messages, activeId, fetchConversations]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 flex flex-col bg-gray-950 border-r border-gray-700">
        <div className="p-3 border-b border-gray-700 flex gap-2">
          <button
            onClick={newChat}
            className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-gray-200 hover:bg-gray-800 transition-colors border border-gray-700"
          >
            <span className="text-lg leading-none">+</span>
            New Chat
          </button>
          <button
            onClick={() => setSearchOpen((v) => !v)}
            title="Search messages"
            className={`flex items-center justify-center w-9 h-9 rounded-lg text-sm border transition-colors ${
              searchOpen
                ? "bg-indigo-700/40 border-indigo-500 text-indigo-300"
                : "border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
            }`}
          >
            🔍
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {conversations.length === 0 && (
            <p className="text-xs text-gray-600 text-center mt-8 px-4">
              No conversations yet
            </p>
          )}
          {conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => selectConversation(conv.id)}
              onMouseEnter={() => setHoveredId(conv.id)}
              onMouseLeave={() => setHoveredId(null)}
              className={`group relative mx-2 my-0.5 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                activeId === conv.id
                  ? "bg-indigo-700/40 text-gray-100"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              }`}
            >
              <p className="text-sm truncate pr-6">{conv.title}</p>
              <p className="text-xs text-gray-600 mt-0.5">
                {new Date(conv.created_at).toLocaleDateString()}
              </p>
              {hoveredId === conv.id && (
                <button
                  onClick={(e) => deleteConversation(e, conv.id)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-red-400 transition-colors"
                  title="Delete"
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
      </aside>

      {/* Search modal */}
      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setSearchOpen(false)}
        >
          <div
            className="w-full max-w-xl bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-700">
              <span className="text-gray-400 text-sm">🔍</span>
              <input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
                placeholder="Search messages…"
                className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 focus:outline-none"
              />
              <button
                onClick={() => setSearchOpen(false)}
                className="text-gray-500 hover:text-gray-300 text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <div className="overflow-y-auto max-h-[60vh] divide-y divide-gray-800">
              {searchLoading && (
                <p className="text-sm text-gray-500 text-center py-6">Searching…</p>
              )}
              {!searchLoading && searchQuery && searchResults.length === 0 && (
                <p className="text-sm text-gray-600 text-center py-6">No results</p>
              )}
              {searchResults.map((r) => (
                <button
                  key={r.id}
                  onClick={() => goToResult(r)}
                  className="w-full text-left px-5 py-4 hover:bg-gray-800 transition-colors"
                >
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <p className="text-sm font-medium text-gray-100 truncate">
                      {r.conversation_title}
                    </p>
                    <p className="text-xs text-gray-500 flex-shrink-0">
                      {new Date(r.conversation_created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed line-clamp-3">
                    {r.content}
                  </p>
                </button>
              ))}
            </div>

            <div className="px-4 py-3 border-t border-gray-700 flex justify-end">
              <button
                onClick={runSearch}
                disabled={searchLoading || !searchQuery.trim()}
                className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {searchLoading ? "Searching…" : "Search"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="bg-gray-900 border-b border-gray-700 px-6 py-4 shadow-sm flex-shrink-0">
          <h1 className="text-lg font-semibold text-gray-100">Hanet Chat</h1>
          <p className="text-xs text-gray-500 mt-0.5">Powered by Claude</p>
        </header>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.length === 0 && (
              <div className="text-center text-gray-500 pt-24 select-none">
                <p className="text-4xl mb-4">💬</p>
                <p className="text-lg font-medium text-gray-400">
                  How can I help you today?
                </p>
                <p className="text-sm mt-1">
                  Type a message below to get started.
                </p>
              </div>
            )}

            {messages.map((msg, i) => {
              const isLastAssistant =
                isStreaming &&
                i === messages.length - 1 &&
                msg.role === "assistant";

              return (
                <div
                  key={msg.id ?? i}
                  id={msg.id ?? `msg-${i}`}
                  className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.role === "assistant" && (
                    <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-1">
                      AI
                    </div>
                  )}

                  <div
                    className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words ${
                      msg.role === "user"
                        ? "bg-indigo-600 text-white rounded-tr-sm"
                        : "bg-gray-800 text-gray-100 border border-gray-700 shadow-sm rounded-tl-sm"
                    }`}
                  >
                    {msg.content}
                    {isLastAssistant && (
                      <span className="inline-block w-[2px] h-[1em] bg-gray-400 ml-0.5 align-middle animate-pulse" />
                    )}
                    {isLastAssistant && msg.content === "" && (
                      <span className="text-gray-500 italic">Thinking…</span>
                    )}
                  </div>

                  {msg.role === "user" && (
                    <div className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center text-gray-200 text-xs font-bold flex-shrink-0 mt-1">
                      You
                    </div>
                  )}
                </div>
              );
            })}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input bar */}
        <div className="flex-shrink-0 bg-gray-900 border-t border-gray-700 px-4 py-4">
          <div className="max-w-3xl mx-auto flex items-end gap-3">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Claude… (Enter to send, Shift+Enter for new line)"
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none rounded-xl border border-gray-600 px-4 py-3 text-sm text-gray-100 placeholder-gray-500 bg-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:bg-gray-800 overflow-hidden"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isStreaming}
              className="flex-shrink-0 px-5 py-3 bg-indigo-600 text-white text-sm font-medium rounded-xl hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isStreaming ? "…" : "Send"}
            </button>
          </div>
          <p className="text-center text-xs text-gray-600 mt-2">
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}
