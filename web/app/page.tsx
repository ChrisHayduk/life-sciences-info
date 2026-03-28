import Link from "next/link";
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
import { Markdown } from "@/components/markdown";
import { api } from "@/lib/api";

export default async function DashboardPage() {
  const data = await api.dashboard().catch(() => null);

  if (!data) {
    return (
      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Platform Status
        </span>
        <h2 className="text-xl mt-1">Backend unavailable</h2>
        <p className="text-sm text-muted-foreground mt-2">
          Start the API service to load filings, news, trial, and watchlist briefing data.
        </p>
      </section>
    );
  }

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card via-card to-secondary/60 p-7 shadow-lg">
        <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
          <div className="space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                Daily Briefing
              </span>
              <h2 className="text-3xl mt-1">Market awareness first, deep follow-up second</h2>
              <p className="text-sm text-muted-foreground mt-2 max-w-2xl leading-relaxed">
                This dashboard separates fresh developments from the most consequential ones, then hands off
                the deeper work to watchlists and company pages.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="text-xs font-normal">
                {data.queue_counts.filings_pending ?? 0} filing summaries queued
              </Badge>
              <Badge variant="outline" className="text-xs font-normal">
                {data.queue_counts.news_pending ?? 0} news summaries queued
              </Badge>
              <Badge variant="outline" className="text-xs font-normal">
                Filing AI budget: {data.ai_budget.filing.used}/{data.ai_budget.filing.limit}
              </Badge>
              <Badge variant="outline" className="text-xs font-normal">
                News AI budget: {data.ai_budget.news.used}/{data.ai_budget.news.limit}
              </Badge>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-2">
            <StatCard label="Companies" value={data.counts.companies ?? 0} />
            <StatCard label="Filings" value={data.counts.filings ?? 0} />
            <StatCard label="News" value={data.counts.news_items ?? 0} />
            <StatCard label="Trials" value={data.counts.clinical_trials ?? 0} />
            <StatCard label="Digests" value={data.counts.digests ?? 0} />
            <StatCard label="Override Slots" value={data.ai_budget.override.remaining} />
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="What Changed"
            title="Last 24 hours"
            description="Start here for freshness. This is the quickest path to what changed today."
            actions={
              <Link href="/filings?sort_mode=freshness&recent_days=30" className="text-sm font-semibold text-primary hover:text-primary/80">
                View filings
              </Link>
            }
          />
          <div className="space-y-4">
            {data.latest_filings.length || data.latest_news.length ? (
              <>
                {data.latest_filings.map((filing) => (
                  <FilingCard key={`latest-filing-${filing.id}`} filing={filing} />
                ))}
                {data.latest_news.map((item) => (
                  <NewsCard key={`latest-news-${item.id}`} item={item} />
                ))}
              </>
            ) : (
              <EmptyPanel
                title="No fresh items yet"
                body="Once new filings or news arrive, the last-24-hours briefing will appear here."
              />
            )}
          </div>
        </div>
        <div>
          <SectionHeader
            eyebrow="What Matters"
            title="Most important this week"
            description="These are ranked for materiality, recency, and company relevance rather than simple chronology."
            actions={
              <Link href="/news?sort_mode=importance&recent_days=14" className="text-sm font-semibold text-primary hover:text-primary/80">
                View news
              </Link>
            }
          />
          <div className="space-y-4">
            {data.important_filings.length ? (
              data.important_filings.map((filing) => (
                <FilingCard key={`important-filing-${filing.id}`} filing={filing} />
              ))
            ) : (
              <EmptyPanel title="No important filings yet" body="Important disclosures will appear here once the universe has recent SEC activity." />
            )}
            {data.important_news.length ? (
              data.important_news.map((item) => (
                <NewsCard key={`important-news-${item.id}`} item={item} />
              ))
            ) : (
              <EmptyPanel title="No important news yet" body="Important news coverage will appear here after feed ingestion." />
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Watchlists"
          title="Follow-up workspaces"
          description="Use watchlists to move from broad monitoring into a tighter, personally relevant workflow."
          actions={
            <Link href="/watchlists" className="text-sm font-semibold text-primary hover:text-primary/80">
              Open watchlists
            </Link>
          }
        />
        {data.watchlist_highlights.length ? (
          <div className="grid gap-5 lg:grid-cols-3">
            {data.watchlist_highlights.map((highlight) => (
              <Card key={highlight.watchlist_id} className="border-border/50">
                <CardContent className="p-5 space-y-3">
                  <div>
                    <Link href={`/watchlists/${highlight.watchlist_id}`} className="text-base font-semibold text-primary hover:text-primary/80">
                      {highlight.watchlist_name}
                    </Link>
                    {highlight.watchlist_description ? (
                      <p className="text-sm text-muted-foreground mt-1">{highlight.watchlist_description}</p>
                    ) : null}
                  </div>
                  <div className="space-y-3">
                    {highlight.highlights.map((event) => (
                      <TimelineEventCard key={event.id} event={event} />
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyPanel
            title="No watchlist highlights yet"
            body="Create starter watchlists to get a tailored follow-up queue on top of the market-wide dashboard."
          />
        )}
      </section>

      {(data.recent_trials ?? []).length > 0 && (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Pipeline"
            title="Recent trial updates"
            description="ClinicalTrials.gov changes are included here as context for catalysts and company narratives."
          />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {data.recent_trials.map((trial) => (
              <TrialCard key={trial.id} trial={trial} />
            ))}
          </div>
        </section>
      )}

      {(data.upcoming_regulatory_events ?? []).length > 0 && (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Regulatory Calendar"
            title="Upcoming FDA catalysts"
            description="Official FDA advisory-calendar events are tracked separately so upcoming committee dates do not get buried inside the news feed."
          />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {data.upcoming_regulatory_events.map((event) => (
              <TimelineEventCard key={event.id} event={event} />
            ))}
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Weekly Digest"
          title={data.latest_digest?.title ?? "Weekly digest pending"}
          description="The digest stays weekly to control AI spend and synthesize only the highest-signal developments."
        />
        {data.latest_digest?.narrative_summary ? (
          <Markdown>{data.latest_digest.narrative_summary}</Markdown>
        ) : (
          <p className="text-sm leading-relaxed">
            The first digest will appear after filings or news are ingested and summarized.
          </p>
        )}
      </section>
    </>
  );
}
