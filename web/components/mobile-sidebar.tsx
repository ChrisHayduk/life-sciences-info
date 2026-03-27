"use client";

import { useState } from "react";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { SidebarNav } from "@/components/sidebar-nav";

export function MobileSidebar() {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger className="inline-flex items-center justify-center size-8 rounded-md hover:bg-accent transition-colors">
        <Menu className="size-5" />
        <span className="sr-only">Open navigation</span>
      </SheetTrigger>
      <SheetContent side="left" className="w-72 bg-[var(--sidebar)] text-[var(--sidebar-foreground)] border-none p-6">
        <SheetTitle className="text-[var(--sidebar-foreground)]">
          <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--color-sidebar-muted)] block mb-1">
            Life Sciences
          </span>
          Intel Grid
        </SheetTitle>
        <div className="mt-6">
          <SidebarNav onNavigate={() => setOpen(false)} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
