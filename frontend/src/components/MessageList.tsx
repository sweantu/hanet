import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  msgHasOlder: boolean;
  isStreaming: boolean;
  pendingInterrupt: boolean;
  messagesContainerRef: React.RefObject<HTMLDivElement | null>;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  onLoadOlderMessages: () => void;
  onResolveInterrupt: (approved: boolean) => void;
}

export default function MessageList({
  messages,
  msgHasOlder,
  isStreaming,
  pendingInterrupt,
  messagesContainerRef,
  bottomRef,
  onLoadOlderMessages,
  onResolveInterrupt,
}: MessageListProps) {
  return (
    <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {msgHasOlder && (
          <div className="text-center pt-2 pb-4">
            <button
              onClick={onLoadOlderMessages}
              className="text-xs text-indigo-400 hover:text-indigo-300 px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors"
            >
              Load older messages
            </button>
          </div>
        )}
        {messages.length === 0 && (
          <div className="text-center text-gray-500 pt-24 select-none">
            <p className="text-4xl mb-4">💬</p>
            <p className="text-lg font-medium text-gray-400">How can I help you today?</p>
            <p className="text-sm mt-1">Type a message below to get started.</p>
          </div>
        )}

        {messages.map((msg, i) => {
          if (msg.role === "interrupt" && msg.interrupt) {
            return (
              <div key={msg.id ?? `interrupt-${i}`} className="flex justify-center">
                <div className="max-w-[75%] px-4 py-4 rounded-2xl border border-amber-500/50 bg-amber-950/30 text-sm space-y-3">
                  <div className="flex items-start gap-2">
                    <span className="text-amber-400 text-base leading-none mt-0.5">⚠</span>
                    <p className="flex-1 text-gray-200 whitespace-pre-wrap break-words">
                      {msg.interrupt.summary}
                    </p>
                  </div>
                  <div className="flex gap-2 justify-end">
                    <button
                      onClick={() => onResolveInterrupt(false)}
                      disabled={!pendingInterrupt}
                      className="px-4 py-1.5 rounded-lg text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 transition-colors"
                    >
                      Deny
                    </button>
                    <button
                      onClick={() => onResolveInterrupt(true)}
                      disabled={!pendingInterrupt}
                      className="px-4 py-1.5 rounded-lg text-xs font-medium bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-40 transition-colors"
                    >
                      Approve
                    </button>
                  </div>
                </div>
              </div>
            );
          }

          const isLastAssistant =
            isStreaming && i === messages.length - 1 && msg.role === "assistant";
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
  );
}
