"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { summarizeFiling, summarizeNews } from "@/lib/api";

export function SummarizeButton({
  kind,
  itemId,
  summaryStatus,
  label,
}: {
  kind: "filing" | "news";
  itemId: number;
  summaryStatus: string;
  label?: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [loading, setLoading] = useState(false);

  if (summaryStatus === "complete") {
    return null;
  }

  async function handleClick() {
    setLoading(true);
    try {
      if (kind === "filing") {
        await summarizeFiling(itemId);
      } else {
        await summarizeNews(itemId);
      }
      toast.success("Summary queued");
      startTransition(() => {
        router.refresh();
      });
    } catch (error) {
      const message = error instanceof Error && error.message.includes("429")
        ? "Daily manual summary budget is exhausted."
        : "Failed to request a summary.";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      className="gap-1.5"
      onClick={handleClick}
      disabled={loading || isPending}
    >
      <Sparkles className="size-3.5" />
      {loading || isPending ? "Working…" : (label ?? (summaryStatus === "stale" ? "Refresh summary" : "Summarize now"))}
    </Button>
  );
}
