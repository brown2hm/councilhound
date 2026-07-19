import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "@/components/Markdown";
import { api, formatDate, type ImpactMetric, type ProjectWiki } from "@/lib/api";
import { metricsByKey, resolveBody } from "@/lib/wiki";

export const dynamic = "force-dynamic";

export default async function ProjectWikiPage({
  params,
}: {
  params: { slug: string };
}) {
  let wiki: ProjectWiki;
  try {
    wiki = await api.developmentWiki(params.slug);
  } catch {
    notFound();
  }
  let metrics = new Map<string, ImpactMetric>();
  try {
    const evaluation = await api.developmentEvaluation(params.slug);
    metrics = metricsByKey(evaluation.metrics);
  } catch {
    // no synthesized evaluation — metric markers render as unavailable
  }

  return (
    <div className="mx-auto max-w-[880px] px-8 pb-16 pt-8">
      <Link
        href={`/development/${params.slug}`}
        className="text-sm font-semibold text-muted hover:text-ink"
      >
        ← Impact analysis
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Project wiki · beta
      </div>
      <h1 className="mb-2 text-[32px] font-medium tracking-[-0.5px]">{wiki.name}</h1>
      <p className="mb-6 text-[13px] text-muted">
        A maintained knowledge base built from council meetings and official
        records — updated as new meetings land.
        {wiki.pushed_at && ` Last synced ${formatDate(wiki.pushed_at.slice(0, 10))}.`}
      </p>

      <nav className="mb-8 flex flex-wrap gap-2">
        {wiki.pages.map((p) => (
          <a
            key={p.page}
            href={`#${p.page}`}
            className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-semibold text-body hover:bg-strong"
          >
            {p.page.charAt(0).toUpperCase() + p.page.slice(1)}
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
              {p.page.charAt(0).toUpperCase() + p.page.slice(1)}
            </h2>
            {p.timestamp && (
              <span className="text-[12px] text-muted">
                through {formatDate(String(p.timestamp).slice(0, 10))}
              </span>
            )}
          </div>
          <div className="text-[14px] leading-[1.6]">
            <Markdown>
              {resolveBody(p.body, metrics, wiki.entity_slug, params.slug)}
            </Markdown>
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

      <p className="text-[12px] text-muted">
        Impact figures shown on this page resolve live from the current
        evaluation — wiki text never carries stale numbers.
      </p>
    </div>
  );
}
