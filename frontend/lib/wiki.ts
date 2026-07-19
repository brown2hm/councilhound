// Helpers for rendering OKF wiki markdown (see councilhound.okf): resolve
// {{metric:...}} markers against the live evaluation so wiki prose never
// carries stale numbers, and rewrite bundle-internal links for whatever page
// is hosting the content.
import type { ImpactMetric } from "@/lib/api";

/** Same normalization as councilhound.okf.bundle.slugify — metric marker
 * keys are the slugified metric name on both sides. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function metricsByKey(metrics: ImpactMetric[]): Map<string, ImpactMetric> {
  return new Map(metrics.map((m) => [slugify(m.name), m]));
}

export function fmtMetric(m: ImpactMetric): string {
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

/** Resolve wiki source into renderable markdown. `wikiBase` is where the
 * wiki's own pages live relative to the hosting page: "" on the wiki page
 * itself (in-page anchors), "/development/<slug>/wiki" when embedding a
 * single page elsewhere. */
export function resolveBody(
  body: string,
  metrics: Map<string, ImpactMetric>,
  entitySlug: string,
  officialSlug: string,
  wikiBase = "",
): string {
  return body
    .replace(/<!--[\s\S]*?-->/g, "") // ownership notes are for editors, not readers
    .replace(/\{\{metric:([a-z0-9-]+)\}\}/g, (_all, key: string) => {
      const m = metrics.get(key);
      return m ? fmtMetric(m) : `_metric ${key} unavailable_`;
    })
    .replace(
      /\{\{map:([a-z0-9-]+)\}\}/g,
      () => `[maps on the analysis page](/development/${officialSlug})`,
    )
    .replace(
      new RegExp(`\\]\\(/projects/${entitySlug}/([a-z0-9-]+)\\.md\\)`, "g"),
      (_all, page: string) => `](${wikiBase}#${page})`,
    );
}

/** Drop one "## Heading" section (through the next h2 or EOF) — used to
 * strip the overview's bundle-navigation section where the hosting page
 * provides its own links. */
export function stripSection(body: string, heading: string): string {
  const re = new RegExp(`^## ${heading}\\s*$[\\s\\S]*?(?=^## |(?![\\s\\S]))`, "m");
  return body.replace(re, "").trim();
}

export const WIKI_PAGE_LABELS: Record<string, string> = {
  overview: "Overview",
  history: "Meeting history",
  positions: "Positions & open questions",
  impact: "Impact analysis",
};
