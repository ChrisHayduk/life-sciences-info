"use client";

import { useEffect, useState } from "react";
import { BookmarkPlus, Check, Plus } from "lucide-react";
import { toast } from "sonner";
import { addCompaniesToWatchlist, api, createWatchlist, Watchlist } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

export function AddToWatchlistButton({
  companyIds,
  label = "Add to watchlist",
  variant = "outline",
}: {
  companyIds: number[];
  label?: string;
  variant?: "outline" | "default";
}) {
  const [open, setOpen] = useState(false);
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    if (!open) return;
    api.watchlists().then(setWatchlists).catch(() => setWatchlists([]));
  }, [open]);

  async function handleAdd(watchlistId: number) {
    setLoading(true);
    try {
      const updated = await addCompaniesToWatchlist(watchlistId, companyIds);
      setWatchlists((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      toast.success("Added to watchlist");
      setOpen(false);
    } catch {
      toast.error("Failed to update watchlist");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setLoading(true);
    try {
      const watchlist = await createWatchlist({
        name: newName.trim(),
        company_ids: companyIds,
      });
      setWatchlists((prev) => [watchlist, ...prev]);
      setNewName("");
      toast.success("Watchlist created");
      setOpen(false);
    } catch {
      toast.error("Failed to create watchlist");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant={variant} size="sm" className="gap-1.5">
            <BookmarkPlus className="size-3.5" />
            {label}
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add company to watchlist</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            {watchlists.length ? (
              watchlists.map((watchlist) => (
                <button
                  key={watchlist.id}
                  type="button"
                  onClick={() => handleAdd(watchlist.id)}
                  disabled={loading}
                  className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-accent transition-colors"
                >
                  <div>
                    <div className="font-medium">{watchlist.name}</div>
                    {watchlist.description ? (
                      <div className="text-xs text-muted-foreground">{watchlist.description}</div>
                    ) : null}
                  </div>
                  <Check className="size-4 text-muted-foreground" />
                </button>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No watchlists yet.</p>
            )}
          </div>
          <div className="rounded-lg border border-border p-3 space-y-2">
            <label className="text-xs font-medium text-muted-foreground">Create new watchlist</label>
            <div className="flex gap-2">
              <input
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="My tracked names"
                className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
              <Button type="button" size="sm" onClick={handleCreate} disabled={loading || !newName.trim()}>
                <Plus className="size-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
