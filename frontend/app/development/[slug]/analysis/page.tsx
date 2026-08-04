import Link from "next/link";
import { redirect } from "next/navigation";
import AssumptionsLab from "@/components/AssumptionsLab";
import HeadlineMetrics from "@/components/HeadlineMetrics";
import ImpactMapClient from "@/components/ImpactMapClient";
import Markdown from "@/components/Markdown";
import { type ImpactProvenance } from "@/lib/api";
import { plainLanguageImpact } from "@/lib/format";
import { getEvaluation, getProject } from "../project";

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
    const project = await getProject(params.slug);
    if (!project.has_evaluation) throw new Error("no analysis");
    evaluation = await getEvaluation(params.slug);
  } catch {
    // no published analysis — the wiki tab is the project's landing view
    redirect(`/development/${params.slug}`);
  }

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
    <div>
      {facts.length > 0 && (
        <p className="mb-6 text-[13px] font-medium text-muted">{facts.join(" · ")}</p>
      )}

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
          <HeadlineMetrics metrics={headlines} assumptions={evaluation.assumptions} />
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
        <h2 className="mb-2 text-lg font-semibold">Summary</h2>
        <Markdown>{report.summary}</Markdown>
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

      {report.rest && (
        <section className="mb-8">
          <details className="rounded-2xl border border-hairline bg-canvas p-5">
            <summary className="cursor-pointer text-[15px] font-semibold">
              Full analysis
            </summary>
            <div className="mt-3">
              <Markdown>{report.rest}</Markdown>
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
