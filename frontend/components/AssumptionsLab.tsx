"use client";

import { useMemo, useState } from "react";
import type { ImpactAssumption, ImpactMetric } from "@/lib/api";

/** Interactive assumption adjustment. Each adjustable metric ships an exact
 * power-law decomposition (metric.adjust); moving a slider re-evaluates
 *   value' = sum_t t.value x prod_k (adjusted[k]/baseline[k])^t.exps[k]
 * which reproduces what the pipeline itself would compute for these
 * assumptions. Network-model parameters (walk decay, mode shares) are not in
 * any term — changing those requires a full re-run — so they render locked. */

function recompute(m: ImpactMetric, baseline: Record<string, number>, adjusted: Record<string, number>): number {
  let total = 0;
  for (const t of m.adjust ?? []) {
    let factor = 1;
    for (const [key, e] of Object.entries(t.exps)) {
      const base = baseline[key];
      const now = adjusted[key] ?? base;
      if (base && now !== base) factor *= Math.pow(now / base, e);
    }
    total += t.value * factor;
  }
  return total;
}

function fmt(value: number, unit: string): string {
  const dollars = unit.startsWith("$");
  if (unit === "fraction") return `${Math.round(value * 100)}%`;
  if (dollars && Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (dollars && Math.abs(value) >= 10_000) return `$${Math.round(value / 1_000).toLocaleString()}k`;
  if (dollars) return `$${Math.round(value).toLocaleString()}`;
  if (Math.abs(value) >= 100) return Math.round(value).toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function sliderStep(a: ImpactAssumption): number {
  // Round via decimal string, not Math.log10/Math.pow: those aren't exactly
  // specified, so server and client can disagree in the last bit and break
  // hydration on the step attribute.
  const raw = (a.high - a.low) / 100;
  return raw > 0 ? Number(raw.toPrecision(1)) : raw;
}

const FRIENDLY: Record<string, string> = {
  occupancy_rate: "Occupancy rate",
  avg_hh_size_multifamily: "Household size (multifamily)",
  income_premium_new_construction: "New-construction income premium",
  ces_scale: "Spending-survey scaling",
  walk_trips_per_resident_day: "Walk trips per resident per day",
  sqft_per_office_job: "Sq ft per office job",
  sqft_per_retail_job: "Sq ft per retail job",
  commercial_value_per_sqft: "Commercial value per sq ft ($)",
  marginal_cost_factor: "Marginal cost factor",
  students_per_unit: "Students per unit",
  vehicles_per_household: "Vehicles per household",
  avg_vehicle_assessed_value: "Assessed value per vehicle ($)",
  retail_sales_per_sqft: "Retail sales per sq ft ($/yr)",
  beta_walk: "Walk-time decay (β)",
  walk_share_neighborhood: "Walk share — neighborhood trips",
  walk_share_comparison: "Walk share — comparison goods",
  walk_share_grocery_entertainment: "Walk share — grocery/entertainment",
  own_retail_sqft_per_equiv_poi: "Own-retail sq ft per equivalent business",
};

export default function AssumptionsLab({
  assumptions,
  metrics,
}: {
  assumptions: ImpactAssumption[];
  metrics: ImpactMetric[];
}) {
  const adjustable = useMemo(() => {
    const keys = new Set<string>();
    for (const m of metrics) for (const t of m.adjust ?? []) for (const k of Object.keys(t.exps)) keys.add(k);
    return keys;
  }, [metrics]);

  const baseline = useMemo(
    () => Object.fromEntries(assumptions.map((a) => [a.key, a.value])),
    [assumptions],
  );

  const [adjusted, setAdjusted] = useState<Record<string, number>>(baseline);
  const dirty = assumptions.some((a) => adjusted[a.key] !== a.value);

  const sliders = assumptions.filter((a) => adjustable.has(a.key));
  const locked = assumptions.filter((a) => !adjustable.has(a.key));

  const rows = metrics
    .filter((m) => (m.adjust ?? []).length > 0)
    .map((m) => ({ m, now: recompute(m, baseline, adjusted) }));
  const byModule = [
    { label: "Economic", rows: rows.filter((r) => r.m.module === "economic") },
    { label: "Fiscal", rows: rows.filter((r) => r.m.module === "fiscal") },
  ].filter((g) => g.rows.length > 0);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(320px,5fr)_minmax(380px,7fr)]">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Assumptions</h2>
          <button
            onClick={() => setAdjusted(baseline)}
            disabled={!dirty}
            className="rounded-full border border-hairline px-3 py-1 text-[12px] font-semibold text-body enabled:hover:bg-soft disabled:opacity-40"
          >
            Reset all
          </button>
        </div>
        <div className="space-y-4">
          {sliders.map((a) => {
            const now = adjusted[a.key] ?? a.value;
            const changed = now !== a.value;
            return (
              <div key={a.key} className="rounded-2xl border border-hairline bg-canvas p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-[13px] font-semibold">{FRIENDLY[a.key] ?? a.key}</div>
                  <div className="whitespace-nowrap text-[13px] tabular-nums">
                    <span className={changed ? "font-semibold" : ""}>
                      {now.toLocaleString(undefined, { maximumFractionDigits: 3 })}
                    </span>
                    {changed && (
                      <button
                        onClick={() => setAdjusted((s) => ({ ...s, [a.key]: a.value }))}
                        className="ml-2 text-[11px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                      >
                        reset
                      </button>
                    )}
                  </div>
                </div>
                <input
                  type="range"
                  min={a.low}
                  max={a.high}
                  step={sliderStep(a)}
                  value={now}
                  onChange={(e) => setAdjusted((s) => ({ ...s, [a.key]: Number(e.target.value) }))}
                  className="mt-2 w-full accent-ink"
                  aria-label={FRIENDLY[a.key] ?? a.key}
                />
                <div className="flex justify-between text-[11px] tabular-nums text-muted">
                  <span>{a.low.toLocaleString()}</span>
                  <span>published: {a.value.toLocaleString()}</span>
                  <span>{a.high.toLocaleString()}</span>
                </div>
                <p className="mt-1.5 text-[12px] leading-snug text-muted">{a.rationale}</p>
              </div>
            );
          })}
        </div>

        {locked.length > 0 && (
          <div className="mt-6">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-[1px] text-muted">
              Requires a full model re-run
            </h3>
            <p className="mb-3 text-[12px] leading-snug text-muted">
              These parameters sit inside the travel/destination-choice model, so their
              effect on the results is not a simple rescaling — they cannot be adjusted
              live.
            </p>
            <div className="space-y-2">
              {locked.map((a) => (
                <div key={a.key} className="rounded-xl border border-hairline bg-soft p-3 opacity-70">
                  <div className="flex items-baseline justify-between text-[13px]">
                    <span className="font-semibold">{FRIENDLY[a.key] ?? a.key}</span>
                    <span className="tabular-nums text-muted">
                      {a.value.toLocaleString()} ({a.low.toLocaleString()}–{a.high.toLocaleString()})
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Recomputed estimates</h2>
        {byModule.map((group) => (
          <div key={group.label} className="mb-5">
            <h3 className="mb-1.5 text-sm font-semibold uppercase tracking-[1px] text-muted">
              {group.label}
            </h3>
            <div className="overflow-x-auto rounded-2xl border border-hairline">
              <table className="w-full text-[13px]">
                <thead className="bg-soft text-left text-muted">
                  <tr>
                    <th className="px-4 py-2 font-semibold">Metric</th>
                    <th className="px-4 py-2 text-right font-semibold">Published</th>
                    <th className="px-4 py-2 text-right font-semibold">Adjusted</th>
                    <th className="px-4 py-2 text-right font-semibold">Δ</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline-soft">
                  {group.rows.map(({ m, now }) => {
                    const delta = m.value !== 0 ? ((now - m.value) / Math.abs(m.value)) * 100 : 0;
                    const changed = Math.abs(delta) >= 0.05;
                    return (
                      <tr key={m.name} className="align-top">
                        <td className="px-4 py-2 leading-snug">
                          {m.name}
                          {m.headline && (
                            <span className="ml-1.5 rounded-full bg-strong px-1.5 py-0.5 text-[10px] font-semibold text-body">
                              headline
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-muted">
                          {fmt(m.value, m.unit)}
                        </td>
                        <td className={`whitespace-nowrap px-4 py-2 text-right tabular-nums ${changed ? "font-semibold" : ""}`}>
                          {fmt(now, m.unit)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-muted">
                          {changed ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        <p className="text-[12px] leading-snug text-muted">
          Adjusted values are exact recomputations of the model&apos;s central estimates
          for the assumptions above — the same arithmetic the pipeline runs, evaluated
          in your browser. Published ranges, maps, and the narrative report are not
          recomputed here.
        </p>
      </div>
    </div>
  );
}
