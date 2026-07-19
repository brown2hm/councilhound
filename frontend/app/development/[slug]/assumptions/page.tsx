import Link from "next/link";
import { notFound } from "next/navigation";
import AssumptionsLab from "@/components/AssumptionsLab";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AssumptionsPage({
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

  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-16 pt-8">
      <Link
        href={`/development/${params.slug}`}
        className="text-sm font-semibold text-muted hover:text-ink"
      >
        ← {evaluation.name} analysis
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Impact analysis · What if?
      </div>
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">
        Adjust the assumptions
      </h1>
      <p className="mb-6 max-w-[720px] text-[14px] leading-[1.6] text-body">
        Every estimate in this analysis rests on named assumptions with published
        ranges. If you have better local knowledge — vehicle ownership, household
        mix, tenant sales — move the sliders and see the estimates recompute
        instantly. Nothing here is saved or submitted.
      </p>

      <div className="mb-8 rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-[13px] leading-[1.55] text-tint-ochre-text">
        <span className="font-semibold">Same math, your inputs.</span> Sliders are
        bounded by each assumption&apos;s published sensitivity range, and adjusted
        values use the exact formulas of the pipeline — not an approximation. Travel
        and destination-choice parameters are excluded (they require a full model
        re-run) and are listed at the bottom left.
      </div>

      <AssumptionsLab
        assumptions={evaluation.assumptions}
        metrics={evaluation.metrics}
      />
    </div>
  );
}
