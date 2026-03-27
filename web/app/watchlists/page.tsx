"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Eye, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SectionHeader, EmptyPanel } from "@/components/cards";
import { api, Company, Watchlist, createWatchlist, deleteWatchlist } from "@/lib/api";

export default function WatchlistsPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<number[]>([]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    Promise.all([
      api.watchlists().catch(() => []),
      api.companies().catch(() => []),
    ]).then(([wl, co]) => {
      setWatchlists(wl);
      setCompanies(co);
      setLoading(false);
    });
  }, []);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const wl = await createWatchlist({
        name: newName.trim(),
        company_ids: selectedCompanyIds,
      });
      setWatchlists((prev) => [wl, ...prev]);
      setNewName("");
      setSelectedCompanyIds([]);
      setShowCreate(false);
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: number) {
    await deleteWatchlist(id);
    setWatchlists((prev) => prev.filter((w) => w.id !== id));
  }

  function toggleCompany(id: number) {
    setSelectedCompanyIds((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  }

  if (loading) {
    return (
      <section className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <p className="text-sm text-muted-foreground">Loading watchlists…</p>
      </section>
    );
  }

  return (
    <>
      <section className="rounded-2xl border border-border/50 bg-gradient-to-br from-card to-secondary/60 p-7 shadow-lg">
        <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Watchlists
        </span>
        <h2 className="text-2xl mt-1">Custom company tracking</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Create watchlists to group companies and get a filtered feed of their filings and news.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Your Watchlists"
          title={`${watchlists.length} watchlist${watchlists.length === 1 ? "" : "s"}`}
          description="Each watchlist generates a combined feed of filings and news for its tracked companies."
          actions={
            <button
              onClick={() => setShowCreate(!showCreate)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <Plus className="size-3.5" /> New watchlist
            </button>
          }
        />

        {showCreate && (
          <Card className="border-border/50 mb-4">
            <CardContent className="p-5 space-y-4">
              <div className="flex flex-col gap-1">
                <label htmlFor="wl-name" className="text-xs font-medium text-muted-foreground">
                  Watchlist name
                </label>
                <input
                  id="wl-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. Large Cap Oncology"
                  className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
                />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  Select companies ({selectedCompanyIds.length} selected)
                </span>
                <div className="max-h-48 overflow-y-auto rounded-lg border border-border p-2 grid gap-1">
                  {companies.map((co) => (
                    <label
                      key={co.id}
                      className="flex items-center gap-2 text-sm cursor-pointer hover:bg-accent rounded px-2 py-1"
                    >
                      <input
                        type="checkbox"
                        checked={selectedCompanyIds.includes(co.id)}
                        onChange={() => toggleCompany(co.id)}
                        className="rounded"
                      />
                      {co.name}
                      {co.ticker && (
                        <span className="text-xs text-muted-foreground">({co.ticker})</span>
                      )}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleCreate}
                  disabled={creating || !newName.trim()}
                  className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {creating ? "Creating…" : "Create watchlist"}
                </button>
                <button
                  onClick={() => setShowCreate(false)}
                  className="rounded-lg border border-border px-4 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
                >
                  Cancel
                </button>
              </div>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          {watchlists.length ? (
            watchlists.map((wl) => (
              <Card key={wl.id} className="border-border/50">
                <CardHeader className="p-5 pb-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold">{wl.name}</h3>
                    <button
                      onClick={() => handleDelete(wl.id)}
                      className="text-muted-foreground hover:text-destructive transition-colors"
                      title="Delete watchlist"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </CardHeader>
                <CardContent className="px-5 pb-5 space-y-3">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="secondary" className="text-xs">
                      {wl.company_ids.length} compan{wl.company_ids.length === 1 ? "y" : "ies"}
                    </Badge>
                    {wl.form_types.length > 0 && (
                      <Badge variant="outline" className="text-xs">
                        {wl.form_types.join(", ")}
                      </Badge>
                    )}
                    {wl.topic_tags.length > 0 && (
                      <Badge variant="outline" className="text-xs">
                        {wl.topic_tags.join(", ")}
                      </Badge>
                    )}
                  </div>
                  <Link
                    href={`/watchlists/${wl.id}`}
                    className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
                  >
                    <Eye className="size-3.5" /> View feed
                  </Link>
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyPanel
              title="No watchlists yet"
              body="Create a watchlist to start tracking specific companies and their filings and news."
            />
          )}
        </div>
      </section>
    </>
  );
}
