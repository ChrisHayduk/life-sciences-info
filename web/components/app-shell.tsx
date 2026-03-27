import { ReactNode } from "react";
import { MobileSidebar } from "@/components/mobile-sidebar";
import { SidebarNav } from "@/components/sidebar-nav";
import { ThemeToggle } from "@/components/theme-toggle";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[280px_minmax(0,1fr)]">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col gap-7 bg-[var(--sidebar)] text-[var(--sidebar-foreground)] p-7">
        <div>
          <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--color-sidebar-muted)]">
            Life Sciences
          </span>
          <h1 className="text-2xl font-bold mt-1">Intel Grid</h1>
          <p className="text-sm text-[var(--color-sidebar-muted)] mt-2 leading-relaxed">
            Filings, market context, and news ranked by what matters now.
          </p>
        </div>
        <SidebarNav />
        <div className="mt-auto space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-[var(--color-sidebar-muted)]">Core SEC issuer universe</p>
            <ThemeToggle />
          </div>
          <p className="text-xs text-[var(--color-sidebar-muted)]">
            Weekly digest every Monday at 8:00 AM ET
          </p>
        </div>
      </aside>

      {/* Mobile header + main */}
      <div className="flex flex-col">
        <header className="flex md:hidden items-center justify-between gap-4 border-b border-border bg-card px-4 py-3">
          <MobileSidebar />
          <h1 className="text-lg font-bold">Intel Grid</h1>
          <ThemeToggle />
        </header>
        <main className="flex-1 p-5 md:p-8 space-y-6">
          {children}
        </main>
      </div>
    </div>
  );
}
