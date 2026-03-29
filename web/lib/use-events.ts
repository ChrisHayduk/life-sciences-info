"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type SSEEvent = {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
};

const EVENT_LABELS: Record<string, string> = {
  new_filing: "New filing ingested",
  new_news: "New news article",
  digest_ready: "Weekly digest ready",
  summary_complete: "Summary completed",
  trial_update: "Clinical trial update",
};

export function useEventStream() {
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ENABLE_EVENT_STREAM === "false") {
      return;
    }
    const url = `${API_BASE}/events/stream`;
    let es: EventSource;
    let reconnectTimeout: ReturnType<typeof setTimeout>;
    let reconnectAttempts = 0;
    let stopped = false;
    // Only show toasts for events after connection time
    const connectedAt = Date.now() / 1000;

    function connect() {
      if (stopped) {
        return;
      }
      es = new EventSource(url);
      eventSourceRef.current = es;

      es.onopen = () => {
        reconnectAttempts = 0;
      };

      es.onmessage = (event) => {
        try {
          const parsed: SSEEvent = JSON.parse(event.data);
          // Only show toasts for new events (after connection)
          if (parsed.timestamp > connectedAt) {
            const label = EVENT_LABELS[parsed.type] ?? parsed.type;
            const description = parsed.data?.message ?? parsed.data?.title ?? "";
            toast(label, { description: String(description) });
          }
        } catch {
          // Ignore malformed events
        }
      };

      es.onerror = () => {
        es.close();
        reconnectAttempts += 1;
        if (reconnectAttempts >= 3) {
          stopped = true;
          return;
        }
        reconnectTimeout = setTimeout(connect, 5000 * reconnectAttempts);
      };
    }

    connect();

    return () => {
      stopped = true;
      clearTimeout(reconnectTimeout);
      es?.close();
    };
  }, []);
}
