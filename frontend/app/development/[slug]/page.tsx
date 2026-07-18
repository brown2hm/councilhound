import Link from "next/link";
import { notFound } from "next/navigation";
import ImpactMapClient from "@/components/ImpactMapClient";
import Markdown from "@/components/Markdown";
import { api, type ImpactMetric, type ImpactProvenance } from "@/lib/api";

export const dynamic = "force-dynamic";

function fmtValue(m: ImpactMetric): string {
  const dollars = m.unit.startsWith("$");
  const fraction = m.unit === "fraction";
  const fmt = (x: number) => {
    if (fraction) return `${Math.round(x * 100)}%`;
    if (dollars && Math.abs(x) >= 1_000_000) return `$${(x / 1_000_000).toFixed(1)}M`;
    if (dollars && Math.abs(x) >= 10_000) return `$${Math.round(x / 1_000)}k`;
    if (dollars) return `$${Math.round(x).toLocaleString()}`;
    return Math.abs(x) >= 100 ? Math.round(x).toLocaleString() : x.toLocaleString(undefined, { maximumFractionDigits: 1 });
  };
  return fmt(m.value);
}

function fmtRange(m: ImpactMetric): string | null {
  if (m.low == null || m.high == null || (m.low === m.value && m.high === m.value)) return null;
  const fraction = m.unit === "fraction";
  const dollars = m.unit.startsWith("$");
  const fmt = (x: number) => {
    if (fraction) return `${Math.round(x * 100)}%`;
    if (dollars && Math.abs(x) >= 1_000_000) return `$${(x / 1_000_000).toFixed(1)}M`;
    if (dollars && Math.abs(x) >= 10_000) return `$${Math.round(x / 1_000)}k`;
    if (dollars) return `$${Math.round(x).toLocaleString()}`;
    return Math.round(x).toLocaleString();
  };
  return `${fmt(m.low)} – ${fmt(m.high)}`;
}

function unitLabel(unit: string): string {
  if (unit === "fraction") return "";
  return unit.replace("$/yr", "per year").replace("$/acre", "per acre").replace("$", "");
}

export default async function DevelopmentAnalysisPage({
  params,
}: {
  params: { slug: string };
}) {
  let evaluation;
  try {
    evaluation = await api.developmentEvaluation(params.slug);
  } catch {
    notFound();
  }

  const headlines = evaluation.metrics.filter((m) => m.headline);
  const proposed = evaluation.spec.proposed ?? {};
  const facts = [
    proposed.units != null && `${proposed.units} units`,
    proposed.retail_sqft != null && `${Number(proposed.retail_sqft).toLocaleString()} sq ft retail`,
    proposed.stories != null && `${proposed.stories} stories`,
    proposed.acres != null && `${proposed.acres} acres`,
  ].filter(Boolean);

  return (
    <div className="mx-auto max-w-[860px] px-8 pb-16 pt-8">
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
        in the appendices below.
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
        </section>
      )}

      {Object.keys(evaluation.map_layers).length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Where the effects land</h2>
          <ImpactMapClient layers={evaluation.map_layers} />
          <p className="mt-2 text-[12px] text-muted">
            Heat: projected annual spending captured, modeled per business location.
            Lines: the new residents&apos; modeled walk trips routed over nearby streets.
            Circles (toggleable): named shopping areas rolled up for reporting, sized by
            dollars.
          </p>
        </section>
      )}

      <section className="mb-8">
        <Markdown>{evaluation.report_markdown}</Markdown>
      </section>

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
        <h2 className="mb-2 text-lg font-semibold">Assumptions &amp; sensitivities</h2>
        <div className="overflow-x-auto rounded-2xl border border-hairline">
          <table className="w-full text-[13px]">
            <thead className="bg-soft text-left text-muted">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Assumption</th>
                <th className="px-4 py-2.5 font-semibold">Value</th>
                <th className="px-4 py-2.5 font-semibold">Range</th>
                <th className="px-4 py-2.5 font-semibold">Why</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline-soft">
              {evaluation.assumptions.map((a) => (
                <tr key={a.key} className="align-top">
                  <td className="px-4 py-2.5 font-mono text-[12px]">{a.key}</td>
                  <td className="px-4 py-2.5">{a.value}</td>
                  <td className="px-4 py-2.5 text-muted">
                    {a.low} – {a.high}
                  </td>
                  <td className="px-4 py-2.5 leading-snug text-body">{a.rationale}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

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
