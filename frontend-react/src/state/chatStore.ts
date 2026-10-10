import { create } from 'zustand';
import type {
  ActiveTurn,
  ChatMessage,
  ResponseSource,
  SourceDocument,
  StreamError,
  WorkflowMetadata,
  WorkflowStep,
} from '@/types';

interface ChatState {
  // Active conversation
  activeSessionId: string | null;
  messages: ChatMessage[];
  
  // Streaming state
  isStreaming: boolean;
  streamingContent: string;
  statusMessage: string;
  workflowSteps: WorkflowStep[];
  activeTurn: ActiveTurn | null;
  composerDraft: { text: string; intent: string; interactionSource: string };
  
  // UI state
  isLoading: boolean;
  error: StreamError | null;
  sessionLoadStatus: 'idle' | 'loading' | 'loaded' | 'error';
  sessionLoadError: string | null;

  // Actions
  setActiveSession: (sessionId: string | null) => void;
  beginSessionLoad: (sessionId: string) => void;
  failSessionLoad: (message: string) => void;
  finishSessionLoad: (sessionId: string, messages: ChatMessage[]) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (messageId: string, updates: Partial<ChatMessage>) => void;
  removeMessage: (messageId: string) => void;
  updateLastAssistantMessage: (
    content: string,
    source?: ResponseSource,
    documents?: SourceDocument[],
    workflow?: WorkflowMetadata,
    serverMessageId?: number
  ) => void;
  setStreaming: (isStreaming: boolean) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (chunk: string) => void;
  setStatusMessage: (message: string) => void;
  addWorkflowStep: (step: WorkflowStep) => void;
  setWorkflowSteps: (steps: WorkflowStep[]) => void;
  setActiveTurn: (turn: ActiveTurn | null) => void;
  setComposerDraft: (draft: Partial<ChatState['composerDraft']>) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (error: StreamError | null) => void;
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
  workflowSteps: [],
  activeTurn: null,
  composerDraft: { text: '', intent: 'auto', interactionSource: 'composer' },
  isLoading: false,
  error: null,
  sessionLoadStatus: 'idle',
  sessionLoadError: null,

  // Actions
  setActiveSession: (sessionId) =>
    set({ activeSessionId: sessionId }),
  beginSessionLoad: (sessionId) =>
    set({
      activeSessionId: sessionId,
      messages: [],
      workflowSteps: [],
      streamingContent: '',
      statusMessage: '',
      error: null,
      sessionLoadStatus: 'loading',
      sessionLoadError: null,
    }),
  failSessionLoad: (message) => set({ sessionLoadStatus: 'error', sessionLoadError: message }),
  finishSessionLoad: (sessionId, messages) =>
    set((state) => state.activeSessionId === sessionId
      ? { messages, sessionLoadStatus: 'loaded', sessionLoadError: null }
      : {}),
  
  setMessages: (messages) =>
    set({ messages }),
  
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),
  updateMessage: (messageId, updates) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId ? { ...message, ...updates } : message
      ),
    })),
  removeMessage: (messageId) =>
    set((state) => ({ messages: state.messages.filter((message) => message.id !== messageId) })),
  
  updateLastAssistantMessage: (content, source, documents, workflow, serverMessageId) =>
    set((state) => {
      const messages = [...state.messages];
      const lastIdx = messages.length - 1;
      if (lastIdx >= 0 && messages[lastIdx].role === 'assistant') {
        const previous = messages[lastIdx];
        messages[lastIdx] = {
          ...previous,
          content,
          source,
          documents,
          workflow,
          serverMessageId: serverMessageId ?? previous.serverMessageId,
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
  addWorkflowStep: (step) =>
    set((state) => {
      const existingIdx = state.workflowSteps.findIndex(
        (item) => (step.step > 0 && item.step === step.step) || (item.action === step.action && item.status === 'running')
      );
      if (existingIdx >= 0) {
        const updated = [...state.workflowSteps];
        updated[existingIdx] = { ...updated[existingIdx], ...step };
        return { workflowSteps: updated.sort((a, b) => a.step - b.step) };
      }
      return {
        workflowSteps: [...state.workflowSteps, step].sort((a, b) => a.step - b.step),
      };
    }),
  setWorkflowSteps: (workflowSteps) => set({ workflowSteps }),
  setActiveTurn: (activeTurn) => set({ activeTurn }),
  setComposerDraft: (draft) => set((state) => ({ composerDraft: { ...state.composerDraft, ...draft } })),
  
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
      workflowSteps: [],
      activeTurn: null,
      composerDraft: { text: '', intent: 'auto', interactionSource: 'composer' },
      error: null,
      sessionLoadStatus: 'idle',
      sessionLoadError: null,
    }),

  removeLastMessage: () =>
    set((state) => ({
      messages: state.messages.slice(0, -1),
    })),
}));
