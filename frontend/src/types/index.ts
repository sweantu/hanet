export type ResumeAction = "approve" | "deny" | "replan";

export interface InterruptData {
  summary: string;
}

export interface Message {
  id?: string;
  role: "user" | "assistant" | "interrupt";
  content: string;
  interrupt?: InterruptData;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
}

export interface SearchResult {
  id: string;
  content: string;
  conversation_title: string;
  conversation_created_at: string;
  metadata: { conversation_id: string; message_id: string; role: string };
  rrf_score: number;
}
