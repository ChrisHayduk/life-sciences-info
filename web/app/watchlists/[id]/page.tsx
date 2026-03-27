import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EmptyPanel, FilingCard, NewsCard, SectionHeader } from "@/components/cards";
import { api } from "@/lib/api";

export default async function WatchlistFeedPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const data = await api.watchlistFeed(id).catch(() => null);
  if (!data) notFound();

  const companies = await api.companies().catch(() => []);
  const trackedCompanies = companies.filter((c) =>
    data.watchlist.company_ids.includes(c.id)
  );

  return (
    <>
      {/* Hero */}
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Watchlist
        </span>
        <h1 className="text-3xl mt-1">{data.watchlist.name}</h1>
        {trackedCompanies.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {trackedCompanies.map((co) => (
              <Link key={co.id} href={`/companies/${co.id}`}>
                <Badge variant="outline" className="text-xs font-normal hover:bg-accent transition-colors cursor-pointer">
                  {co.name}{co.ticker ? ` (${co.ticker})` : ""}
                </Badge>
              </Link>
            ))}
          </div>
        )}
        <p className="text-sm text-muted-foreground mt-3">
          {data.filings.length} filings and {data.news.length} news items matching this watchlist.
        </p>
      </section>

      {/* Feed */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="Filings"
            title="Watchlist filings"
            description="SEC filings from tracked companies, ranked by composite score."
          />
          <div className="space-y-4">
            {data.filings.length ? (
              data.filings.map((filing) => <FilingCard key={filing.id} filing={filing} />)
            ) : (
              <EmptyPanel title="No filings yet" body="Filings will appear here once tracked companies have SEC documents." />
            )}
          </div>
        </div>
        <div>
          <SectionHeader
            eyebrow="News"
            title="Watchlist news"
            description="News articles mentioning tracked companies, ranked by composite score."
          />
          <div className="space-y-4">
            {data.news.length ? (
              data.news.map((item) => <NewsCard key={item.id} item={item} />)
            ) : (
              <EmptyPanel title="No news yet" body="News will appear here once articles mention tracked companies." />
            )}
          </div>
        </div>
      </section>

      {/* Back link */}
      <Link href="/watchlists" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
        <ArrowLeft className="size-3.5" /> Back to watchlists
      </Link>
    </>
  );
}
