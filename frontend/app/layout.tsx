import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CouncilHound — City of Fairfax",
  description:
    "CouncilHound sniffs through City of Fairfax council and planning commission records so you can track projects, votes, and decisions over time.",
};

const nav = [
  { href: "/topics", label: "Tracker" },
  { href: "/meetings", label: "Meetings" },
  { href: "/ask", label: "Ask" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-5xl items-center gap-8 px-4 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              <span aria-hidden className="mr-1.5">🐕</span>Council<span className="text-amber-600">Hound</span>
            </Link>
            <nav className="flex gap-5 text-sm font-medium text-slate-600">
              {nav.map((n) => (
                <Link key={n.href} href={n.href} className="hover:text-slate-900">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 pb-8 text-xs text-slate-400">
          CouncilHound fetches from public City of Fairfax, VA meeting records on Granicus.
          Summaries are machine-generated — always verify against the linked source documents.
        </footer>
      </body>
    </html>
  );
}
