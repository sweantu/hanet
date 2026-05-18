interface ChatInputProps {
  input: string;
  isStreaming: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onInputChange: (value: string) => void;
  onSend: () => void;
}

export default function ChatInput({
  input,
  isStreaming,
  textareaRef,
  onInputChange,
  onSend,
}: ChatInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="flex-shrink-0 bg-gray-900 border-t border-gray-700 px-4 py-4">
      <div className="max-w-3xl mx-auto flex items-end gap-3">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message Claude… (Enter to send, Shift+Enter for new line)"
          rows={1}
          disabled={isStreaming}
          className="flex-1 resize-none rounded-xl border border-gray-600 px-4 py-3 text-sm text-gray-100 placeholder-gray-500 bg-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:bg-gray-800 overflow-hidden"
        />
        <button
          onClick={onSend}
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
  );
}
