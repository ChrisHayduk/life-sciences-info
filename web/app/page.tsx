import { EmptyPanel, FilingCard, NewsCard, SectionHeader, StatCard } from "@/components/cards";
import { api } from "@/lib/api";

export default async function DashboardPage() {
  const data = await api.dashboard().catch(() => null);

  if (!data) {
    return (
      <div className="main-stack">
        <section className="hero">
          <span className="eyebrow">Platform Status</span>
          <h2>Backend unavailable</h2>
          <p>Start the API service to load filings, news, and digest data.</p>
        </section>
      </div>
    );
  }

  return (
    <>
      <section className="hero">
        <div className="hero-grid">
          <div>
            <span className="eyebrow">Command Center</span>
            <h2>Ranked intelligence for public life sciences issuers</h2>
            <p>
              Track periodic SEC filings, pull the original document or PDF, and blend them with weekly
              life sciences news in a single private dashboard.
            </p>
          </div>
          <div className="stat-grid">
            <StatCard label="Companies" value={data.counts.companies ?? 0} />
            <StatCard label="Filings" value={data.counts.filings ?? 0} />
            <StatCard label="News Items" value={data.counts.news_items ?? 0} />
            <StatCard label="Digests" value={data.counts.digests ?? 0} />
          </div>
        </div>
      </section>

      <section className="grid-2">
        <div>
          <SectionHeader
            eyebrow="Top Filings"
            title="Most important disclosures"
            description="Composite rank blends current company scale with filing surprise and materiality."
          />
          <div className="grid-1">
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
          <div className="grid-1">
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

      <section className="detail-section">
        <SectionHeader
          eyebrow="Latest Digest"
          title={data.latest_digest?.title ?? "Weekly digest pending"}
          description="Every Monday at 8:00 AM ET the platform captures the prior Monday through Sunday window."
        />
        <p>{data.latest_digest?.narrative_summary ?? "The first digest will appear after filings or news are ingested."}</p>
      </section>
    </>
  );
}

