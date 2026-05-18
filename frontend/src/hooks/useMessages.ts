"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { Message } from "../types";

export function useMessages() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [msgPrevCursor, setMsgPrevCursor] = useState<string | null>(null);
  const [msgHasOlder, setMsgHasOlder] = useState(false);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const scrollRestoreRef = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const targetMessageIdRef = useRef<string | null>(null);

  // activeId ref to avoid stale closures in loadOlderMessages
  const activeIdRef = useRef(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    if (scrollRestoreRef.current !== null) {
      const container = messagesContainerRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight - scrollRestoreRef.current;
      }
      scrollRestoreRef.current = null;
      return;
    }
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

  const loadMessages = useCallback(async (id: string, loadAll = false) => {
    setActiveId(id);
    setMsgPrevCursor(null);
    setMsgHasOlder(false);
    const url = loadAll
      ? `${API_URL}/conversations/${id}/messages?limit=0`
      : `${API_URL}/conversations/${id}/messages`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    setMessages(data.items);
    setMsgPrevCursor(data.prev_cursor);
    setMsgHasOlder(!!data.prev_cursor);
  }, []);

  const loadOlderMessages = useCallback(async () => {
    if (!msgPrevCursor || !activeIdRef.current) return;
    const container = messagesContainerRef.current;
    scrollRestoreRef.current = container?.scrollHeight ?? null;
    const res = await fetch(
      `${API_URL}/conversations/${activeIdRef.current}/messages?cursor=${msgPrevCursor}`
    );
    if (!res.ok) return;
    const data = await res.json();
    setMessages((prev) => [...data.items, ...prev]);
    setMsgPrevCursor(data.prev_cursor);
    setMsgHasOlder(!!data.prev_cursor);
  }, [msgPrevCursor]);

  const resetMessages = useCallback(() => {
    setMessages([]);
    setMsgPrevCursor(null);
    setMsgHasOlder(false);
  }, []);

  return {
    activeId,
    setActiveId,
    messages,
    setMessages,
    msgHasOlder,
    loadMessages,
    loadOlderMessages,
    resetMessages,
    messagesContainerRef,
    bottomRef,
    targetMessageIdRef,
    scrollRestoreRef,
  };
}
