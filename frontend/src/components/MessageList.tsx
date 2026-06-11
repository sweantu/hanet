import { useState } from "react";
import type { Message, ResumeAction } from "../types";

interface MessageListProps {
  messages: Message[];
  msgHasOlder: boolean;
  isStreaming: boolean;
  pendingInterrupt: boolean;
  messagesContainerRef: React.RefObject<HTMLDivElement | null>;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  onLoadOlderMessages: () => void;
  onResolveInterrupt: (action: ResumeAction, message?: string) => void;
}

function InterruptCard({
  summary,
  pendingInterrupt,
  onResolve,
}: {
  summary: string;
  pendingInterrupt: boolean;
  onResolve: (action: ResumeAction, message?: string) => void;
}) {
  const [showReplan, setShowReplan] = useState(false);
  const [replanText, setReplanText] = useState("");

  const handleSubmit = () => {
    const trimmed = replanText.trim();
    if (!trimmed) return;
    onResolve("replan", trimmed);
  };

  return (
    <div className="max-w-[75%] px-4 py-4 rounded-2xl border border-amber-500/50 bg-amber-950/30 text-sm space-y-3">
      <div className="flex items-start gap-2">
        <span className="text-amber-400 text-base leading-none mt-0.5">⚠</span>
        <p className="flex-1 text-gray-200 whitespace-pre-wrap break-words">{summary}</p>
      </div>
      {showReplan && (
        <textarea
          autoFocus
          className="w-full rounded-lg bg-gray-800 border border-gray-600 text-gray-100 text-xs px-3 py-2 resize-none focus:outline-none focus:border-amber-500"
          rows={3}
          placeholder="Describe what to do instead…"
          value={replanText}
          onChange={(e) => setReplanText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
      )}
      <div className="flex gap-2 justify-end">
        {showReplan ? (
          <>
            <button
              onClick={() => { setShowReplan(false); setReplanText(""); }}
              disabled={!pendingInterrupt}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!pendingInterrupt || !replanText.trim()}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 transition-colors"
            >
              Submit
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => onResolve("deny")}
              disabled={!pendingInterrupt}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 transition-colors"
            >
              Deny
            </button>
            <button
              onClick={() => setShowReplan(true)}
              disabled={!pendingInterrupt}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-700 text-white hover:bg-blue-600 disabled:opacity-40 transition-colors"
            >
              Re-plan
            </button>
            <button
              onClick={() => onResolve("approve")}
              disabled={!pendingInterrupt}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-40 transition-colors"
            >
              Approve
            </button>
          </>
        )}
      </div>
    </div>
  );
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
                <InterruptCard
                  summary={msg.interrupt.summary}
                  pendingInterrupt={pendingInterrupt}
                  onResolve={onResolveInterrupt}
                />
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
