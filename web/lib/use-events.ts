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
    if (process.env.NEXT_PUBLIC_ENABLE_EVENT_STREAM !== "true") {
      return;
    }
    const url = `${API_BASE}/events/stream`;
    const es = new EventSource(url);
    let stopped = false;
    // Only show toasts for events after connection time
    const connectedAt = Date.now() / 1000;
    eventSourceRef.current = es;

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
      // The event stream is a nice-to-have; fail closed instead of reconnecting forever.
      if (!stopped) {
        es.close();
      }
    };

    return () => {
      stopped = true;
      es?.close();
      eventSourceRef.current = null;
    };
  }, []);
}
