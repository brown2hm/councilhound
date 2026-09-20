import Link from "next/link";
import { cache } from "react";
import Markdown from "@/components/Markdown";
import WikiTrustBadges from "@/components/WikiTrust";
import { api, formatDate } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";
import { resolveBody, WIKI_PAGE_LABELS } from "@/lib/wiki";

export const dynamic = "force-dynamic";

// The sibling route under /development covers projects with an official city
// record. Meeting-derived projects have no such record and so no /development
// URL — without this page their wiki is served by the API but reachable
// nowhere in the UI.
const getWiki = cache((slug: string) => api.entityWiki(slug));

export async function generateMetadata({ params }: { params: { slug: string } }) {
  const wiki = await requireRecord(getWiki(params.slug));
  return {
    title: `${wiki.name} — wiki`,
    description: `A maintained knowledge base on ${wiki.name}: overview, meeting history, and member positions, built from City of Fairfax meeting records.`,
  };
}

export default async function TopicWikiPage({
  params,
}: {
  params: { slug: string };
}) {
  const wiki = await requireRecord(getWiki(params.slug));

  return (
    <div className="mx-auto max-w-[880px] px-4 pb-16 pt-8 sm:px-8">
      <Link
        href={`/topics/${params.slug}`}
        className="text-sm font-semibold text-muted hover:text-ink"
      >
        ← {wiki.name}
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Wiki · beta
      </div>
      <h1 className="mb-2 text-[32px] font-medium tracking-[-0.5px]">{wiki.name}</h1>
      <p className="mb-6 text-[13px] text-muted">
        A maintained knowledge base built from council and commission meetings —
        updated as new meetings land.
        {wiki.pushed_at && ` Last synced ${formatDate(wiki.pushed_at.slice(0, 10))}.`}
      </p>

      <nav className="mb-8 flex flex-wrap gap-2">
        {wiki.pages.map((p) => (
          <a
            key={p.page}
            href={`#${p.page}`}
            className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-semibold text-body hover:bg-strong"
          >
            {WIKI_PAGE_LABELS[p.page] ?? p.page}
          </a>
        ))}
      </nav>

      {wiki.pages.map((p) => (
        <section
          key={p.page}
          id={p.page}
          className="mb-6 scroll-mt-6 rounded-2xl border border-hairline bg-canvas p-6"
        >
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold">
              {WIKI_PAGE_LABELS[p.page] ?? p.page}
            </h2>
            {p.timestamp && (
              <span className="text-[12px] text-muted">
                through {formatDate(String(p.timestamp).slice(0, 10))}
              </span>
            )}
          </div>
          <div className="mb-3">
            <WikiTrustBadges trust={p.trust} />
          </div>
          <div className="text-[14px] leading-[1.6]">
            {/* no impact page without a city record, so no metrics to resolve */}
            <Markdown>{resolveBody(p.body, new Map(), wiki.entity_slug, null)}</Markdown>
          </div>
        </section>
      ))}

      {wiki.log && (
        <details className="mb-8 rounded-2xl border border-hairline bg-soft p-5">
          <summary className="cursor-pointer text-[14px] font-semibold">
            Page history
          </summary>
          <div className="mt-3 text-[13px] leading-[1.6]">
            <Markdown>{wiki.log}</Markdown>
          </div>
        </details>
      )}
    </div>
  );
}
