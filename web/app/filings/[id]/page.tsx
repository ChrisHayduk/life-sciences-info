import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Download, ExternalLink, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyPanel, NewsCard, ScorePill } from "@/components/cards";
import { Markdown } from "@/components/markdown";
import { CollapsibleSection } from "@/components/collapsible-section";
import { AddToWatchlistButton } from "@/components/watchlist-actions";
import { SummarizeButton } from "@/components/summary-actions";
import { api, formatDate } from "@/lib/api";

export default async function FilingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const filing = await api.filing(id).catch(() => null);
  if (!filing) notFound();

  return (
    <>
      {/* Hero */}
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <Badge variant="secondary" className="font-mono text-xs">
          {filing.form_type}
        </Badge>
        <h1 className="text-2xl mt-2">{filing.title ?? `${filing.company_name} ${filing.form_type}`}</h1>
        <p className="text-sm text-muted-foreground mt-2">
          <Link href={`/companies/${filing.company_id}`} className="text-primary underline underline-offset-2 decoration-1 hover:text-primary/80">
            {filing.company_name}
          </Link>
          {filing.ticker ? ` (${filing.ticker})` : ""} filed this report on {formatDate(filing.filed_at)}.
        </p>
        <div className="flex flex-wrap gap-1.5 mt-4">
          <ScorePill label="Composite" value={filing.composite_score} />
          <ScorePill label="Impact" value={filing.impact_score} />
          <ScorePill label="Importance" value={filing.importance_score} />
          <ScorePill label="Mkt Cap" value={filing.market_cap_score} />
          <Badge variant="outline" className="text-xs font-normal">
            {filing.source_type.replaceAll("_", " ")}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {filing.freshness_bucket.replaceAll("_", " ")}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal">
            {filing.summary_tier.replaceAll("_", " ")}
          </Badge>
        </div>
        {filing.priority_reason ? (
          <p className="text-sm text-muted-foreground mt-3">
            Why it matters: {filing.priority_reason}.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-4 mt-4">
          {filing.pdf_download_url && (
            <a href={filing.pdf_download_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
              <Download className="size-3.5" /> Download PDF
            </a>
          )}
          <a href={filing.original_document_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
            <ExternalLink className="size-3.5" /> Original SEC document
          </a>
          {filing.prior_comparable_filing_id && (
            <Link href={`/filings/${filing.prior_comparable_filing_id}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
              <FileText className="size-3.5" /> Prior comparable filing
            </Link>
          )}
          <AddToWatchlistButton companyIds={[filing.company_id]} label="Track company" />
        </div>
      </section>

      {/* Summary + Risk Lens */}
      <section className="grid gap-6 lg:grid-cols-[1.3fr_0.9fr]">
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">AI Summary</span>
              <h2 className="text-lg mt-1">Key takeaways</h2>
            </div>
            {filing.summary_status === "complete" ? (
              <>
                <Markdown>{filing.summary}</Markdown>
                <ul className="space-y-1.5 text-sm pl-4 list-disc marker:text-muted-foreground">
                  {filing.key_takeaways.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-sm leading-relaxed">
                  {filing.summary || "This filing is stored and ranked already. AI summary generation is budget-limited and will run automatically for higher-priority new items."}
                </p>
                <p className="text-xs text-muted-foreground">
                  This is the rule-based fallback view. You can spend one manual override slot to summarize this filing now.
                </p>
                <SummarizeButton kind="filing" itemId={filing.id} summaryStatus={filing.summary_status} />
              </div>
            )}
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Risk Lens</span>
              <h2 className="text-lg mt-1">Material signals</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Score confidence: {filing.score_explanation?.confidence ?? "high"}.
            </p>
            {filing.summary_status === "complete" ? (
              <ul className="space-y-1.5 text-sm pl-4 list-disc marker:text-muted-foreground">
                {filing.material_changes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
                {filing.risk_flags.map((item) => (
                  <li key={item} className="text-[var(--color-alert)]">{item}</li>
                ))}
                {filing.opportunity_flags.map((item) => (
                  <li key={item} className="text-emerald-700 dark:text-emerald-400">{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                The provisional rank currently uses market cap, form type, recency, and material keywords.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Diff Analysis (if prior comparable exists and diff is complete) */}
      {filing.diff_status === "complete" && filing.diff_json?.summary && (
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-4">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                Changes from Prior Filing
              </span>
              <h2 className="text-lg mt-1">Filing-over-filing analysis</h2>
            </div>
            <p className="text-sm leading-relaxed">{filing.diff_json.summary}</p>
            <div className="grid gap-4 sm:grid-cols-2">
              {(filing.diff_json.added_risks?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-alert)] mb-2">New risks</h3>
                  <ul className="space-y-1 text-sm pl-4 list-disc marker:text-[var(--color-alert)]">
                    {filing.diff_json.added_risks!.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                </div>
              )}
              {(filing.diff_json.removed_risks?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-emerald-700 dark:text-emerald-400 mb-2">Resolved risks</h3>
                  <ul className="space-y-1 text-sm pl-4 list-disc marker:text-emerald-500">
                    {filing.diff_json.removed_risks!.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                </div>
              )}
              {(filing.diff_json.financial_deltas?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Financial changes</h3>
                  <ul className="space-y-1 text-sm pl-4 list-disc marker:text-muted-foreground">
                    {filing.diff_json.financial_deltas!.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                </div>
              )}
              {(filing.diff_json.guidance_changes?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Guidance changes</h3>
                  <ul className="space-y-1 text-sm pl-4 list-disc marker:text-muted-foreground">
                    {filing.diff_json.guidance_changes!.map((g) => <li key={g}>{g}</li>)}
                  </ul>
                </div>
              )}
              {(filing.diff_json.pipeline_updates?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Pipeline updates</h3>
                  <ul className="space-y-1 text-sm pl-4 list-disc marker:text-muted-foreground">
                    {filing.diff_json.pipeline_updates!.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Evidence + Score Breakdown */}
      <section className="grid gap-6 md:grid-cols-2">
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-3">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Evidence Sections</span>
              <h2 className="text-lg mt-1">Sections used in the summary</h2>
            </div>
            {filing.evidence_sections.length ? (
              <div className="flex flex-wrap gap-1.5">
                {filing.evidence_sections.map((section) => (
                  <Badge key={section} variant="outline" className="text-xs font-normal">
                    {section}
                  </Badge>
                ))}
              </div>
            ) : (
              <EmptyPanel title="No extracted sections" body="The parser did not identify canonical filing sections." />
            )}
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-3">
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Score Breakdown</span>
              <h2 className="text-lg mt-1">Ranking inputs</h2>
            </div>
            <ul className="space-y-1.5 text-sm pl-4 list-disc marker:text-muted-foreground">
              {Object.entries(filing.score_explanation?.components ?? {}).map(([label, value]) => (
                <li key={label}>
                  <span className="font-medium">{label}:</span>{" "}
                  <span className="font-mono">{value.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      {/* Parsed Filing Sections */}
      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg space-y-4">
        <div>
          <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Parsed Filing</span>
          <h2 className="text-lg mt-1">Canonical sections</h2>
        </div>
        {Object.keys(filing.parsed_sections).length ? (
          <div className="grid gap-4 md:grid-cols-2">
            {Object.entries(filing.parsed_sections).map(([section, text]) => (
              <Card key={section} className="border-border/50">
                <CardContent className="p-5">
                  <CollapsibleSection
                    title={section.replaceAll("_", " ")}
                    text={text}
                    previewLength={800}
                  />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyPanel title="No parsed sections" body="The original document is still available through the SEC link and PDF export." />
        )}
      </section>

      {/* Related News */}
      {(filing.related_news ?? []).length > 0 && (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg space-y-4">
          <div>
            <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Cross-Reference</span>
            <h2 className="text-lg mt-1">Related news coverage</h2>
            <p className="text-sm text-muted-foreground mt-1">News articles linked to this filing based on event overlap.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {filing.related_news!.map((item) => (
              <NewsCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}

      {/* Back link */}
      <Link href="/companies" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
        <ArrowLeft className="size-3.5" /> Back to companies
      </Link>
    </>
  );
}
