import { create } from 'zustand';
import type { SessionInfo } from '@/types';

interface SessionState {
  // Session list
  sessions: SessionInfo[];
  isLoadingSessions: boolean;
  hasLoadedSessions: boolean;
  
  // Actions
  setSessions: (sessions: SessionInfo[]) => void;
  addSession: (session: SessionInfo) => void;
  removeSession: (sessionId: string) => void;
  updateSession: (sessionId: string, updates: Partial<SessionInfo>) => void;
  setLoading: (isLoading: boolean) => void;
  setLoaded: (hasLoaded: boolean) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  // Initial state
  sessions: [],
  isLoadingSessions: false,
  hasLoadedSessions: false,

  // Actions
  setSessions: (sessions) =>
    set({ sessions }),
  
  addSession: (session) =>
    set((state) => ({
      sessions: [session, ...state.sessions],
    })),
  
  removeSession: (sessionId) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== sessionId),
    })),
  
  updateSession: (sessionId, updates) =>
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === sessionId ? { ...s, ...updates } : s
      ),
    })),
  
  setLoading: (isLoading) =>
    set({ isLoadingSessions: isLoading }),
  setLoaded: (hasLoadedSessions) =>
    set({ hasLoadedSessions }),
}));
