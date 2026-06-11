"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { Conversation, InterruptData, Message } from "../types";

interface UseChatOptions {
  activeId: string | null;
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  onCreateConversation: () => Promise<Conversation | null>;
  onSetActiveId: (id: string) => void;
  onAfterSend: () => void;
}

export function useChat({
  activeId,
  messages,
  setMessages,
  onCreateConversation,
  onSetActiveId,
  onAfterSend,
}: UseChatOptions) {
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingInterrupt, setPendingInterrupt] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const parseStream = useCallback(
    async (reader: ReadableStreamDefaultReader<Uint8Array>): Promise<boolean> => {
      const decoder = new TextDecoder();
      let buffer = "";
      let foundInterrupt = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;
          try {
            const parsed = JSON.parse(data) as { text?: string; interrupt?: InterruptData };
            if (parsed.text) {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = { ...last, content: last.content + parsed.text! };
                return updated;
              });
            } else if (parsed.interrupt) {
              setMessages((prev) => {
                // Remove trailing empty assistant placeholder if present
                const filtered = prev.filter(
                  (m, i) =>
                    !(i === prev.length - 1 && m.role === "assistant" && m.content === "")
                );
                return [
                  ...filtered,
                  { role: "interrupt", content: "", interrupt: parsed.interrupt },
                ];
              });
              setPendingInterrupt(true);
              foundInterrupt = true;
            }
          } catch {
            // ignore malformed events
          }
        }
      }
      return foundInterrupt;
    },
    [setMessages]
  );

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming || pendingInterrupt) return;

    let currentId = activeId;
    if (!currentId) {
      const conv = await onCreateConversation();
      if (!conv) return;
      currentId = conv.id;
      onSetActiveId(currentId);
    }

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setIsStreaming(true);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: currentId }),
      });

      if (!res.ok || !res.body) throw new Error("Request failed");

      const foundInterrupt = await parseStream(res.body.getReader());
      if (!foundInterrupt) onAfterSend();
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Something went wrong. Please try again.",
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  }, [
    input,
    isStreaming,
    pendingInterrupt,
    activeId,
    onCreateConversation,
    onSetActiveId,
    setMessages,
    onAfterSend,
    parseStream,
  ]);

  const resolveInterrupt = useCallback(
    async (approved: boolean) => {
      if (!activeId) return;

      setMessages((prev) => prev.filter((m) => m.role !== "interrupt"));
      setPendingInterrupt(false);
      setIsStreaming(true);
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      try {
        const res = await fetch(`${API_URL}/chat/resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: activeId, approved }),
        });

        if (!res.ok || !res.body) throw new Error("Resume failed");

        const foundInterrupt = await parseStream(res.body.getReader());
        if (!foundInterrupt) onAfterSend();
      } catch {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant" && last.content === "") {
            updated[updated.length - 1] = {
              role: "assistant",
              content: "Something went wrong. Please try again.",
            };
          }
          return updated;
        });
      } finally {
        setIsStreaming(false);
      }
    },
    [activeId, setMessages, onAfterSend, parseStream]
  );

  const setInterruptFromReload = useCallback(
    (payload: InterruptData) => {
      setMessages((prev) => [
        ...prev,
        { role: "interrupt", content: "", interrupt: payload },
      ]);
      setPendingInterrupt(true);
    },
    [setMessages]
  );

  return {
    input,
    setInput,
    isStreaming,
    pendingInterrupt,
    sendMessage,
    resolveInterrupt,
    setInterruptFromReload,
    textareaRef,
  };
}
