import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyPanel, ScorePill } from "@/components/cards";
import { api, formatDate } from "@/lib/api";

export default async function FilingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const filing = await api.filing(id).catch(() => null);

  if (!filing) {
    notFound();
  }

  return (
    <>
      <section className="detail-hero">
        <span className="eyebrow">{filing.form_type}</span>
        <h1>{filing.title ?? `${filing.company_name} ${filing.form_type}`}</h1>
        <p>
          <Link href={`/companies/${filing.company_id}`} className="inline-link">
            {filing.company_name}
          </Link>
          {filing.ticker ? ` (${filing.ticker})` : ""} filed this report on {formatDate(filing.filed_at)}.
        </p>
        <div className="metric-strip">
          <ScorePill label="Composite" value={filing.composite_score} />
          <ScorePill label="Impact" value={filing.impact_score} />
          <ScorePill label="Importance" value={filing.importance_score} />
          <ScorePill label="Mkt Cap" value={filing.market_cap_score} />
        </div>
        <div className="link-row">
          {filing.pdf_download_url ? (
            <a href={filing.pdf_download_url} target="_blank" rel="noreferrer">
              Download PDF
            </a>
          ) : null}
          <a href={filing.original_document_url} target="_blank" rel="noreferrer">
            Original SEC document
          </a>
          {filing.prior_comparable_filing_id ? (
            <Link href={`/filings/${filing.prior_comparable_filing_id}`}>Prior comparable filing</Link>
          ) : null}
        </div>
      </section>

      <section className="detail-columns">
        <div className="detail-section">
          <span className="eyebrow">AI Summary</span>
          <h2>Key takeaways</h2>
          <p>{filing.summary}</p>
          <ul className="list-reset">
            {filing.key_takeaways.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="detail-section">
          <span className="eyebrow">Risk Lens</span>
          <h2>Material signals</h2>
          <p className="muted">
            Score confidence: {filing.score_explanation?.confidence ?? "high"}.
          </p>
          <ul className="list-reset">
            {filing.material_changes.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {filing.risk_flags.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {filing.opportunity_flags.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="grid-2">
        <div className="detail-section">
          <span className="eyebrow">Evidence Sections</span>
          <h2>Sections used in the summary</h2>
          {filing.evidence_sections.length ? (
            <div className="meta-list">
              {filing.evidence_sections.map((section) => (
                <span key={section} className="mini-tag">
                  {section}
                </span>
              ))}
            </div>
          ) : (
            <EmptyPanel title="No extracted sections" body="The parser did not identify canonical filing sections." />
          )}
        </div>
        <div className="detail-section">
          <span className="eyebrow">Score Breakdown</span>
          <h2>Ranking inputs</h2>
          <ul className="list-reset">
            {Object.entries(filing.score_explanation?.components ?? {}).map(([label, value]) => (
              <li key={label}>
                {label}: {value.toFixed(1)}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="detail-section">
        <span className="eyebrow">Parsed Filing</span>
        <h2>Canonical sections</h2>
        {Object.keys(filing.parsed_sections).length ? (
          <div className="grid-2">
            {Object.entries(filing.parsed_sections).map(([section, text]) => (
              <article key={section} className="panel">
                <h3>{section.replaceAll("_", " ")}</h3>
                <p>{text.slice(0, 2400)}</p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyPanel title="No parsed sections" body="The original document is still available through the SEC link and PDF export." />
        )}
      </section>
    </>
  );
}
