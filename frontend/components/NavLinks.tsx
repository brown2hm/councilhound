"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

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

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1">
      {NAV.map((n) => {
        const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
        const isAsk = n.href === "/ask";
        return (
          <Link
            key={n.href}
            href={n.href}
            className={`rounded-full px-4 py-2 text-sm ${
              isAsk
                ? `font-semibold text-hound ${active ? "bg-card" : "hover:bg-soft"}`
                : active
                  ? "bg-card font-medium text-ink"
                  : "font-medium text-muted hover:text-ink"
            }`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}
