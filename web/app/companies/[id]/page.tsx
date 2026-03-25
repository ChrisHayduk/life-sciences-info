import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyPanel, FilingCard, NewsCard, SectionHeader, StatCard } from "@/components/cards";
import { api, formatCurrency, formatDate, formatMarketCap } from "@/lib/api";

export default async function CompanyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const company = await api.company(id).catch(() => null);

  if (!company) {
    notFound();
  }

  return (
    <>
      <section className="detail-hero">
        <span className="eyebrow">Company</span>
        <h1>{company.name}</h1>
        <p>
          {company.ticker ? `${company.ticker} · ` : ""}
          {company.exchange ?? "Exchange unavailable"} · {company.sic ?? "SIC unavailable"}{" "}
          {company.sic_description ? `(${company.sic_description})` : ""}
        </p>
        <div className="metric-strip">
          <StatCard label="Market Cap" value={formatMarketCap(company)} />
          <StatCard label="Filings" value={company.filings_count} />
          <StatCard label="News Items" value={company.news_count} />
        </div>
        <div className="detail-meta">
          <span>{company.universe_reason_label}</span>
          <span>
            {company.market_cap_updated_at
              ? `Market cap updated ${formatDate(company.market_cap_updated_at)}`
              : "Market cap refresh pending"}
          </span>
        </div>
      </section>

      <section className="detail-section">
        <SectionHeader
          eyebrow="Coverage"
          title="Company profile"
          description="The company page combines ranked SEC filings with related industry news coverage."
        />
        <div className="grid-3">
          <div className="panel">
            <h3>Ticker</h3>
            <p>{company.ticker ?? "Unavailable"}</p>
          </div>
          <div className="panel">
            <h3>Market Cap</h3>
            <p>{company.market_cap ? formatCurrency(company.market_cap) : "Pending refresh"}</p>
          </div>
          <div className="panel">
            <h3>SEC CIK</h3>
            <p>{company.cik}</p>
          </div>
        </div>
      </section>

      <section className="grid-2">
        <div>
          <SectionHeader
            eyebrow="Filings"
            title="Recent company disclosures"
            description="Ranked periodic filings for this issuer, with AI summaries and direct document access."
          />
          <div className="grid-1">
            {company.recent_filings.length ? (
              company.recent_filings.map((filing) => <FilingCard key={filing.id} filing={filing} />)
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
          <div className="grid-1">
            {company.recent_news.length ? (
              company.recent_news.map((item) => <NewsCard key={item.id} item={item} />)
            ) : (
              <EmptyPanel title="No related news yet" body="Run the news ingestion job to load relevant articles and press coverage." />
            )}
          </div>
        </div>
      </section>

      <section className="detail-section">
        <div className="link-row">
          <Link href="/companies">Back to companies</Link>
          {company.recent_filings.length ? (
            <Link href={`/filings/${company.recent_filings[0].id}`}>Open latest filing</Link>
          ) : null}
        </div>
      </section>
    </>
  );
}
