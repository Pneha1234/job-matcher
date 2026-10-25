"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { OllamaStatus } from "@/components/ollama-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/jobs", label: "Jobs" },
  { href: "/applications", label: "Applications" },
  { href: "/insights", label: "Insights" },
  { href: "/sources", label: "Sources" },
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
] as const;

function NavLinks() {
  const pathname = usePathname();
  return (
    <>
      {NAV.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex w-auto items-center gap-2.5 rounded-lg px-2.5 py-2 text-muted-foreground hover:bg-muted md:w-full",
              active && "bg-sidebar-accent font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent",
            )}
          >
            {label}
          </Link>
        );
      })}
    </>
  );
}

export function Sidebar() {
  return (
    <aside className="flex flex-row flex-wrap gap-1 border-b border-sidebar-border bg-sidebar px-4 py-2.5 md:sticky md:top-0 md:h-screen md:flex-col md:flex-nowrap md:border-r md:border-b-0 md:px-3 md:py-4">
      <div className="flex items-center gap-2.5 px-2 py-1 text-base font-semibold text-foreground md:pb-4">
        <div className="grid size-[30px] place-items-center rounded-lg bg-primary font-bold text-primary-foreground">
          J
        </div>
        Job matcher
      </div>
      <NavLinks />
      <div className="mt-auto hidden border-t border-sidebar-border p-2 text-xs text-faint md:block">
        <OllamaStatus />
        <div>No scrapes yet</div>
        <div className="mt-2">
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
