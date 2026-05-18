"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "../lib/api";
import type { Conversation, Message } from "../types";

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

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

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

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
            const { text: chunk } = JSON.parse(data) as { text: string };
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, content: last.content + chunk };
              return updated;
            });
          } catch {
            // ignore malformed events
          }
        }
      }
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
      onAfterSend();
    }
  }, [input, isStreaming, activeId, onCreateConversation, onSetActiveId, setMessages, onAfterSend]);

  return { input, setInput, isStreaming, sendMessage, textareaRef };
}
