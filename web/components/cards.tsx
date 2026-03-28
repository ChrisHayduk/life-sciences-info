import Link from "next/link";
import { ReactNode } from "react";
import { Building2, ExternalLink, FileText, Globe, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { ClinicalTrial, FilingListItem, NewsItem, TimelineEvent, formatDate } from "@/lib/api";
import { AddToWatchlistButton } from "@/components/watchlist-actions";
import { SummarizeButton } from "@/components/summary-actions";

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

const FRESHNESS_LABELS: Record<string, string> = {
  last_24h: "24h",
  last_7d: "7d",
  last_30d: "30d",
  last_90d: "90d",
  stale: "Older",
};

const SOURCE_LABELS: Record<string, string> = {
  official_filing: "Official filing",
  official_company_pr: "Company PR",
  regulator: "Regulator",
  trade_press: "Trade press",
  trial_registry: "Trial registry",
};

const SUMMARY_TIER_LABELS: Record<string, string> = {
  no_ai: "Rule-based",
  short_ai: "Quick AI",
  full_ai: "Full AI",
};

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
        <div className="flex flex-wrap gap-1.5 mt-2">
          <Badge variant="outline" className="text-xs font-normal">
            {SOURCE_LABELS[filing.source_type] ?? filing.source_type}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {FRESHNESS_LABELS[filing.freshness_bucket] ?? filing.freshness_bucket}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {SUMMARY_TIER_LABELS[filing.summary_tier] ?? filing.summary_tier}
          </Badge>
          {filing.event_type ? (
            <Badge variant="outline" className="text-xs font-normal">
              {filing.event_type.replaceAll("-", " ")}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-3">
        <p className="text-sm leading-relaxed">{filing.summary || "Summary pending."}</p>
        {filing.priority_reason ? (
          <p className="text-xs text-muted-foreground">
            Why it is ranked here: {filing.priority_reason}.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-1.5">
          <ScorePill label="Composite" value={filing.composite_score} />
          <ScorePill label="Impact" value={filing.impact_score} />
          <ScorePill label="Mkt Cap" value={filing.market_cap_score} />
        </div>
        <div className="flex flex-wrap gap-3 pt-1 items-center">
          <Link href={`/filings/${filing.id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80">
            <FileText className="size-3.5" /> Open filing
          </Link>
          <SummarizeButton kind="filing" itemId={filing.id} summaryStatus={filing.summary_status} />
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
          <AddToWatchlistButton companyIds={[filing.company_id]} label="Track company" />
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
        {item.mentioned_companies.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {item.mentioned_companies.map((name, i) => {
              const companyId = item.company_tag_ids?.[i];
              return companyId ? (
                <Link key={`${companyId}-${name}`} href={`/companies/${companyId}`}>
                  <Badge variant="outline" className="text-xs font-normal hover:bg-accent transition-colors cursor-pointer">
                    <Building2 className="size-3 mr-1" />
                    {name}
                  </Badge>
                </Link>
              ) : (
                <Badge key={name} variant="outline" className="text-xs font-normal">
                  <Building2 className="size-3 mr-1" />
                  {name}
                </Badge>
              );
            })}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5 mt-2">
          <Badge variant="outline" className="text-xs font-normal">
            {SOURCE_LABELS[item.source_type] ?? item.source_type}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {FRESHNESS_LABELS[item.freshness_bucket] ?? item.freshness_bucket}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {SUMMARY_TIER_LABELS[item.summary_tier] ?? item.summary_tier}
          </Badge>
          {item.event_type ? (
            <Badge variant="outline" className="text-xs font-normal">
              {item.event_type.replaceAll("-", " ")}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-3">
        <p className="text-sm leading-relaxed">{item.summary || item.excerpt || "Summary pending."}</p>
        {item.priority_reason ? (
          <p className="text-xs text-muted-foreground">
            Why it is ranked here: {item.priority_reason}.
          </p>
        ) : null}
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
        <div className="flex flex-wrap gap-3 pt-1 items-center">
          <a
            href={item.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
          >
            <ExternalLink className="size-3.5" /> Open article
          </a>
          <SummarizeButton kind="news" itemId={item.id} summaryStatus={item.summary_status} />
          {item.company_tag_ids.length > 0 ? (
            <AddToWatchlistButton companyIds={item.company_tag_ids} label="Track companies" />
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function TrialCard({ trial, showCompany = true }: { trial: ClinicalTrial; showCompany?: boolean }) {
  return (
    <Card className="border-border/50">
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between">
          <a
            href={`https://clinicaltrials.gov/study/${trial.nct_id}`}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-mono text-primary underline underline-offset-2 decoration-1 hover:text-primary/80"
          >
            {trial.nct_id}
          </a>
          <Badge
            variant={
              trial.status === "Recruiting" || trial.status === "Active, not recruiting"
                ? "default"
                : trial.status === "Completed"
                  ? "secondary"
                  : "outline"
            }
            className="text-xs"
          >
            {trial.status}
          </Badge>
        </div>
        <p className="text-sm font-medium leading-snug">{trial.title}</p>
        {trial.conditions.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {trial.conditions.slice(0, 3).map((c) => (
              <Badge key={c} variant="outline" className="text-xs font-normal">
                {c}
              </Badge>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
          {trial.phase && (
            <Badge variant="secondary" className="text-xs font-mono">{trial.phase}</Badge>
          )}
          {showCompany && trial.company_name && trial.company_id && (
            <Link href={`/companies/${trial.company_id}`} className="text-primary underline underline-offset-2 decoration-1 hover:text-primary/80">
              {trial.company_name}{trial.ticker ? ` (${trial.ticker})` : ""}
            </Link>
          )}
          {trial.enrollment && <span>{trial.enrollment} enrolled</span>}
          {trial.primary_completion_date && <span>Est. completion: {trial.primary_completion_date}</span>}
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

export function TimelineEventCard({ event }: { event: TimelineEvent }) {
  return (
    <Card className="border-border/50">
      <CardContent className="p-4 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap gap-1.5 mb-2">
              <Badge variant="secondary" className="text-xs">
                {event.item_type}
              </Badge>
              <Badge variant="outline" className="text-xs font-normal">
                {SOURCE_LABELS[event.source_type] ?? event.source_type}
              </Badge>
              <Badge variant="outline" className="text-xs font-normal">
                {FRESHNESS_LABELS[event.freshness_bucket] ?? event.freshness_bucket}
              </Badge>
            </div>
            <h3 className="text-sm font-semibold leading-snug">{event.title}</h3>
            <p className="text-xs text-muted-foreground mt-1">{formatDate(event.occurred_at)}</p>
          </div>
          {event.summary_tier !== "no_ai" ? (
            <Sparkles className="size-4 text-muted-foreground" />
          ) : null}
        </div>
        <p className="text-sm leading-relaxed">{event.summary || event.priority_reason}</p>
        {event.priority_reason ? (
          <p className="text-xs text-muted-foreground">Why now: {event.priority_reason}.</p>
        ) : null}
        <div className="flex flex-wrap gap-3 pt-1 items-center">
          {event.href ? (
            <Link href={event.href} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80">
              <FileText className="size-3.5" /> Open in app
            </Link>
          ) : null}
          {event.external_url ? (
            <a
              href={event.external_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
            >
              <ExternalLink className="size-3.5" /> Source
            </a>
          ) : null}
          {event.company_ids.length > 0 ? (
            <AddToWatchlistButton companyIds={event.company_ids} label="Track" />
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
