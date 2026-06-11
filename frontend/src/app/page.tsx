"use client";

import { useCallback, useRef, useState } from "react";
import ChatInput from "../components/ChatInput";
import MessageList from "../components/MessageList";
import SearchModal from "../components/SearchModal";
import Sidebar from "../components/Sidebar";
import { useChat } from "../hooks/useChat";
import { useConversations } from "../hooks/useConversations";
import { useMessages } from "../hooks/useMessages";
import { useSearch } from "../hooks/useSearch";
import { API_URL } from "../lib/api";
import type { InterruptData } from "../types";

export default function ChatPage() {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const {
    conversations,
    convNextCursor,
    convHasMore,
    fetchConversations,
    createConversation,
    deleteConversation,
  } = useConversations();

  const {
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
  } = useMessages();

  // ref so selectConversation (defined before useChat) can call setInterruptFromReload
  const setInterruptFromReloadRef = useRef<((payload: InterruptData) => void) | null>(null);

  const selectConversation = useCallback(
    async (id: string, loadAll = false) => {
      await loadMessages(id, loadAll);
      try {
        const r = await fetch(`${API_URL}/conversations/${id}/pending-interrupt`);
        if (r.ok) {
          const data = await r.json();
          if (data.interrupt) {
            setInterruptFromReloadRef.current?.(data.interrupt);
          }
        }
      } catch {}
    },
    [loadMessages]
  );

  const newChat = useCallback(() => {
    setActiveId(null);
    resetMessages();
  }, [setActiveId, resetMessages]);

  const handleDeleteConversation = useCallback(
    async (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
      await deleteConversation(id);
    },
    [activeId, setActiveId, setMessages, deleteConversation]
  );

  const {
    input,
    setInput,
    isStreaming,
    pendingInterrupt,
    sendMessage,
    resolveInterrupt,
    setInterruptFromReload,
    textareaRef,
  } = useChat({
    activeId,
    messages,
    setMessages,
    onCreateConversation: createConversation,
    onSetActiveId: setActiveId,
    onAfterSend: fetchConversations,
  });

  // wire the ref so selectConversation can call setInterruptFromReload
  setInterruptFromReloadRef.current = setInterruptFromReload;

  const {
    searchOpen,
    setSearchOpen,
    searchQuery,
    setSearchQuery,
    searchResults,
    searchLoading,
    runSearch,
    goToResult,
    searchInputRef,
  } = useSearch((conversationId, messageId) => {
    targetMessageIdRef.current = messageId;
    selectConversation(conversationId, true);
  });

  return (
    <div className="flex h-screen bg-gray-900">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        hoveredId={hoveredId}
        convHasMore={convHasMore}
        convNextCursor={convNextCursor}
        searchOpen={searchOpen}
        onNewChat={newChat}
        onSelectConversation={(id) => selectConversation(id)}
        onDeleteConversation={handleDeleteConversation}
        onLoadMore={() => fetchConversations(convNextCursor ?? undefined)}
        onHoverConversation={setHoveredId}
        onToggleSearch={() => setSearchOpen((v) => !v)}
      />

      {searchOpen && (
        <SearchModal
          searchQuery={searchQuery}
          searchResults={searchResults}
          searchLoading={searchLoading}
          searchInputRef={searchInputRef}
          onQueryChange={setSearchQuery}
          onSearch={runSearch}
          onClose={() => setSearchOpen(false)}
          onGoToResult={goToResult}
        />
      )}

      <div className="flex flex-col flex-1 min-w-0">
        <header className="bg-gray-900 border-b border-gray-700 px-6 py-4 shadow-sm flex-shrink-0">
          <h1 className="text-lg font-semibold text-gray-100">Hanet Chat</h1>
          <p className="text-xs text-gray-500 mt-0.5">Powered by Claude</p>
        </header>

        <MessageList
          messages={messages}
          msgHasOlder={msgHasOlder}
          isStreaming={isStreaming}
          pendingInterrupt={pendingInterrupt}
          messagesContainerRef={messagesContainerRef}
          bottomRef={bottomRef}
          onLoadOlderMessages={loadOlderMessages}
          onResolveInterrupt={resolveInterrupt}
        />

        <ChatInput
          input={input}
          isStreaming={isStreaming || pendingInterrupt}
          textareaRef={textareaRef}
          onInputChange={setInput}
          onSend={sendMessage}
        />
      </div>
    </div>
  );
}
