"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Eye, Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SectionHeader, EmptyPanel } from "@/components/cards";
import {
  api,
  Company,
  Watchlist,
  createStarterWatchlists,
  createWatchlist,
  deleteWatchlist,
} from "@/lib/api";

export default function WatchlistsPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
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
        description: newDescription.trim() || undefined,
        company_ids: selectedCompanyIds,
      });
      setWatchlists((prev) => [wl, ...prev]);
      setNewName("");
      setNewDescription("");
      setSelectedCompanyIds([]);
      setShowCreate(false);
      toast.success("Watchlist created");
    } finally {
      setCreating(false);
    }
  }

  async function handleCreateStarters() {
    try {
      const starters = await createStarterWatchlists();
      setWatchlists((prev) => {
        const merged = [...starters, ...prev];
        const seen = new Set<number>();
        return merged.filter((item) => {
          if (seen.has(item.id)) return false;
          seen.add(item.id);
          return true;
        });
      });
      toast.success("Starter watchlists ready");
    } catch {
      toast.error("Failed to create starter watchlists");
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
        <h2 className="text-2xl mt-1">Personal follow-up workspaces</h2>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          Watchlists are the main handoff from the market-wide dashboard into the names you want to keep up with.
        </p>
      </section>

      <section>
        <SectionHeader
          eyebrow="Your Watchlists"
          title={`${watchlists.length} watchlist${watchlists.length === 1 ? "" : "s"}`}
          description="Each watchlist now has a briefing view with grouped filings, news, trial updates, and a merged timeline."
          actions={
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleCreateStarters}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
              >
                <Sparkles className="size-3.5" /> Starter watchlists
              </button>
              <button
                onClick={() => setShowCreate(!showCreate)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                <Plus className="size-3.5" /> New watchlist
              </button>
            </div>
          }
        />

        {showCreate && (
          <Card className="border-border/50 mb-4">
            <CardContent className="p-5 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <label htmlFor="wl-name" className="text-xs font-medium text-muted-foreground">
                    Watchlist name
                  </label>
                  <input
                    id="wl-name"
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g. Oncology leaders"
                    className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor="wl-description" className="text-xs font-medium text-muted-foreground">
                    Description
                  </label>
                  <input
                    id="wl-description"
                    type="text"
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Why this watchlist exists"
                    className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
                  />
                </div>
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
                    <div>
                      <h3 className="text-base font-semibold">{wl.name}</h3>
                      {wl.description ? (
                        <p className="text-sm text-muted-foreground mt-1">{wl.description}</p>
                      ) : null}
                    </div>
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
                    {wl.preset_key ? (
                      <Badge variant="outline" className="text-xs font-normal">
                        preset
                      </Badge>
                    ) : null}
                  </div>
                  <Link
                    href={`/watchlists/${wl.id}`}
                    className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary/80"
                  >
                    <Eye className="size-3.5" /> View briefing
                  </Link>
                </CardContent>
              </Card>
            ))
          ) : (
            <EmptyPanel
              title="No watchlists yet"
              body="Create a watchlist or generate the starter set to turn the dashboard into a personal workflow."
            />
          )}
        </div>
      </section>
    </>
  );
}
