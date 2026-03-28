import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, FileText, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  EmptyPanel,
  FilingCard,
  NewsCard,
  SectionHeader,
  StatCard,
  TimelineEventCard,
  TrialCard,
} from "@/components/cards";
import { AddToWatchlistButton } from "@/components/watchlist-actions";
import { api, ClinicalTrial, FilingListItem, formatDate, formatMarketCap } from "@/lib/api";

const FILING_TYPE_LABELS: Record<string, string> = {
  "10-K": "10-K",
  "20-F": "20-F",
  "40-F": "40-F",
  "10-Q": "10-Q",
  "8-K": "8-K",
  "6-K": "6-K",
};

function groupFilingsByType(filings: FilingListItem[]) {
  const groups: Array<{ formType: string; filings: FilingListItem[] }> = [];
  for (const filing of filings) {
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.formType === filing.normalized_form_type) {
      lastGroup.filings.push(filing);
      continue;
    }
    groups.push({ formType: filing.normalized_form_type, filings: [filing] });
  }
  return groups;
}

export default async function CompanyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const company = await api.company(id).catch(() => null);
  if (!company) notFound();

  const filingGroups = groupFilingsByType(company.recent_filings);

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card via-card to-secondary/60 p-7 shadow-lg">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Company Briefing
            </span>
            <div className="flex items-center gap-3 mt-1">
              <h1 className="text-3xl">{company.name}</h1>
              {company.trend && company.trend.direction !== "insufficient_data" && (
                <Badge
                  variant={
                    company.trend.direction === "improving"
                      ? "default"
                      : company.trend.direction === "deteriorating"
                        ? "destructive"
                        : "secondary"
                  }
                  className="text-xs"
                >
                  {company.trend.direction === "improving" && <TrendingUp className="size-3 mr-1" />}
                  {company.trend.direction === "deteriorating" && <TrendingDown className="size-3 mr-1" />}
                  {company.trend.direction === "stable" && <Minus className="size-3 mr-1" />}
                  {company.trend.direction}
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground mt-2">
              {company.ticker ? `${company.ticker} · ` : ""}
              {company.exchange ?? "Exchange unavailable"} · {company.sic ?? "SIC unavailable"}{" "}
              {company.sic_description ? `(${company.sic_description})` : ""}
            </p>
            <p className="text-sm leading-relaxed mt-4 max-w-2xl">
              {company.business_summary}
            </p>
            <div className="flex flex-wrap gap-2 mt-4">
              <Badge variant="outline" className="text-xs font-normal">
                {company.universe_reason_label}
              </Badge>
              {company.market_cap_updated_at ? (
                <Badge variant="outline" className="text-xs font-normal">
                  Market cap updated {formatDate(company.market_cap_updated_at)}
                </Badge>
              ) : null}
            </div>
          </div>
          <AddToWatchlistButton companyIds={[company.id]} label="Add to watchlist" variant="default" />
        </div>

        <div className="grid gap-3 mt-6 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="Market Cap" value={formatMarketCap(company)} />
          <StatCard label="Filings" value={company.filings_count} />
          <StatCard label="News" value={company.news_count} />
          <StatCard
            label="Latest Filing"
            value={company.latest_filing ? company.latest_filing.form_type : "None"}
          />
          <StatCard
            label="Active Trials"
            value={Object.values(company.pipeline ?? {}).reduce((sum, trials) => sum + trials.length, 0)}
          />
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                At A Glance
              </span>
              <h2 className="text-lg mt-1">What changed since last quarter</h2>
            </div>
            {company.change_summary.length ? (
              <ul className="space-y-2 text-sm pl-4 list-disc marker:text-muted-foreground">
                {company.change_summary.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Recent filing deltas will appear here once this company has a summarized periodic filing.
              </p>
            )}
            {company.latest_filing ? (
              <div className="pt-2">
                <Link href={`/filings/${company.latest_filing.id}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
                  <FileText className="size-3.5" /> Open latest document
                </Link>
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                Catalysts
              </span>
              <h2 className="text-lg mt-1">Key programs and signals</h2>
            </div>
            {company.catalyst_summary.length ? (
              <div className="space-y-4">
                <ul className="space-y-2 text-sm pl-4 list-disc marker:text-muted-foreground">
                  {company.catalyst_summary.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                {company.catalysts.length ? (
                  <div className="space-y-3">
                    {company.catalysts.slice(0, 3).map((event) => (
                      <TimelineEventCard key={event.id} event={event} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Pipeline and catalyst summaries appear once trials and recent news are available.
              </p>
            )}
            {company.catalysts[0]?.external_url ? (
              <a
                href={company.catalysts[0].external_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80"
              >
                Latest catalyst source
              </a>
            ) : null}
          </CardContent>
        </Card>
      </section>

      {company.timeline.length ? (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Timeline"
            title="Merged company timeline"
            description="Filings, news, and trial updates are merged here so you can scan the company story chronologically."
          />
          <div className="grid gap-4 lg:grid-cols-2">
            {company.timeline.map((event) => (
              <TimelineEventCard key={event.id} event={event} />
            ))}
          </div>
        </section>
      ) : null}

      {company.pipeline && Object.keys(company.pipeline).length > 0 && (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Pipeline"
            title="Clinical trials"
            description="ClinicalTrials.gov updates stay in the company page because they are often the clearest forward-looking catalyst."
          />
          <div className="space-y-4">
            {Object.entries(company.pipeline).map(([phase, trials]) => (
              <div key={phase}>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="secondary" className="text-xs font-mono">{phase}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {trials.length} trial{trials.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {trials.map((trial: ClinicalTrial) => (
                    <TrialCard key={trial.id} trial={trial} showCompany={false} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="Filings"
            title="Grouped disclosures"
            description="Form types stay grouped so annual and quarterly filings are easy to scan historically."
          />
          <div className="space-y-4">
            {filingGroups.length ? (
              filingGroups.map((group) => (
                <div key={group.formType} className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm space-y-3">
                  <div className="flex items-center justify-between text-sm text-muted-foreground">
                    <Badge variant="secondary" className="font-mono text-xs">
                      {FILING_TYPE_LABELS[group.formType] ?? group.formType}
                    </Badge>
                    <span className="text-xs">
                      {group.filings.length} filing{group.filings.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="space-y-3">
                    {group.filings.map((filing) => (
                      <FilingCard key={filing.id} filing={filing} />
                    ))}
                  </div>
                </div>
              ))
            ) : (
              <EmptyPanel title="No filings yet" body="Run the company backfill job to load historical SEC documents." />
            )}
          </div>
        </div>
        <div>
          <SectionHeader
            eyebrow="News"
            title="Operating context"
            description="These are deduped and explicitly tagged to this company, with official sources preferred when available."
          />
          <div className="space-y-4">
            {company.recent_news.length ? (
              company.recent_news.map((item) => <NewsCard key={item.id} item={item} />)
            ) : (
              <EmptyPanel title="No related news yet" body="Run the news ingestion job to load relevant articles and press coverage." />
            )}
          </div>
        </div>
      </section>

      <div className="flex flex-wrap gap-4">
        <Link href="/companies" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
          <ArrowLeft className="size-3.5" /> Back to companies
        </Link>
        {company.latest_filing ? (
          <Link href={`/filings/${company.latest_filing.id}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
            <FileText className="size-3.5" /> Open latest filing
          </Link>
        ) : null}
      </div>
    </>
  );
}
