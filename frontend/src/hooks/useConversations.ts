"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL } from "../lib/api";
import type { Conversation } from "../types";

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convNextCursor, setConvNextCursor] = useState<string | null>(null);
  const [convHasMore, setConvHasMore] = useState(false);

  const fetchConversations = useCallback(async (cursor?: string) => {
    const url = cursor
      ? `${API_URL}/conversations?cursor=${cursor}`
      : `${API_URL}/conversations`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    setConversations((prev) => (cursor ? [...prev, ...data.items] : data.items));
    setConvNextCursor(data.next_cursor);
    setConvHasMore(!!data.next_cursor);
  }, []);

  const createConversation = useCallback(async (): Promise<Conversation | null> => {
    const res = await fetch(`${API_URL}/conversations`, { method: "POST" });
    if (!res.ok) return null;
    return res.json();
  }, []);

  const deleteConversation = useCallback(
    async (id: string) => {
      await fetch(`${API_URL}/conversations/${id}`, { method: "DELETE" });
      fetchConversations();
    },
    [fetchConversations]
  );

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  return {
    conversations,
    convNextCursor,
    convHasMore,
    fetchConversations,
    createConversation,
    deleteConversation,
  };
}
