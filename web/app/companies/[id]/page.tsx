import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyPanel, FilingCard, NewsCard, SectionHeader, StatCard } from "@/components/cards";
import { api, FilingListItem, formatCurrency, formatDate, formatMarketCap } from "@/lib/api";

const FILING_TYPE_LABELS: Record<string, string> = {
  "10-K": "10-K",
  "20-F": "20-F",
  "40-F": "40-F",
  "10-Q": "10-Q",
  "6-K": "6-K"
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
    if (!latest) {
      return filing;
    }
    const latestTime = new Date(latest.filed_at).getTime();
    const filingTime = new Date(filing.filed_at).getTime();
    if (filingTime !== latestTime) {
      return filingTime > latestTime ? filing : latest;
    }
    return filing.composite_score > latest.composite_score ? filing : latest;
  }, null);
}

export default async function CompanyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const company = await api.company(id).catch(() => null);

  if (!company) {
    notFound();
  }

  const filingGroups = groupFilingsByType(company.recent_filings);
  const latestFiling = findLatestFiling(company.recent_filings);

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
            description="Periodic filings grouped by form type priority, with the newest filings shown first inside each type."
          />
          <div className="grid-1">
            {filingGroups.length ? (
              filingGroups.map((group) => (
                <div key={group.formType} className="detail-section">
                  <div className="panel-topline">
                    <span className="tag">{FILING_TYPE_LABELS[group.formType] ?? group.formType}</span>
                    <span>
                      {group.filings.length} filing{group.filings.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="grid-1">
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
          {latestFiling ? (
            <Link href={`/filings/${latestFiling.id}`}>Open most recent filing</Link>
          ) : null}
        </div>
      </section>
    </>
  );
}
