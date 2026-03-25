import Link from "next/link";

import { EmptyPanel, SectionHeader } from "@/components/cards";
import { api, formatMarketCap } from "@/lib/api";

export default async function CompaniesPage() {
  const companies = await api.companies().catch(() => []);

  return (
    <>
      <section className="hero">
        <span className="eyebrow">Universe</span>
        <h2>Covered life sciences issuers</h2>
        <p>
          Core SEC-reporting pharma, biotech, diagnostics, and medtech companies filtered by SIC codes plus
          manual overrides.
        </p>
      </section>

      <section className="detail-section">
        <SectionHeader
          eyebrow="Coverage"
          title={`${companies.length} active companies`}
          description="Market cap comes from the active market-data adapter and feeds the filing/news ranking model."
        />
        {companies.length ? (
          <div className="table-wrap">
            <table className="company-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Ticker</th>
                  <th>SIC</th>
                  <th>Market Cap</th>
                  <th>Universe Reason</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((company) => (
                  <tr key={company.id}>
                    <td>
                      <strong>
                        <Link href={`/companies/${company.id}`} className="inline-link">
                          {company.name}
                        </Link>
                      </strong>
                      <div className="muted">{company.exchange ?? "Exchange unavailable"}</div>
                    </td>
                    <td>{company.ticker ?? "N/A"}</td>
                    <td>
                      {company.sic ?? "N/A"}
                      <div className="muted">{company.sic_description ?? ""}</div>
                    </td>
                    <td>{formatMarketCap(company)}</td>
                    <td>{company.universe_reason_label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyPanel
            title="No companies loaded"
            body="Trigger the universe sync job to populate the SEC issuer coverage list."
          />
        )}
      </section>
    </>
  );
}
