import { EmptyPanel, SectionHeader, TrialCard } from "@/components/cards";
import { api } from "@/lib/api";

export default async function TrialsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const limit = 20;
  const offset = (page - 1) * limit;

  const result = await api
    .trials({
      limit,
      offset,
      phase: params.phase,
      status: params.status,
      search: params.q,
    })
    .catch(() => ({ items: [], total: 0, offset: 0, limit }));

  const totalPages = Math.ceil(result.total / limit);

  function buildPageUrl(newPage: number) {
    const parts = [`/trials?page=${newPage}`];
    if (params.phase) parts.push(`phase=${encodeURIComponent(params.phase)}`);
    if (params.status) parts.push(`status=${encodeURIComponent(params.status)}`);
    if (params.q) parts.push(`q=${encodeURIComponent(params.q)}`);
    return parts.join("&");
  }

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Clinical Trials
        </span>
        <h2 className="text-2xl mt-1">Pipeline intelligence across tracked companies</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Browse clinical trials from ClinicalTrials.gov for all companies in the tracked universe,
          with links back to the sponsoring company.
        </p>
      </section>

      {/* Filters */}
      <section className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm">
        <form className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label htmlFor="q" className="text-xs font-medium text-muted-foreground">Search</label>
            <input
              id="q"
              name="q"
              type="text"
              placeholder="Search by title..."
              defaultValue={params.q ?? ""}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="phase" className="text-xs font-medium text-muted-foreground">Phase</label>
            <select
              id="phase"
              name="phase"
              defaultValue={params.phase ?? ""}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="">All phases</option>
              <option value="Phase 3">Phase 3</option>
              <option value="Phase 2/Phase 3">Phase 2/3</option>
              <option value="Phase 2">Phase 2</option>
              <option value="Phase 1/Phase 2">Phase 1/2</option>
              <option value="Phase 1">Phase 1</option>
              <option value="Early Phase 1">Early Phase 1</option>
              <option value="Phase 4">Phase 4</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="status" className="text-xs font-medium text-muted-foreground">Status</label>
            <select
              id="status"
              name="status"
              defaultValue={params.status ?? ""}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="">All statuses</option>
              <option value="Recruiting">Recruiting</option>
              <option value="Active, not recruiting">Active, not recruiting</option>
              <option value="Completed">Completed</option>
              <option value="Not yet recruiting">Not yet recruiting</option>
              <option value="Terminated">Terminated</option>
              <option value="Withdrawn">Withdrawn</option>
              <option value="Suspended">Suspended</option>
            </select>
          </div>
          <button
            type="submit"
            className="rounded-lg border border-border bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Filter
          </button>
        </form>
      </section>

      <section>
        <SectionHeader
          eyebrow="Registry"
          title={`${result.total} clinical trials`}
          description="Trials sourced from ClinicalTrials.gov, linked to tracked companies by sponsor name."
        />
        <div className="grid gap-3 md:grid-cols-2">
          {result.items.length ? (
            result.items.map((trial) => <TrialCard key={trial.id} trial={trial} />)
          ) : (
            <EmptyPanel title="No trials found" body="Adjust your filters or run the trial polling job to load clinical trial data." />
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
