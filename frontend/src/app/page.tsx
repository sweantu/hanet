"use client";

import { useCallback, useState } from "react";
import ChatInput from "../components/ChatInput";
import MessageList from "../components/MessageList";
import SearchModal from "../components/SearchModal";
import Sidebar from "../components/Sidebar";
import { useChat } from "../hooks/useChat";
import { useConversations } from "../hooks/useConversations";
import { useMessages } from "../hooks/useMessages";
import { useSearch } from "../hooks/useSearch";

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

  const selectConversation = useCallback(
    async (id: string, loadAll = false) => {
      await loadMessages(id, loadAll);
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

  const { input, setInput, isStreaming, sendMessage, textareaRef } = useChat({
    activeId,
    messages,
    setMessages,
    onCreateConversation: createConversation,
    onSetActiveId: setActiveId,
    onAfterSend: fetchConversations,
  });

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
          messagesContainerRef={messagesContainerRef}
          bottomRef={bottomRef}
          onLoadOlderMessages={loadOlderMessages}
        />

        <ChatInput
          input={input}
          isStreaming={isStreaming}
          textareaRef={textareaRef}
          onInputChange={setInput}
          onSend={sendMessage}
        />
      </div>
    </div>
  );
}
