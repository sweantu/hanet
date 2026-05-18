"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { SearchResult } from "../types";

export function useSearch(onGoToResult: (conversationId: string, messageId: string) => void) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else {
      setSearchQuery("");
      setSearchResults([]);
    }
  }, [searchOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

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
    (result: SearchResult) => {
      setSearchOpen(false);
      onGoToResult(result.metadata.conversation_id, result.metadata.message_id);
    },
    [onGoToResult]
  );

  return {
    searchOpen,
    setSearchOpen,
    searchQuery,
    setSearchQuery,
    searchResults,
    searchLoading,
    runSearch,
    goToResult,
    searchInputRef,
  };
}
