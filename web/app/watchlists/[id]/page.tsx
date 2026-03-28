import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  EmptyPanel,
  FilingCard,
  NewsCard,
  SectionHeader,
  TimelineEventCard,
  TrialCard,
} from "@/components/cards";
import { api } from "@/lib/api";

export default async function WatchlistFeedPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const data = await api.watchlistBriefing(id).catch(() => null);
  const companies = await api.companies().catch(() => []);
  if (!data) notFound();
  const trackedCompanies = companies.filter((company) => data.watchlist.company_ids.includes(company.id));

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Watchlist Briefing
        </span>
        <h1 className="text-3xl mt-1">{data.watchlist.name}</h1>
        {data.watchlist.description ? (
          <p className="text-sm text-muted-foreground mt-2 max-w-3xl">{data.watchlist.description}</p>
        ) : null}
        <div className="flex flex-wrap gap-1.5 mt-3">
          {trackedCompanies.slice(0, 12).map((company) => (
            <Link key={company.id} href={`/companies/${company.id}`}>
              <Badge variant="outline" className="text-xs font-normal hover:bg-accent transition-colors cursor-pointer">
                {company.name}
              </Badge>
            </Link>
          ))}
        </div>
        <p className="text-sm text-muted-foreground mt-3">
          {data.filings.length} filings, {data.news.length} news items, and {data.trials.length} trials in the current briefing.
        </p>
      </section>

      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Highlights"
          title="What to read next"
          description="These are the highest-priority, watchlist-relevant events across filings, news, and trials."
        />
        <div className="grid gap-4 lg:grid-cols-2">
          {data.highlights.length ? (
            data.highlights.map((event) => <TimelineEventCard key={event.id} event={event} />)
          ) : (
            <EmptyPanel title="No highlights yet" body="Once tracked companies have activity, the most relevant items will appear here." />
          )}
        </div>
      </section>

      {data.catalysts.length ? (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Catalysts"
            title="Upcoming and recent signals"
            description="Structured catalysts blend official press releases, event filings, and trial milestones across the tracked set."
          />
          <div className="grid gap-4 lg:grid-cols-2">
            {data.catalysts.map((event) => <TimelineEventCard key={event.id} event={event} />)}
          </div>
        </section>
      ) : null}

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionHeader
            eyebrow="Filings"
            title="Tracked company filings"
            description="Personal relevance comes first here, then freshness."
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
            title="Tracked company news"
            description="News is deduped by event group so you see the cleanest representative story first."
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

      {data.trials.length ? (
        <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
          <SectionHeader
            eyebrow="Trials"
            title="Pipeline context"
            description="Clinical trial changes are included so watchlists capture both disclosures and forward catalysts."
          />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {data.trials.map((trial) => (
              <TrialCard key={trial.id} trial={trial} />
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <SectionHeader
          eyebrow="Timeline"
          title="Merged watchlist timeline"
          description="A single chronological stream across filings, news, and trials."
        />
        <div className="grid gap-4 lg:grid-cols-2">
          {data.timeline.length ? (
            data.timeline.map((event) => <TimelineEventCard key={event.id} event={event} />)
          ) : (
            <EmptyPanel title="No timeline yet" body="New watchlist activity will appear here as soon as tracked companies have events." />
          )}
        </div>
      </section>

      <Link href="/watchlists" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80">
        <ArrowLeft className="size-3.5" /> Back to watchlists
      </Link>
    </>
  );
}
