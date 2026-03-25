import Link from "next/link";
import { ReactNode } from "react";

import { FilingListItem, NewsItem, formatDate } from "@/lib/api";

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {actions}
    </div>
  );
}

export function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ScorePill({ label, value }: { label: string; value: number }) {
  return (
    <span className="score-pill">
      {label}: <strong>{value.toFixed(1)}</strong>
    </span>
  );
}

export function FilingCard({ filing }: { filing: FilingListItem }) {
  return (
    <article className="panel">
      <div className="panel-topline">
        <span className="tag">{filing.form_type}</span>
        <span>{formatDate(filing.filed_at)}</span>
      </div>
      <h3>{filing.title ?? `${filing.company_name} ${filing.form_type}`}</h3>
      <p className="muted">
        <Link href={`/companies/${filing.company_id}`} className="inline-link">
          {filing.company_name}
        </Link>
        {filing.ticker ? ` (${filing.ticker})` : ""}
      </p>
      <p>{filing.summary || "Summary pending."}</p>
      <div className="score-row">
        <ScorePill label="Composite" value={filing.composite_score} />
        <ScorePill label="Impact" value={filing.impact_score} />
        <ScorePill label="Mkt Cap" value={filing.market_cap_score} />
      </div>
      <div className="link-row">
        <Link href={`/filings/${filing.id}`}>Open filing</Link>
        <a href={filing.pdf_download_url ?? filing.original_document_url} target="_blank" rel="noreferrer">
          PDF
        </a>
        <a href={filing.original_document_url} target="_blank" rel="noreferrer">
          SEC source
        </a>
      </div>
    </article>
  );
}

export function NewsCard({ item }: { item: NewsItem }) {
  return (
    <article className="panel">
      <div className="panel-topline">
        <span className="tag">{item.source_name}</span>
        <span>{formatDate(item.published_at)}</span>
      </div>
      <h3>{item.title}</h3>
      <p>{item.summary || item.excerpt || "Summary pending."}</p>
      <div className="meta-list">
        {item.topic_tags.map((tag) => (
          <span key={tag} className="mini-tag">
            {tag}
          </span>
        ))}
      </div>
      <div className="score-row">
        <ScorePill label="Composite" value={item.composite_score} />
        <ScorePill label="Importance" value={item.importance_score} />
      </div>
      <div className="link-row">
        <a href={item.canonical_url} target="_blank" rel="noreferrer">
          Open article
        </a>
      </div>
    </article>
  );
}

export function EmptyPanel({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-panel">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}
