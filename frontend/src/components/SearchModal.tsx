import type { SearchResult } from "../types";

interface SearchModalProps {
  searchQuery: string;
  searchResults: SearchResult[];
  searchLoading: boolean;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  onQueryChange: (q: string) => void;
  onSearch: () => void;
  onClose: () => void;
  onGoToResult: (result: SearchResult) => void;
}

export default function SearchModal({
  searchQuery,
  searchResults,
  searchLoading,
  searchInputRef,
  onQueryChange,
  onSearch,
  onClose,
  onGoToResult,
}: SearchModalProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
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
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder="Search messages…"
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 focus:outline-none"
          />
          <button
            onClick={onClose}
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
              onClick={() => onGoToResult(r)}
              className="w-full text-left px-5 py-4 hover:bg-gray-800 transition-colors"
            >
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <p className="text-sm font-medium text-gray-100 truncate">{r.conversation_title}</p>
                <p className="text-xs text-gray-500 flex-shrink-0">
                  {new Date(r.conversation_created_at).toLocaleDateString()}
                </p>
              </div>
              <p className="text-xs text-gray-400 leading-relaxed line-clamp-3">{r.content}</p>
            </button>
          ))}
        </div>

        <div className="px-4 py-3 border-t border-gray-700 flex justify-end">
          <button
            onClick={onSearch}
            disabled={searchLoading || !searchQuery.trim()}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {searchLoading ? "Searching…" : "Search"}
          </button>
        </div>
      </div>
    </div>
  );
}
