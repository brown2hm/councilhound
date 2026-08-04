"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Tab bar for the development project page. The Wiki tab always exists;
 * Impact analysis and Documents appear only when there is something behind
 * them, and a missing analysis carries its editorial reason instead. */
export default function ProjectTabs({
  slug,
  hasAnalysis,
  hasDocuments,
  noAnalysisReason,
}: {
  slug: string;
  hasAnalysis: boolean;
  hasDocuments: boolean;
  noAnalysisReason?: string | null;
}) {
  const pathname = usePathname();
  const base = `/development/${slug}`;
  const tabs = [
    { href: base, label: "Wiki", exact: true },
    ...(hasAnalysis ? [{ href: `${base}/analysis`, label: "Impact analysis", exact: false }] : []),
    ...(hasDocuments ? [{ href: `${base}/documents`, label: "Documents", exact: false }] : []),
  ];
  return (
    <nav className="mb-8 flex flex-wrap items-center gap-2 border-b border-hairline pb-3">
      {tabs.map((t) => {
        const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`rounded-full px-4 py-2 text-sm font-medium ${
              active
                ? "bg-ink text-canvas"
                : "border border-hairline bg-canvas text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
      {!hasAnalysis && noAnalysisReason && (
        <span className="ml-1 text-[11px] font-medium leading-snug text-muted-soft">
          no impact analysis — {noAnalysisReason}
        </span>
      )}
    </nav>
  );
}
