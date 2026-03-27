"use client";

import { useEventStream } from "@/lib/use-events";

export function EventProvider({ children }: { children: React.ReactNode }) {
  useEventStream();
  return <>{children}</>;
}
