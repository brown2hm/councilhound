import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import AssumptionsLab from "@/components/AssumptionsLab";
import ImpactMapClient from "@/components/ImpactMapClient";
import Markdown from "@/components/Markdown";
import {
  api,
  formatDate,
  type ImpactMetric,
  type ImpactProvenance,
  type ProjectWiki,
} from "@/lib/api";
import { fmtScalar, plainLanguageImpact } from "@/lib/format";
import { metricsByKey, resolveBody, stripSection, WIKI_PAGE_LABELS } from "@/lib/wiki";

export const dynamic = "force-dynamic";

/** Split the synthesized report into the executive summary (shown inline)
 * and the remaining sections (collapsed). Falls back to the whole report
 * when the expected "## Executive summary" heading is missing. */
function splitReport(markdown: string): { summary: string; rest: string | null } {
  const sections = markdown.split(/\n(?=## )/);
  const summaryIdx = sections.findIndex((s) => /^## Executive summary/i.test(s));
  if (summaryIdx === -1) return { summary: markdown, rest: null };
  const summary = sections[summaryIdx].replace(/^## Executive summary\s*/i, "");
  const rest = sections.filter((_, i) => i !== summaryIdx && i > 0).join("\n");
  return { summary, rest: rest.trim() ? rest : null };
}

function fmtValue(m: ImpactMetric): string {
  return fmtScalar(m.value, m.unit);
}

function fmtRange(m: ImpactMetric): string | null {
  if (m.low == null || m.high == null || (m.low === m.value && m.high === m.value)) return null;
  return `${fmtScalar(m.low, m.unit)} – ${fmtScalar(m.high, m.unit)}`;
}

function unitLabel(unit: string): string {
  if (unit === "fraction") return "";
  return unit.replace("$/yr", "per year").replace("$/acre", "per acre").replace("$", "");
}

const getEvaluation = cache((slug: string) => api.developmentEvaluation(slug));

export async function generateMetadata({ params }: { params: { slug: string } }) {
  try {
    const evaluation = await getEvaluation(params.slug);
    return {
      title: `${evaluation.name} — impact analysis`,
      description: `Screening estimates of the community impact of ${evaluation.name} in the City of Fairfax, with named assumptions and sensitivity ranges.`,
    };
  } catch {
    return {};
  }
}

export default async function DevelopmentAnalysisPage({
  params,
}: {
  params: { slug: string };
}) {
  let evaluation;
  try {
    evaluation = await getEvaluation(params.slug);
  } catch {
    notFound();
  }
  // the wiki's overview page replaces the report's executive summary as the
  // narrative when one exists (the full report stays in "Full analysis")
  let wiki: ProjectWiki | null = null;
  if (evaluation.has_wiki) {
    try {
      wiki = await api.developmentWiki(params.slug);
    } catch {
      // wiki flagged but unavailable — fall back to the report summary
    }
  }
  const overview = wiki?.pages.find((p) => p.page === "overview") ?? null;
  const wikiBase = `/development/${params.slug}/wiki`;

  const headlines = evaluation.metrics.filter((m) => m.headline);
  const report = splitReport(evaluation.report_markdown || "");
  const proposed = evaluation.spec.proposed ?? {};
  const facts = [
    proposed.units != null && `${proposed.units} units`,
    proposed.retail_sqft != null && `${Number(proposed.retail_sqft).toLocaleString()} sq ft retail`,
    proposed.stories != null && `${proposed.stories} stories`,
    proposed.acres != null && `${proposed.acres} acres`,
  ].filter(Boolean);

  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-16 pt-8">
      <Link href="/development" className="text-sm font-semibold text-muted hover:text-ink">
        ← Development directory
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Impact analysis
      </div>
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">{evaluation.name}</h1>
        {evaluation.official_status && (
          <span className="rounded-full bg-strong px-3 py-1 text-xs font-semibold text-body">
            {evaluation.official_status}
          </span>
        )}
      </div>
      <p className="mb-6 text-[13px] text-muted">
        {facts.join(" · ")}
        {facts.length > 0 && " · "}
        {evaluation.has_wiki && (
          <>
            <Link
              href={`/development/${evaluation.slug}/wiki`}
              className="font-semibold underline underline-offset-2 hover:text-ink"
            >
              project wiki
            </Link>
            {" · "}
          </>
        )}
        {evaluation.entity_slug && (
          <>
            <Link
              href={`/topics/${evaluation.entity_slug}`}
              className="font-semibold underline underline-offset-2 hover:text-ink"
            >
              topic history
            </Link>
            {" · "}
          </>
        )}
        <a href={evaluation.detail_url} target="_blank" className="font-semibold underline underline-offset-2 hover:text-ink">
          city record ↗
        </a>
      </p>

      <div className="mb-8 rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-[13px] leading-[1.55] text-tint-ochre-text">
        <span className="font-semibold">Screening estimates.</span> These figures rank
        likely magnitudes with stated assumptions and ranges — they are decision-support
        context, not predictions. Every number traces to a source or a named assumption
        in the appendices below. Formulas, citations, and limitations:{" "}
        <a
          href="/impact-methodology.pdf"
          target="_blank"
          className="font-semibold underline underline-offset-2"
        >
          methodology report (PDF)
        </a>
        .
      </div>

      {headlines.length > 0 && (
        <section className="mb-8">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {headlines.map((m) => (
              <div key={m.name} className="rounded-2xl border border-hairline bg-canvas p-4">
                <div className="text-[22px] font-semibold tracking-[-0.3px]">{fmtValue(m)}</div>
                {fmtRange(m) && (
                  <div className="text-[12px] font-medium text-muted">range {fmtRange(m)}</div>
                )}
                <div className="mt-1 text-[12px] leading-snug text-muted">
                  {m.name}
                  {unitLabel(m.unit) && ` (${unitLabel(m.unit).trim()})`}
                </div>
              </div>
            ))}
          </div>
          {plainLanguageImpact(evaluation.metrics) && (
            <p className="mt-4 max-w-[820px] rounded-2xl bg-soft p-4 px-5 text-[14px] leading-[1.6] text-body">
              {plainLanguageImpact(evaluation.metrics)}
            </p>
          )}
        </section>
      )}

      {Object.keys(evaluation.map_layers).length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Where the effects land</h2>
          <ImpactMapClient layers={evaluation.map_layers} />
          <p className="mt-2 text-[12px] text-muted">
            {"capture_points" in evaluation.map_layers ||
            "capture_clusters" in evaluation.map_layers ? (
              <>
                The economic map shows total captured spending by business location and
                named reporting clusters. The walk map uses a tighter extent around
                walk-arriving capture and the street segments assigned new resident walk
                trips; the bike map (when present) shows bike-arriving capture across
                the city — bikes reach farther, so it spreads wider and thinner. Dollar
                heatmaps are clipped to CR (Commercial Retail) zoning, and each map is
                scaled to its own data, so colors are not comparable across maps.
              </>
            ) : "bike_corridor" in evaluation.map_layers ? (
              <>
                The corridor map shows the proposed facility, the businesses along it
                with their estimated new bike spending, and the residents the corridor
                newly serves (weighted by bike travel time). Each heatmap is scaled to
                its own data and the legend states the dollars.
              </>
            ) : (
              <>
                The trail map shows the trail line, its access points, businesses within
                walking reach of them with estimated trail-user spending, and the dashed
                band of parcels close enough to plausibly capitalize a property premium.
              </>
            )}
          </p>
        </section>
      )}

      <section className="mb-8">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Summary</h2>
          {overview?.timestamp && (
            <span className="text-[12px] text-muted">
              from the project wiki · through{" "}
              {formatDate(String(overview.timestamp).slice(0, 10))}
            </span>
          )}
        </div>
        {overview && wiki ? (
          <>
            <Markdown>
              {resolveBody(
                stripSection(overview.body, "In this wiki"),
                metricsByKey(evaluation.metrics),
                wiki.entity_slug,
                params.slug,
                wikiBase,
              )}
            </Markdown>
            <div className="mt-4 flex flex-wrap gap-2">
              {wiki.pages
                .filter((p) => p.page !== "overview")
                .map((p) => (
                  <Link
                    key={p.page}
                    href={`${wikiBase}#${p.page}`}
                    className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-semibold text-body hover:bg-strong"
                  >
                    {WIKI_PAGE_LABELS[p.page] ?? p.title}
                  </Link>
                ))}
              <Link
                href={wikiBase}
                className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-semibold text-body hover:bg-strong"
              >
                Full wiki →
              </Link>
            </div>
          </>
        ) : (
          <Markdown>{report.summary}</Markdown>
        )}
        {evaluation.metrics.length > 0 && (
          <Link
            href="/development/methods"
            className="mt-4 inline-flex text-[13px] font-semibold underline underline-offset-4 hover:text-muted"
          >
            View metric methods and calculations →
          </Link>
        )}
      </section>

      <section className="mb-8">
        <h2 className="mb-1 text-lg font-semibold">Adjust the assumptions</h2>
        <p className="mb-4 max-w-[760px] text-[13px] leading-[1.55] text-muted">
          Every estimate above rests on named assumptions with published ranges. If you
          have better local knowledge, move the sliders — adjusted values use the exact
          formulas of the pipeline, bounded by each assumption&apos;s sensitivity range.
          Travel and destination-choice parameters are excluded (they require a full
          model re-run). Nothing is saved or submitted.
        </p>
        <AssumptionsLab
          assumptions={evaluation.assumptions}
          metrics={evaluation.metrics}
        />
      </section>

      {(overview ? evaluation.report_markdown : report.rest) && (
        <section className="mb-8">
          <details className="rounded-2xl border border-hairline bg-canvas p-5">
            <summary className="cursor-pointer text-[15px] font-semibold">
              Full analysis
            </summary>
            <div className="mt-3">
              {/* with the wiki overview as the page summary, the report's own
                  executive summary lives here instead of disappearing */}
              <Markdown>{overview ? evaluation.report_markdown : report.rest!}</Markdown>
            </div>
          </details>
        </section>
      )}

      {evaluation.narrative_notes.length > 0 && (
        <section className="mb-8 rounded-2xl border border-hairline bg-soft p-5">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-[1px] text-muted">
            Method notes &amp; caveats
          </h2>
          <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-[1.55] text-body">
            {evaluation.narrative_notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-semibold">Data sources</h2>
        <ul className="space-y-1.5 text-[13px] leading-[1.55]">
          {evaluation.sources.map((s: ImpactProvenance, i) => (
            <li key={i}>
              {s.url ? (
                <a href={s.url} target="_blank" className="font-semibold underline underline-offset-2 hover:text-ink">
                  {s.source_name}
                </a>
              ) : (
                <span className="font-semibold">{s.source_name}</span>
              )}
              <span className="text-muted"> · {s.vintage}</span>
              {s.notes && <span className="text-muted"> · {s.notes}</span>}
            </li>
          ))}
        </ul>
      </section>

      <p className="text-[12px] text-muted">
        Computed {evaluation.synthesized_at ? new Date(evaluation.synthesized_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : ""}
        {evaluation.report_model && ` · narrative by ${evaluation.report_model} over deterministic model output`}
        {evaluation.report_prompt_version && ` (${evaluation.report_prompt_version})`}
      </p>
    </div>
  );
}
