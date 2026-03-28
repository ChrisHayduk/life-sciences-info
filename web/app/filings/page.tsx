import { EmptyPanel, FilingCard, SectionHeader } from "@/components/cards";
import { api } from "@/lib/api";

const FORM_OPTIONS = ["10-K", "20-F", "40-F", "10-Q", "8-K", "6-K"];

export default async function FilingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const limit = 20;
  const offset = (page - 1) * limit;

  const result = await api
    .filings({
      limit,
      offset,
      form_type: params.form_type,
      search: params.q,
      sort_by: params.sort,
      recent_days: Number(params.recent_days) || undefined,
      sort_mode: params.sort_mode,
    })
    .catch(() => ({ items: [], total: 0, offset: 0, limit }));

  const totalPages = Math.ceil(result.total / limit);

  function buildPageUrl(newPage: number) {
    const parts = [`/filings?page=${newPage}`];
    if (params.form_type) parts.push(`form_type=${encodeURIComponent(params.form_type)}`);
    if (params.q) parts.push(`q=${encodeURIComponent(params.q)}`);
    if (params.sort_mode) parts.push(`sort_mode=${encodeURIComponent(params.sort_mode)}`);
    if (params.recent_days) parts.push(`recent_days=${encodeURIComponent(params.recent_days)}`);
    return parts.join("&");
  }

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Filing Archive
        </span>
        <h2 className="text-2xl mt-1">Ranked SEC disclosures</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Browse the tracked universe of annual, quarterly, and material event filings with the same freshness and importance controls used on the dashboard.
        </p>
      </section>

      <section className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm">
        <form className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label htmlFor="q" className="text-xs font-medium text-muted-foreground">Search</label>
            <input
              id="q"
              name="q"
              type="text"
              placeholder="Search company or filing title..."
              defaultValue={params.q ?? ""}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="form_type" className="text-xs font-medium text-muted-foreground">Form type</label>
            <select
              id="form_type"
              name="form_type"
              defaultValue={params.form_type ?? ""}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="">All forms</option>
              {FORM_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="sort_mode" className="text-xs font-medium text-muted-foreground">Sort</label>
            <select
              id="sort_mode"
              name="sort_mode"
              defaultValue={params.sort_mode ?? "importance"}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="importance">Most important</option>
              <option value="freshness">Newest</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="recent_days" className="text-xs font-medium text-muted-foreground">Window</label>
            <select
              id="recent_days"
              name="recent_days"
              defaultValue={params.recent_days ?? "90"}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
              <option value="365">Last 12 months</option>
              <option value="">All available</option>
            </select>
          </div>
          <button
            type="submit"
            className="rounded-lg border border-border bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Apply
          </button>
        </form>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${result.total} filings`}
          description="This view keeps the dashboard’s ranking logic but makes it easier to search and filter the full filing set."
        />
        <div className="grid gap-4 md:grid-cols-2">
          {result.items.length ? (
            result.items.map((item) => <FilingCard key={item.id} filing={item} />)
          ) : (
            <EmptyPanel title="No filings available" body="Run the filing backfill or polling jobs to populate the archive." />
          )}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            {page > 1 && (
              <a
                href={buildPageUrl(page - 1)}
                className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
              >
                Previous
              </a>
            )}
            <span className="text-sm text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            {page < totalPages && (
              <a
                href={buildPageUrl(page + 1)}
                className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
              >
                Next
              </a>
            )}
          </div>
        )}
      </section>
    </>
  );
}
