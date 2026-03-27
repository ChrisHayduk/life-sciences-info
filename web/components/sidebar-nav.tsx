"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Building2, Newspaper, FlaskConical, BookOpen, Eye } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/trials", label: "Trials", icon: FlaskConical },
  { href: "/digests", label: "Digests", icon: BookOpen },
  { href: "/watchlists", label: "Watchlists", icon: Eye },
];

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="grid gap-1.5">
      {navItems.map((item) => {
        const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            href={item.href}
            key={item.href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors",
              "border border-transparent",
              isActive
                ? "bg-white/12 border-white/10 text-white"
                : "text-white/70 hover:bg-white/8 hover:text-white"
            )}
          >
            <Icon className="size-4 shrink-0" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
