import { EmptyPanel, FilingCard, NewsCard, SectionHeader, StatCard } from "@/components/cards";
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
          Start the API service to load filings, news, and digest data.
        </p>
      </section>
    );
  }

  return (
    <>
      {/* Hero */}
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr] lg:items-end">
          <div>
            <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Command Center
            </span>
            <h2 className="text-2xl mt-1">Ranked intelligence for public life sciences issuers</h2>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
              Track periodic SEC filings, pull the original document or PDF, and blend them with weekly
              life sciences news in a single private dashboard.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Companies" value={data.counts.companies ?? 0} />
            <StatCard label="Filings" value={data.counts.filings ?? 0} />
            <StatCard label="News Items" value={data.counts.news_items ?? 0} />
            <StatCard label="Digests" value={data.counts.digests ?? 0} />
          </div>
        </div>
      </section>

      {/* Top Filings + News */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="Top Filings"
            title="Most important disclosures"
            description="Composite rank blends current company scale with filing surprise and materiality."
          />
          <div className="space-y-4">
            {data.top_filings.length ? (
              data.top_filings.map((filing) => <FilingCard key={filing.id} filing={filing} />)
            ) : (
              <EmptyPanel
                title="No filings yet"
                body="Run the universe sync and company backfill admin actions to start loading SEC documents."
              />
            )}
          </div>
        </div>
        <div>
          <SectionHeader
            eyebrow="Top News"
            title="Weekly operating context"
            description="News rankings combine source quality, recency, company relevance, and AI importance."
          />
          <div className="space-y-4">
            {data.top_news.length ? (
              data.top_news.map((item) => <NewsCard key={item.id} item={item} />)
            ) : (
              <EmptyPanel
                title="No news yet"
                body="Run the news ingestion job to pull Fierce Pharma, Fierce Biotech, and FDA headlines."
              />
            )}
          </div>
        </div>
      </section>

      {/* Latest Digest */}
      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Latest Digest"
          title={data.latest_digest?.title ?? "Weekly digest pending"}
          description="Every Monday at 8:00 AM ET the platform captures the prior Monday through Sunday window."
        />
        {data.latest_digest?.narrative_summary ? (
          <Markdown>{data.latest_digest.narrative_summary}</Markdown>
        ) : (
          <p className="text-sm leading-relaxed">
            The first digest will appear after filings or news are ingested.
          </p>
        )}
      </section>
    </>
  );
}
