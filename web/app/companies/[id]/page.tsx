import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, FileText, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyPanel, FilingCard, NewsCard, SectionHeader, StatCard } from "@/components/cards";
import { api, FilingListItem, formatCurrency, formatDate, formatMarketCap } from "@/lib/api";

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

function findLatestFiling(filings: FilingListItem[]) {
  return filings.reduce<FilingListItem | null>((latest, filing) => {
    if (!latest) return filing;
    const latestTime = new Date(latest.filed_at).getTime();
    const filingTime = new Date(filing.filed_at).getTime();
    if (filingTime !== latestTime) return filingTime > latestTime ? filing : latest;
    return filing.composite_score > latest.composite_score ? filing : latest;
  }, null);
}

export default async function CompanyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const company = await api.company(id).catch(() => null);
  if (!company) notFound();

  const filingGroups = groupFilingsByType(company.recent_filings);
  const latestFiling = findLatestFiling(company.recent_filings);

  return (
    <>
      {/* Hero */}
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Company
        </span>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-3xl">{company.name}</h1>
          {company.trend && company.trend.direction !== "insufficient_data" && (
            <Badge
              variant={company.trend.direction === "improving" ? "default" : company.trend.direction === "deteriorating" ? "destructive" : "secondary"}
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
        <div className="flex flex-wrap gap-3 mt-4">
          <StatCard label="Market Cap" value={formatMarketCap(company)} />
          <StatCard label="Filings" value={company.filings_count} />
          <StatCard label="News Items" value={company.news_count} />
        </div>
        <div className="flex items-center justify-between mt-4 text-xs text-muted-foreground">
          <span>{company.universe_reason_label}</span>
          <span>
            {company.market_cap_updated_at
              ? `Market cap updated ${formatDate(company.market_cap_updated_at)}`
              : "Market cap refresh pending"}
          </span>
        </div>
      </section>

      {/* Profile cards */}
      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Coverage"
          title="Company profile"
          description="The company page combines ranked SEC filings with related industry news coverage."
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <Card className="border-border/50">
            <CardContent className="p-4">
              <h3 className="text-sm font-semibold">Ticker</h3>
              <p className="text-lg font-mono mt-1">{company.ticker ?? "Unavailable"}</p>
            </CardContent>
          </Card>
          <Card className="border-border/50">
            <CardContent className="p-4">
              <h3 className="text-sm font-semibold">Market Cap</h3>
              <p className="text-lg font-mono mt-1">{company.market_cap ? formatCurrency(company.market_cap) : "Pending refresh"}</p>
            </CardContent>
          </Card>
          <Card className="border-border/50">
            <CardContent className="p-4">
              <h3 className="text-sm font-semibold">SEC CIK</h3>
              <p className="text-lg font-mono mt-1">{company.cik}</p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Pipeline (Clinical Trials) */}
      {company.pipeline && Object.keys(company.pipeline).length > 0 && (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Pipeline"
            title="Clinical trials"
            description="Active and completed clinical trials from ClinicalTrials.gov, grouped by phase."
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
                  {trials.map((trial) => (
                    <Card key={trial.id} className="border-border/50">
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
                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                          {trial.enrollment && <span>{trial.enrollment} enrolled</span>}
                          {trial.primary_completion_date && <span>Est. completion: {trial.primary_completion_date}</span>}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Filings + News */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="Filings"
            title="Recent company disclosures"
            description="Periodic filings grouped by form type priority, with the newest filings shown first inside each type."
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
            title="Related operating context"
            description="Important news items mentioning this company from the tracked public sources."
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

      {/* Footer links */}
      <div className="flex flex-wrap gap-4">
        <Link href="/companies" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
          <ArrowLeft className="size-3.5" /> Back to companies
        </Link>
        {latestFiling ? (
          <Link href={`/filings/${latestFiling.id}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
            <FileText className="size-3.5" /> Open most recent filing
          </Link>
        ) : null}
      </div>
    </>
  );
}
