"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/", label: "Briefing" },
  { href: "/topics", label: "Tracker" },
  { href: "/development", label: "Development" },
  { href: "/meetings", label: "Meetings" },
  { href: "/members", label: "Members" },
  { href: "/map", label: "Map" },
  { href: "/search", label: "Search" },
  { href: "/ask", label: "Ask" },
];

function linkClasses(href: string, pathname: string, mobile = false) {
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
  const isAsk = href === "/ask";
  const shape = mobile ? "block rounded-xl px-4 py-3 text-[15px]" : "rounded-full px-4 py-2 text-sm";
  if (isAsk) return `${shape} font-semibold text-hound ${active ? "bg-card" : "hover:bg-soft"}`;
  if (active) return `${shape} bg-card font-medium text-ink`;
  return `${shape} font-medium text-muted hover:text-ink`;
}

export default function NavLinks() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // navigating away always closes the menu
  useEffect(() => setOpen(false), [pathname]);

  return (
    <>
      <nav className="hidden gap-1 lg:flex">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={linkClasses(n.href, pathname)}>
            {n.label}
          </Link>
        ))}
      </nav>

      <button
        type="button"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 w-10 items-center justify-center rounded-xl border border-hairline lg:hidden"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
          {open ? (
            <path d="M3 3l12 12M15 3L3 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          ) : (
            <path d="M2 4h14M2 9h14M2 14h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          )}
        </svg>
      </button>

      {open && (
        <nav className="absolute inset-x-0 top-16 z-20 border-b border-hairline bg-canvas px-4 pb-4 pt-2 shadow-lg lg:hidden">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={linkClasses(n.href, pathname, true)}>
              {n.label}
            </Link>
          ))}
        </nav>
      )}
    </>
  );
}
