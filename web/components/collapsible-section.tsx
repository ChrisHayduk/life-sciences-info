"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

export function CollapsibleSection({
  title,
  text,
  previewLength = 800,
}: {
  title: string;
  text: string;
  previewLength?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = text.length > previewLength;
  const displayText = expanded || !needsTruncation ? text : text.slice(0, previewLength);

  return (
    <div>
      <h3 className="text-sm font-semibold capitalize">{title}</h3>
      <p className="text-sm text-muted-foreground mt-2 leading-relaxed whitespace-pre-wrap">
        {displayText}
        {!expanded && needsTruncation && "..."}
      </p>
      {needsTruncation && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="inline-flex items-center gap-1 mt-2 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
        >
          {expanded ? (
            <>
              <ChevronDown className="size-3" /> Show less
            </>
          ) : (
            <>
              <ChevronRight className="size-3" /> Expand full section ({Math.round(text.length / 1000)}k chars)
            </>
          )}
        </button>
      )}
    </div>
  );
}
