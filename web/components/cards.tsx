import Link from "next/link";
import { ReactNode } from "react";
import { ExternalLink, FileText, Globe } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { FilingListItem, NewsItem, formatDate } from "@/lib/api";

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row justify-between gap-3 sm:items-end mb-4">
      <div>
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          {eyebrow}
        </span>
        <h2 className="text-xl">{title}</h2>
        <p className="text-sm text-muted-foreground mt-1">{description}</p>
      </div>
      {actions}
    </div>
  );
}

export function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="border-border/50">
      <CardContent className="p-4">
        <span className="text-xs text-muted-foreground block mb-1">{label}</span>
        <strong className="text-2xl font-bold">{value}</strong>
      </CardContent>
    </Card>
  );
}

const SCORE_TOOLTIPS: Record<string, string> = {
  Composite:
    "Overall priority rank blending company scale, content impact, and recency. Higher = more important to review.",
  Impact:
    "How much new, material information this filing contains relative to its predecessor.",
  Importance:
    "AI-assessed materiality of the disclosure or article for life sciences investors.",
  "Mkt Cap":
    "Company size percentile within the tracked universe. Larger companies rank higher.",
};

function scoreColor(value: number): string {
  if (value >= 70) return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20";
  if (value >= 40) return "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20";
  return "bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20";
}

export function ScorePill({ label, value }: { label: string; value: number }) {
  const tooltip = SCORE_TOOLTIPS[label] ?? `${label} score (0–100)`;
  return (
    <TooltipProvider delay={200}>
      <Tooltip>
        <TooltipTrigger
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium cursor-default",
            scoreColor(value)
          )}
        >
          {label}: <strong>{value.toFixed(1)}</strong>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-60 text-xs">
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function FilingCard({ filing }: { filing: FilingListItem }) {
  return (
    <Card className="border-border/50">
      <CardHeader className="p-5 pb-3">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <Badge variant="secondary" className="font-mono text-xs">
            {filing.form_type}
          </Badge>
          <span className="text-xs">{formatDate(filing.filed_at)}</span>
        </div>
        <h3 className="text-base font-semibold mt-2 leading-snug">
          {filing.title ?? `${filing.company_name} ${filing.form_type}`}
        </h3>
        <p className="text-sm text-muted-foreground">
          <Link href={`/companies/${filing.company_id}`} className="text-primary underline underline-offset-2 decoration-1 hover:text-primary/80">
            {filing.company_name}
          </Link>
          {filing.ticker ? ` (${filing.ticker})` : ""}
        </p>
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-3">
        <p className="text-sm leading-relaxed">{filing.summary || "Summary pending."}</p>
        <div className="flex flex-wrap gap-1.5">
          <ScorePill label="Composite" value={filing.composite_score} />
          <ScorePill label="Impact" value={filing.impact_score} />
          <ScorePill label="Mkt Cap" value={filing.market_cap_score} />
        </div>
        <div className="flex flex-wrap gap-3 pt-1">
          <Link href={`/filings/${filing.id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80">
            <FileText className="size-3.5" /> Open filing
          </Link>
          <a
            href={filing.pdf_download_url ?? filing.original_document_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
          >
            <ExternalLink className="size-3.5" /> PDF
          </a>
          <a
            href={filing.original_document_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
          >
            <Globe className="size-3.5" /> SEC source
          </a>
        </div>
      </CardContent>
    </Card>
  );
}

export function NewsCard({ item }: { item: NewsItem }) {
  return (
    <Card className="border-border/50">
      <CardHeader className="p-5 pb-3">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <Badge variant="secondary" className="text-xs">
            {item.source_name}
          </Badge>
          <span className="text-xs">{formatDate(item.published_at)}</span>
        </div>
        <h3 className="text-base font-semibold mt-2 leading-snug">{item.title}</h3>
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-3">
        <p className="text-sm leading-relaxed">{item.summary || item.excerpt || "Summary pending."}</p>
        {item.topic_tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {item.topic_tags.map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5">
          <ScorePill label="Composite" value={item.composite_score} />
          <ScorePill label="Importance" value={item.importance_score} />
        </div>
        <div className="flex flex-wrap gap-3 pt-1">
          <a
            href={item.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
          >
            <ExternalLink className="size-3.5" /> Open article
          </a>
        </div>
      </CardContent>
    </Card>
  );
}

export function EmptyPanel({ title, body }: { title: string; body: string }) {
  return (
    <Card className="border-border/50 border-dashed">
      <CardContent className="p-8 text-center">
        <h3 className="text-lg font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground mt-2">{body}</p>
      </CardContent>
    </Card>
  );
}
