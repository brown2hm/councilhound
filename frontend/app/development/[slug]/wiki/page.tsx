import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "@/components/Markdown";
import { api, formatDate, type ImpactMetric, type ProjectWiki } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Same normalization as councilhound.okf.bundle.slugify — metric marker
 * keys are the slugified metric name on both sides. */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function fmtMetric(m: ImpactMetric): string {
  const dollars = m.unit.startsWith("$");
  const fraction = m.unit === "fraction";
  const fmt = (x: number) => {
    if (fraction) return `${Math.round(x * 100)}%`;
    if (dollars && Math.abs(x) >= 1_000_000) return `$${(x / 1_000_000).toFixed(1)}M`;
    if (dollars && Math.abs(x) >= 10_000) return `$${Math.round(x / 1_000)}k`;
    if (dollars) return `$${Math.round(x).toLocaleString()}`;
    return Math.abs(x) >= 100
      ? Math.round(x).toLocaleString()
      : x.toLocaleString(undefined, { maximumFractionDigits: 1 });
  };
  let out = `**${m.name}: ${fmt(m.value)}**`;
  if (m.low != null && m.high != null && !(m.low === m.value && m.high === m.value)) {
    out += ` _(range ${fmt(m.low)} – ${fmt(m.high)})_`;
  }
  return out;
}

/** Resolve wiki source into renderable markdown: {{metric:...}} markers
 * become formatted live values (numbers never live in wiki prose), {{map:...}}
 * points at the analysis maps, and bundle-internal links become in-page
 * anchors. */
function resolveBody(
  body: string,
  metricsByKey: Map<string, ImpactMetric>,
  entitySlug: string,
  officialSlug: string,
): string {
  return body
    .replace(/<!--[\s\S]*?-->/g, "") // ownership notes are for editors, not readers
    .replace(/\{\{metric:([a-z0-9-]+)\}\}/g, (_all, key: string) => {
      const m = metricsByKey.get(key);
      return m ? fmtMetric(m) : `_metric ${key} unavailable_`;
    })
    .replace(
      /\{\{map:([a-z0-9-]+)\}\}/g,
      () => `[maps on the analysis page](/development/${officialSlug})`,
    )
    .replace(
      new RegExp(`\\]\\(/projects/${entitySlug}/([a-z0-9-]+)\\.md\\)`, "g"),
      (_all, page: string) => `](#${page})`,
    );
}

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
  const metricsByKey = new Map<string, ImpactMetric>();
  try {
    const evaluation = await api.developmentEvaluation(params.slug);
    for (const m of evaluation.metrics) metricsByKey.set(slugify(m.name), m);
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
              {resolveBody(p.body, metricsByKey, wiki.entity_slug, params.slug)}
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
