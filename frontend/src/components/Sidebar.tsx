import type { Conversation } from "../types";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  hoveredId: string | null;
  convHasMore: boolean;
  convNextCursor: string | null;
  searchOpen: boolean;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (e: React.MouseEvent, id: string) => void;
  onLoadMore: () => void;
  onHoverConversation: (id: string | null) => void;
  onToggleSearch: () => void;
}

export default function Sidebar({
  conversations,
  activeId,
  hoveredId,
  convHasMore,
  searchOpen,
  onNewChat,
  onSelectConversation,
  onDeleteConversation,
  onLoadMore,
  onHoverConversation,
  onToggleSearch,
}: SidebarProps) {
  return (
    <aside className="w-64 flex-shrink-0 flex flex-col bg-gray-950 border-r border-gray-700">
      <div className="p-3 border-b border-gray-700 flex gap-2">
        <button
          onClick={onNewChat}
          className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-gray-200 hover:bg-gray-800 transition-colors border border-gray-700"
        >
          <span className="text-lg leading-none">+</span>
          New Chat
        </button>
        <button
          onClick={onToggleSearch}
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
          <p className="text-xs text-gray-600 text-center mt-8 px-4">No conversations yet</p>
        )}
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => onSelectConversation(conv.id)}
            onMouseEnter={() => onHoverConversation(conv.id)}
            onMouseLeave={() => onHoverConversation(null)}
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
                onClick={(e) => onDeleteConversation(e, conv.id)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-red-400 transition-colors"
                title="Delete"
              >
                ×
              </button>
            )}
          </div>
        ))}
        {convHasMore && (
          <button
            onClick={onLoadMore}
            className="w-full text-xs text-gray-500 hover:text-gray-300 py-2 transition-colors"
          >
            Load more
          </button>
        )}
      </div>
    </aside>
  );
}
