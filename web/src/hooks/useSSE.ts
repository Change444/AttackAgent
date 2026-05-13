import { useEffect, useRef, useCallback, useState } from 'react';
import type { SSEEvent, SSEChannel } from '../api/types';

const SSE_CHANNELS: SSEChannel[] = [
  'project_updated', 'solver_updated', 'idea_updated', 'memory_added',
  'observer_reported', 'review_created', 'review_decided',
  'candidate_flag_found', 'tool_event', 'hint_added',
  'knowledge_published', 'knowledge_merged',
];

type Subscriber = (data: SSEEvent) => void;

export function useSSE(url: string) {
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'open' | 'closed' | 'error'>('connecting');
  const subscribersRef = useRef<Map<string, Set<Subscriber>>>(new Map());
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnectionStatus('open');
    es.onerror = () => setConnectionStatus('error');

    for (const channel of SSE_CHANNELS) {
      es.addEventListener(channel, (e: MessageEvent) => {
        try {
          const data: SSEEvent = JSON.parse(e.data as string);
          const subs = subscribersRef.current.get(channel);
          if (subs) subs.forEach((cb) => cb(data));
        } catch { /* ignore parse errors */ }
      });
    }

    // Also listen for unnamed messages (server might send without event field)
    es.onmessage = (e: MessageEvent) => {
      try {
        const data: SSEEvent = JSON.parse(e.data as string);
        const eventType = (data.event_type as SSEChannel) || 'unknown';
        const subs = subscribersRef.current.get(eventType);
        if (subs) subs.forEach((cb) => cb(data));
      } catch { /* ignore */ }
    };

    return () => {
      es.close();
      setConnectionStatus('closed');
    };
  }, [url]);

  const subscribe = useCallback((channel: string, callback: Subscriber) => {
    if (!subscribersRef.current.has(channel)) {
      subscribersRef.current.set(channel, new Set());
    }
    subscribersRef.current.get(channel)!.add(callback);
  }, []);

  const unsubscribe = useCallback((channel: string, callback: Subscriber) => {
    const subs = subscribersRef.current.get(channel);
    if (subs) {
      subs.delete(callback);
      if (subs.size === 0) subscribersRef.current.delete(channel);
    }
  }, []);

  return { subscribe, unsubscribe, connectionStatus };
}