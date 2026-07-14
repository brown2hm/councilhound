"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Briefing" },
  { href: "/topics", label: "Tracker" },
  { href: "/meetings", label: "Meetings" },
  { href: "/members", label: "Members" },
  { href: "/ask", label: "Ask" },
];

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1">
      {NAV.map((n) => {
        const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            className={`rounded-full px-4 py-2 text-sm font-medium ${
              active ? "bg-card text-ink" : "text-muted hover:text-ink"
            }`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}
