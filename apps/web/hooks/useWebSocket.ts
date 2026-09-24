"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type WebSocketMessage = {
  type: string;
  task_id?: string;
  event_type?: string;
  data?: unknown;
  timestamp?: number;
  message?: string;
};

type UseWebSocketOptions = {
  taskId?: string;
  /** Custom WS path (overrides task/global default). Use with buildWsUrl semantics. */
  path?: string;
  enabled?: boolean;
  onMessage?: (message: WebSocketMessage) => void;
  onError?: (error: Event) => void;
  onClose?: (event: CloseEvent) => void;
  onOpen?: (event: Event) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
};

/** Derive ws(s) URL from NEXT_PUBLIC_API_BASE (Gateway), never hardcode :8090. */
export function buildWsUrl(path: string, apiKey?: string): string {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080";
  const u = new URL(apiBase);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  const basePath = u.pathname.replace(/\/$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  u.pathname = `${basePath}${cleanPath}`;
  u.search = "";
  if (apiKey) {
    u.searchParams.set("api_key", apiKey);
  }
  return u.toString();
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    taskId,
    path: customPath,
    enabled = true,
    onMessage,
    onError,
    onClose,
    onOpen,
    reconnectInterval = 3000,
    maxReconnectAttempts = 8,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);
  const onCloseRef = useRef(onClose);
  const onOpenRef = useRef(onOpen);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
    onCloseRef.current = onClose;
    onOpenRef.current = onOpen;
  }, [onMessage, onError, onClose, onOpen]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      try {
        wsRef.current.close(1000, "client disconnect");
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (!enabled) return;
    if (typeof window === "undefined") return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const apiKey = process.env.NEXT_PUBLIC_API_KEY || "";
    const path = customPath
      ? customPath
      : taskId
        ? `/v1/tasks/${taskId}/events/ws`
        : `/v1/events/ws`;
    const wsUrl = buildWsUrl(path, apiKey || undefined);

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = (event) => {
        setIsConnected(true);
        setConnectionError(null);
        reconnectAttemptsRef.current = 0;
        onOpenRef.current?.(event);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage;
          onMessageRef.current?.(message);
        } catch (error) {
          console.error("Failed to parse WebSocket message:", error);
        }
      };

      ws.onerror = (event) => {
        setConnectionError("WebSocket connection error");
        onErrorRef.current?.(event);
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        wsRef.current = null;
        onCloseRef.current?.(event);

        if (event.code !== 1000 && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current += 1;
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };
    } catch (error) {
      setConnectionError("Failed to create WebSocket connection");
      console.error("WebSocket connection error:", error);
    }
  }, [enabled, taskId, customPath, reconnectInterval, maxReconnectAttempts]);

  const sendMessage = useCallback((message: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      disconnect();
      return;
    }
    connect();
    return () => disconnect();
  }, [connect, disconnect, enabled]);

  return {
    isConnected,
    connectionError,
    sendMessage,
    disconnect,
    reconnect: connect,
  };
}

export function useTaskWebSocket(
  taskId: string | null,
  onTaskEvent?: (event: WebSocketMessage) => void
) {
  const [taskState, setTaskState] = useState<unknown>(null);
  const [taskEvents, setTaskEvents] = useState<WebSocketMessage[]>([]);

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      switch (message.type) {
        case "initial_state":
          setTaskState(message.data);
          break;
        case "initial_events":
          setTaskEvents(
            Array.isArray(message.data)
              ? (message.data as WebSocketMessage[])
              : []
          );
          break;
        case "task_event":
          setTaskEvents((prev) => [...prev, message]);
          onTaskEvent?.(message);
          break;
        default:
          onTaskEvent?.(message);
      }
    },
    [onTaskEvent]
  );

  const ws = useWebSocket({
    taskId: taskId || undefined,
    enabled: Boolean(taskId),
    onMessage: handleMessage,
  });

  useEffect(() => {
    setTaskState(null);
    setTaskEvents([]);
  }, [taskId]);

  return {
    ...ws,
    taskState,
    taskEvents,
  };
}

export function useGlobalWebSocket(
  onSystemEvent?: (event: WebSocketMessage) => void
) {
  const [systemState, setSystemState] = useState<unknown>(null);

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      switch (message.type) {
        case "initial_state":
          setSystemState(message.data);
          break;
        case "system_event":
          onSystemEvent?.(message);
          break;
        default:
          onSystemEvent?.(message);
      }
    },
    [onSystemEvent]
  );

  const ws = useWebSocket({ onMessage: handleMessage });
  return { ...ws, systemState };
}
