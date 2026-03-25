import Link from "next/link";

import { EmptyPanel, SectionHeader } from "@/components/cards";
import { api, formatDate } from "@/lib/api";

export default async function DigestsPage() {
  const digests = await api.digests().catch(() => []);

  return (
    <>
      <section className="hero">
        <span className="eyebrow">Digest Archive</span>
        <h2>Weekly review of filings and news</h2>
        <p>The digest captures the prior Monday through Sunday window and highlights the highest ranked items.</p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${digests.length} weekly digests`}
          description="Use this page for a compact recap before diving into individual filings or articles."
        />
        <div className="grid-2">
          {digests.length ? (
            digests.map((digest) => (
              <article key={digest.id} className="panel">
                <div className="panel-topline">
                  <span className="tag">{digest.digest_type}</span>
                  <span>{formatDate(digest.published_at)}</span>
                </div>
                <h3>{digest.title}</h3>
                <p>{digest.narrative_summary}</p>
                <p className="muted">
                  {digest.payload.filings?.length ?? 0} filings and {digest.payload.news?.length ?? 0} news items
                </p>
                <div className="link-row">
                  {(digest.payload.filings ?? []).slice(0, 3).map((item) => (
                    <Link href={`/filings/${item.id}`} key={item.id}>
                      {item.title}
                    </Link>
                  ))}
                </div>
              </article>
            ))
          ) : (
            <EmptyPanel
              title="No digests yet"
              body="Build a weekly digest after loading filings or news to populate this archive."
            />
          )}
        </div>
      </section>
    </>
  );
}

