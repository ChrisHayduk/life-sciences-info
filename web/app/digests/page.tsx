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
        <h2 className="text-2xl mt-1">Daily and weekly reviews of filings and news</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Daily briefings recap already-summarized items from the prior day, while weekly digests synthesize the prior Monday through Sunday window.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Archive"
          title={`${digests.length} saved digests`}
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
                    <div className="space-y-1 pt-1">
                      <span className="text-xs font-medium text-muted-foreground">Top Filings</span>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {(digest.payload.filings ?? []).slice(0, 5).map((item) => (
                          <span key={item.id} className="text-xs">
                            <Link
                              href={`/filings/${item.id}`}
                              className="font-semibold text-primary hover:text-primary/80 underline underline-offset-2 decoration-1"
                            >
                              {item.title}
                            </Link>
                            {item.company_name && item.company_id && (
                              <>
                                {" · "}
                                <Link
                                  href={`/companies/${item.company_id}`}
                                  className="text-muted-foreground hover:text-primary"
                                >
                                  {item.company_name}
                                </Link>
                              </>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {(digest.payload.news ?? []).length > 0 && (
                    <div className="space-y-1 pt-1">
                      <span className="text-xs font-medium text-muted-foreground">Top News</span>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {(digest.payload.news ?? []).slice(0, 5).map((item) => (
                          <span key={item.id} className="text-xs">
                            <span className="font-semibold">{item.title}</span>
                            <span className="text-muted-foreground"> ({item.source_name})</span>
                            {(item.mentioned_companies ?? []).length > 0 && (item.company_tag_ids ?? []).length > 0 && (
                              <>
                                {" · "}
                                {item.mentioned_companies!.slice(0, 2).map((name, i) => {
                                  const cid = item.company_tag_ids?.[i];
                                  return (
                                    <span key={`${item.id}-${i}`}>
                                      {i > 0 && ", "}
                                      {cid ? (
                                        <Link href={`/companies/${cid}`} className="text-muted-foreground hover:text-primary">
                                          {name}
                                        </Link>
                                      ) : (
                                        <span className="text-muted-foreground">{name}</span>
                                      )}
                                    </span>
                                  );
                                })}
                              </>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyPanel
              title="No digests yet"
              body="Build a daily or weekly digest after loading filings or news to populate this archive."
            />
          )}
        </div>
      </section>
    </>
  );
}
