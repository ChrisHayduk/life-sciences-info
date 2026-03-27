import Link from "next/link";
import { EmptyPanel, SectionHeader } from "@/components/cards";
import { api, formatMarketCap } from "@/lib/api";

export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const companies = await api.companies(params.q).catch(() => []);

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Universe
        </span>
        <h2 className="text-2xl mt-1">Covered life sciences issuers</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Core SEC-reporting pharma, biotech, diagnostics, and medtech companies filtered by SIC codes plus
          manual overrides.
        </p>
      </section>

      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Coverage"
          title={`${companies.length} active companies`}
          description="Market cap comes from the active market-data adapter and feeds the filing/news ranking model."
        />
        {/* Search */}
        <form className="mb-4">
          <input
            type="search"
            name="q"
            defaultValue={params.q ?? ""}
            placeholder="Search by name or ticker..."
            className="w-full max-w-sm rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </form>

        {companies.length ? (
          <div className="overflow-auto rounded-lg">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border/50">
                  <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Company</th>
                  <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Ticker</th>
                  <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">SIC</th>
                  <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Market Cap</th>
                  <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Universe Reason</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((company) => (
                  <tr key={company.id} className="border-b border-border/30 hover:bg-accent/30 transition-colors">
                    <td className="p-3">
                      <Link href={`/companies/${company.id}`} className="font-semibold text-primary underline underline-offset-2 decoration-1 hover:text-primary/80">
                        {company.name}
                      </Link>
                      <div className="text-xs text-muted-foreground">{company.exchange ?? "Exchange unavailable"}</div>
                    </td>
                    <td className="p-3 font-mono text-xs">{company.ticker ?? "N/A"}</td>
                    <td className="p-3">
                      <span className="font-mono text-xs">{company.sic ?? "N/A"}</span>
                      <div className="text-xs text-muted-foreground">{company.sic_description ?? ""}</div>
                    </td>
                    <td className="p-3 font-mono text-xs">{formatMarketCap(company)}</td>
                    <td className="p-3 text-xs text-muted-foreground">{company.universe_reason_label}</td>
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
