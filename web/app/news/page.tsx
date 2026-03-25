import { EmptyPanel, NewsCard, SectionHeader } from "@/components/cards";
import { api } from "@/lib/api";

export default async function NewsPage() {
  const newsItems = await api.news().catch(() => []);

  return (
    <>
      <section className="hero">
        <span className="eyebrow">News Feed</span>
        <h2>Important life sciences headlines</h2>
        <p>
          Browse the continuously ingested archive from public feeds, summarized and ranked for company relevance
          and operating impact.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${newsItems.length} ranked stories`}
          description="Starting sources: Fierce Pharma, Fierce Biotech, and FDA press releases."
        />
        <div className="grid-2">
          {newsItems.length ? (
            newsItems.map((item) => <NewsCard key={item.id} item={item} />)
          ) : (
            <EmptyPanel title="No news available" body="Run the feed ingestion job to populate the archive." />
          )}
        </div>
      </section>
    </>
  );
}

