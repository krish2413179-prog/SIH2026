'use client';

/**
 * WebSocket notification context.
 *
 * Creates a persistent WebSocket connection to /ws/notifications/{user_id}
 * and exposes real-time alerts and trace-progress updates via React context.
 *
 * Requirements: 13.1 (real-time progress), 18.6 (risk alert broadcast)
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';

import { getCurrentUser } from './auth';

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

export interface Alert {
  id: string;
  type: 'risk_alert' | 'notification' | string;
  message: string;
  severity?: 'low' | 'medium' | 'high' | 'critical';
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface TraceProgress {
  trace_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress_pct: number;
  message?: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface NotificationContextValue {
  /** All alerts received during this session (newest first). */
  alerts: Alert[];
  /** Map of trace_id → latest progress snapshot. */
  traceProgress: Record<string, TraceProgress>;
  /** Whether the WebSocket is currently connected. */
  connected: boolean;
  /** Manually clear all alerts (e.g., after user dismisses them). */
  clearAlerts: () => void;
}

const NotificationContext = createContext<NotificationContextValue>({
  alerts: [],
  traceProgress: {},
  connected: false,
  clearAlerts: () => {},
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL.replace(/^http/, 'ws').replace('/api/v1', '')
    : 'ws://localhost:8000');

const RECONNECT_DELAY_MS = 3_000;
const MAX_ALERTS = 100;

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [traceProgress, setTraceProgress] = useState<Record<string, TraceProgress>>({});
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const clearAlerts = useCallback(() => setAlerts([]), []);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const user = getCurrentUser();
    if (!user) return; // Not authenticated — don't open a connection

    const url = `${WS_BASE_URL}/ws/notifications/${user.user_id}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnected(true);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (!mountedRef.current) return;

        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(event.data as string) as Record<string, unknown>;
        } catch {
          return; // Ignore non-JSON frames
        }

        const msgType = payload['type'] as string | undefined;

        // Keepalive ping — no state update needed
        if (msgType === 'ping') return;

        // Trace progress update
        if (msgType === 'trace_progress') {
          const tp = payload as unknown as TraceProgress;
          if (tp.trace_id) {
            setTraceProgress((prev) => ({
              ...prev,
              [tp.trace_id]: { ...tp, updated_at: tp.updated_at ?? new Date().toISOString() },
            }));
          }
          return;
        }

        // Risk alerts and generic notifications → alerts list
        const alert: Alert = {
          id: (payload['id'] as string) ?? crypto.randomUUID(),
          type: msgType ?? 'notification',
          message: (payload['message'] as string) ?? JSON.stringify(payload),
          severity: payload['severity'] as Alert['severity'],
          timestamp: (payload['timestamp'] as string) ?? new Date().toISOString(),
          data: payload['data'] as Record<string, unknown> | undefined,
        };

        setAlerts((prev) => [alert, ...prev].slice(0, MAX_ALERTS));
      };

      ws.onerror = () => {
        // onerror always fires before onclose — let onclose handle reconnect
        setConnected(false);
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        wsRef.current = null;

        // Schedule reconnect
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) connect();
        }, RECONNECT_DELAY_MS);
      };
    } catch {
      // WebSocket constructor can throw in SSR or unsupported environments
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return (
    <NotificationContext.Provider
      value={{ alerts, traceProgress, connected, clearAlerts }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useNotifications(): NotificationContextValue {
  return useContext(NotificationContext);
}
