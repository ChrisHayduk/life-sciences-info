import { EmptyPanel, NewsCard, SectionHeader } from "@/components/cards";
import { api } from "@/lib/api";

export default async function NewsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const limit = 20;
  const offset = (page - 1) * limit;

  const result = await api
    .news({
      limit,
      offset,
      source_name: params.source,
      search: params.q,
      sort_by: params.sort,
    })
    .catch(() => ({ items: [], total: 0, offset: 0, limit }));

  const totalPages = Math.ceil(result.total / limit);

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          News Feed
        </span>
        <h2 className="text-2xl mt-1">Important life sciences headlines</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Browse the continuously ingested archive from public feeds, summarized and ranked for company relevance
          and operating impact.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${result.total} ranked stories`}
          description="Starting sources: Fierce Pharma, Fierce Biotech, and FDA press releases."
        />
        <div className="grid gap-4 md:grid-cols-2">
          {result.items.length ? (
            result.items.map((item) => <NewsCard key={item.id} item={item} />)
          ) : (
            <EmptyPanel title="No news available" body="Run the feed ingestion job to populate the archive." />
          )}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            {page > 1 && (
              <a
                href={`/news?page=${page - 1}${params.source ? `&source=${params.source}` : ""}${params.q ? `&q=${params.q}` : ""}`}
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
                href={`/news?page=${page + 1}${params.source ? `&source=${params.source}` : ""}${params.q ? `&q=${params.q}` : ""}`}
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
