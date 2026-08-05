import { create } from 'zustand';
import type { ChatMessage } from '@/types';

interface ChatState {
  // Active conversation
  activeSessionId: string | null;
  messages: ChatMessage[];
  
  // Streaming state
  isStreaming: boolean;
  streamingContent: string;
  statusMessage: string;
  
  // UI state
  isLoading: boolean;
  error: string | null;

  // Actions
  setActiveSession: (sessionId: string) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateLastAssistantMessage: (content: string, source?: string, documents?: unknown[]) => void;
  setStreaming: (isStreaming: boolean) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (chunk: string) => void;
  setStatusMessage: (message: string) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (error: string | null) => void;
  clearChat: () => void;
  removeLastMessage: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  // Initial state
  activeSessionId: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  statusMessage: '',
  isLoading: false,
  error: null,

  // Actions
  setActiveSession: (sessionId) =>
    set({ activeSessionId: sessionId }),
  
  setMessages: (messages) =>
    set({ messages }),
  
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),
  
  updateLastAssistantMessage: (content, source, documents) =>
    set((state) => {
      const messages = [...state.messages];
      const lastIdx = messages.length - 1;
      if (lastIdx >= 0 && messages[lastIdx].role === 'assistant') {
        messages[lastIdx] = {
          ...messages[lastIdx],
          content,
          source: source as any,
          documents: documents as any,
        };
      }
      return { messages, streamingContent: '' };
    }),
  
  setStreaming: (isStreaming) =>
    set({ isStreaming, streamingContent: '' }),
  
  setStreamingContent: (content) =>
    set({ streamingContent: content }),
  
  appendStreamingContent: (chunk) =>
    set((state) => ({
      streamingContent: state.streamingContent + chunk,
    })),
  
  setStatusMessage: (message) =>
    set({ statusMessage: message }),
  
  setLoading: (isLoading) =>
    set({ isLoading }),
  
  setError: (error) =>
    set({ error }),
  
  clearChat: () =>
    set({
      activeSessionId: null,
      messages: [],
      isStreaming: false,
      streamingContent: '',
      statusMessage: '',
      error: null,
    }),

  removeLastMessage: () =>
    set((state) => ({
      messages: state.messages.slice(0, -1),
    })),
}));
