import { createContext, useContext, type ReactNode } from 'react';
import { useSSE } from '../hooks/useSSE';
import type { SSEEvent } from '../api/types';

type SSEContextValue = {
  subscribe: (channel: string, callback: (data: SSEEvent) => void) => void;
  unsubscribe: (channel: string, callback: (data: SSEEvent) => void) => void;
  connectionStatus: 'connecting' | 'open' | 'closed' | 'error';
};

const SSEContext = createContext<SSEContextValue | null>(null);

export function SSEProvider({ children }: { children: ReactNode }) {
  const { subscribe, unsubscribe, connectionStatus } = useSSE('/api/events/stream');

  return (
    <SSEContext.Provider value={{ subscribe, unsubscribe, connectionStatus }}>
      {children}
    </SSEContext.Provider>
  );
}

export function useSSEContext() {
  const ctx = useContext(SSEContext);
  if (!ctx) throw new Error('useSSEContext must be used within SSEProvider');
  return ctx;
}