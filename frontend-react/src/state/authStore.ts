import { create } from 'zustand';
import type { MeResponse } from '@/api/me';

interface AuthState {
  me: MeResponse | null;
  setMe: (me: MeResponse | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  me: null,
  setMe: (me) => set({ me }),
}));
