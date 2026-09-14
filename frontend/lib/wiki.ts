// Helpers for rendering OKF wiki markdown (see councilhound.okf): resolve
// {{metric:...}} markers against the live evaluation so wiki prose never
// carries stale numbers, and rewrite bundle-internal links for whatever page
// is hosting the content.
import type { ImpactMetric } from "@/lib/api";
import { fmtScalar } from "@/lib/format";

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
  const fmt = (x: number) => fmtScalar(x, m.unit);
  let out = `**${m.name}: ${fmt(m.value)}**`;
  if (m.low != null && m.high != null && !(m.low === m.value && m.high === m.value)) {
    out += ` _(range ${fmt(m.low)} – ${fmt(m.high)})_`;
  }
  return out;
}

/** Resolve wiki source into renderable markdown. `wikiBase` is where the
 * wiki's own pages live relative to the hosting page: "" on the wiki tab
 * itself (in-page anchors), "/development/<slug>" when embedding a single
 * page elsewhere. `pageHrefs` overrides the target for specific bundle pages
 * that live on their own route (e.g. documents → the Documents tab). */
export function resolveBody(
  body: string,
  metrics: Map<string, ImpactMetric>,
  entitySlug: string,
  officialSlug: string | null,
  wikiBase = "",
  pageHrefs: Record<string, string> = {},
): string {
  return body
    .replace(/<!--[\s\S]*?-->/g, "") // ownership notes are for editors, not readers
    // a bullet citing a metric the pipeline retired goes, not just its number
    .replace(/^.*\{\{metric:(?:net-annual-fiscal-impact-naive-per-capita-method|annual-service-cost-naive-per-capita-method|net-annual-fiscal-impact-range-across-both-cost-methods)\}\}.*\n?/gm, "")
    .replace(/\{\{metric:([a-z0-9-]+)\}\}/g, (_all, key: string) => {
      const m = metrics.get(key);
      return m ? fmtMetric(m) : `_metric ${key} unavailable_`;
    })
    .replace(/\{\{map:([a-z0-9-]+)\}\}/g, (_all, key: string) =>
      // meeting-derived projects have no analysis page to link to
      officialSlug
        ? `[maps on the analysis page](/development/${officialSlug}/analysis)`
        : `_map ${key} unavailable_`,
    )
    .replace(
      new RegExp(`\\]\\(/projects/${entitySlug}/([a-z0-9-]+)\\.md\\)`, "g"),
      (_all, page: string) => `](${pageHrefs[page] ?? `${wikiBase}#${page}`})`,
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
  documents: "Documents",
};
