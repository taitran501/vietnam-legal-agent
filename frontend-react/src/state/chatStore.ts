import { create } from 'zustand';
import type { CaseState, ChatMessage, ResponseSource, SourceDocument, WorkflowMetadata, WorkflowStep } from '@/types';

interface ChatState {
  // Active conversation
  activeSessionId: string | null;
  messages: ChatMessage[];
  
  // Streaming state
  isStreaming: boolean;
  streamingContent: string;
  statusMessage: string;
  workflowSteps: WorkflowStep[];
  activeCase: CaseState | null;
  composerDraft: { text: string; intent: string; interactionSource: string };
  
  // UI state
  isLoading: boolean;
  error: string | null;

  // Actions
  setActiveSession: (sessionId: string) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateLastAssistantMessage: (
    content: string,
    source?: ResponseSource,
    documents?: SourceDocument[],
    workflow?: WorkflowMetadata
  ) => void;
  setStreaming: (isStreaming: boolean) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (chunk: string) => void;
  setStatusMessage: (message: string) => void;
  addWorkflowStep: (step: WorkflowStep) => void;
  setWorkflowSteps: (steps: WorkflowStep[]) => void;
  setActiveCase: (caseState: CaseState | null) => void;
  setComposerDraft: (draft: Partial<ChatState['composerDraft']>) => void;
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
  workflowSteps: [],
  activeCase: null,
  composerDraft: { text: '', intent: 'auto', interactionSource: 'composer' },
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
  
  updateLastAssistantMessage: (content, source, documents, workflow) =>
    set((state) => {
      const messages = [...state.messages];
      const lastIdx = messages.length - 1;
      if (lastIdx >= 0 && messages[lastIdx].role === 'assistant') {
        messages[lastIdx] = {
          ...messages[lastIdx],
          content,
          source,
          documents,
          workflow,
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
    set((state) => ({
      workflowSteps: [...state.workflowSteps.filter((item) => item.step !== step.step), step].sort((a, b) => a.step - b.step),
    })),
  setWorkflowSteps: (workflowSteps) => set({ workflowSteps }),
  setActiveCase: (activeCase) => set({ activeCase }),
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
      activeCase: null,
      composerDraft: { text: '', intent: 'auto', interactionSource: 'composer' },
      error: null,
    }),

  removeLastMessage: () =>
    set((state) => ({
      messages: state.messages.slice(0, -1),
    })),
}));
