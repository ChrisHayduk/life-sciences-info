import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyPanel, SectionHeader } from "@/components/cards";
import { Markdown } from "@/components/markdown";
import { api, formatDate } from "@/lib/api";

export default async function DigestsPage() {
  const digests = await api.digests().catch(() => []);

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Digest Archive
        </span>
        <h2 className="text-2xl mt-1">Weekly review of filings and news</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          The digest captures the prior Monday through Sunday window and highlights the highest ranked items.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${digests.length} weekly digests`}
          description="Use this page for a compact recap before diving into individual filings or articles."
        />
        <div className="grid gap-4 md:grid-cols-2">
          {digests.length ? (
            digests.map((digest) => (
              <Card key={digest.id} className="border-border/50">
                <CardHeader className="p-5 pb-3">
                  <div className="flex items-center justify-between text-sm text-muted-foreground">
                    <Badge variant="secondary" className="text-xs">
                      {digest.digest_type}
                    </Badge>
                    <span className="text-xs">{formatDate(digest.published_at)}</span>
                  </div>
                  <h3 className="text-base font-semibold mt-2">{digest.title}</h3>
                </CardHeader>
                <CardContent className="px-5 pb-5 space-y-3">
                  <Markdown>{digest.narrative_summary}</Markdown>
                  <p className="text-xs text-muted-foreground">
                    {digest.payload.filings?.length ?? 0} filings and {digest.payload.news?.length ?? 0} news items
                  </p>
                  {(digest.payload.filings ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {(digest.payload.filings ?? []).slice(0, 3).map((item) => (
                        <Link
                          href={`/filings/${item.id}`}
                          key={item.id}
                          className="text-xs font-semibold text-primary hover:text-primary/80 underline underline-offset-2 decoration-1"
                        >
                          {item.title}
                        </Link>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
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
