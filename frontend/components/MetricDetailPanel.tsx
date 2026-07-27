"use client";

import { useEffect, useMemo } from "react";
import MetricFormula from "@/components/MetricFormula";
import type { ImpactAssumption, ImpactMetric, ImpactProvenance } from "@/lib/api";
import { labelFor } from "@/lib/assumptions";
import { fmtScalar } from "@/lib/format";
import {
  composition,
  lockedAssumptions,
  sensitivity,
  type CompositionGroup,
} from "@/lib/metric-detail";

const MODULE_LABELS: Record<string, string> = {
  economic: "Economic",
  fiscal: "Fiscal",
  bike_lane: "Bike lane",
  trail: "Trail",
};

function fmt(value: number, unit: string): string {
  return fmtScalar(value, unit, 2);
}

/** Signed amount with an explicit leading + or − so a ledger row never reads
 * ambiguously (fmtScalar already renders U+2212 for negatives). */
function fmtSigned(value: number, unit: string): string {
  const s = fmt(value, unit);
  return value > 0 ? `+${s}` : s;
}

/** Primary line: what the piece is. Falls back to the driver signature for
 * evaluations computed before terms carried labels. */
function groupTitle(g: CompositionGroup): string {
  if (g.label) return g.label;
  return g.driverLabel ? `Scales with ${g.driverLabel}` : "Fixed amount";
}

/** Secondary line: what rescales it (only when the row already has a name). */
function groupDrivers(g: CompositionGroup): string | null {
  if (!g.label) return null;
  return g.driverLabel ? `moves with ${g.driverLabel}` : "fixed — no assumption rescales it";
}

export default function MetricDetailPanel({
  metric,
  assumptions,
  onClose,
}: {
  metric: ImpactMetric;
  assumptions: ImpactAssumption[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  const comp = useMemo(() => composition(metric), [metric]);
  const drivers = useMemo(() => sensitivity(metric, assumptions), [metric, assumptions]);
  const locked = useMemo(() => lockedAssumptions(metric, assumptions), [metric, assumptions]);
  const named = useMemo(
    () => assumptions.filter((a) => metric.assumptions.includes(a.key)),
    [assumptions, metric],
  );

  const ledgerMax = comp
    ? Math.max(...[...comp.adds, ...comp.subtracts].map((g) => Math.abs(g.value)), 1)
    : 1;
  // a single group is just the headline number restated — the ledger only
  // earns its space once there are distinct pieces to compare
  const groupCount = comp ? comp.adds.length + comp.subtracts.length : 0;
  const showLedger = comp !== null && groupCount > 1;
  const termCount = (metric.adjust ?? []).length;
  const driverMax = drivers.length ? Math.max(...drivers.map((d) => d.swing), 1) : 1;
  const hasRange =
    metric.low != null && metric.high != null &&
    !(metric.low === metric.value && metric.high === metric.value);

  return (
    <div className="fixed inset-0 z-[1000]">
      <button
        aria-label="Close details"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-ink/20 backdrop-blur-[1px]"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="metric-detail-title"
        className="absolute right-0 top-0 flex h-full w-full max-w-[560px] flex-col border-l border-hairline bg-canvas shadow-2xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-hairline px-6 py-4">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="rounded-full bg-strong px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.5px] text-body">
                {MODULE_LABELS[metric.module] ?? metric.module}
              </span>
              <span className="text-[11px] font-semibold uppercase tracking-[1px] text-muted">
                How this number is built
              </span>
            </div>
            <h2 id="metric-detail-title" className="text-[15px] font-semibold leading-snug">
              {metric.name}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 shrink-0 rounded-full border border-hairline px-2.5 py-1 text-[13px] font-semibold text-muted hover:bg-soft hover:text-ink"
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-6">
            <div className="text-[30px] font-semibold tracking-[-0.5px]">
              {fmtScalar(metric.value, metric.unit)}
            </div>
            {hasRange && (
              <div className="text-[12px] font-medium text-muted">
                range {fmtScalar(metric.low!, metric.unit)} – {fmtScalar(metric.high!, metric.unit)}
                <span className="text-muted-soft"> · from the full model, not the sliders</span>
              </div>
            )}
          </div>

          {showLedger && comp && (
            <section className="mb-7">
              <h3 className="mb-1 text-sm font-semibold uppercase tracking-[1px] text-muted">
                {comp.mixed ? "What adds and what subtracts" : "What it adds up from"}
              </h3>
              <p className="mb-3 text-[12px] leading-snug text-muted">
                {comp.mixed
                  ? "This figure is a net: the pieces below add to and subtract from each other, and they sum exactly to the published number."
                  : "Every piece below contributes in the same direction, summing exactly to the published number."}
              </p>

              <div className="rounded-2xl border border-hairline bg-canvas p-4">
                <LedgerSide
                  title="Adds"
                  groups={comp.adds}
                  total={comp.addsTotal}
                  unit={metric.unit}
                  max={ledgerMax}
                  positive
                />
                {comp.subtracts.length > 0 && (
                  <div className="mt-4">
                    <LedgerSide
                      title="Subtracts"
                      groups={comp.subtracts}
                      total={comp.subtractsTotal}
                      unit={metric.unit}
                      max={ledgerMax}
                      positive={false}
                    />
                  </div>
                )}
                <div className="mt-4 flex items-baseline justify-between border-t-2 border-ink/15 pt-3">
                  <span className="text-[13px] font-semibold">Net</span>
                  <span className="text-[15px] font-semibold tabular-nums">
                    {fmt(comp.net, metric.unit)}
                  </span>
                </div>
              </div>
            </section>
          )}

          {drivers.length > 0 && (
            <section className="mb-7">
              <h3 className="mb-1 text-sm font-semibold uppercase tracking-[1px] text-muted">
                What moves it most
              </h3>
              <p className="mb-3 text-[12px] leading-snug text-muted">
                {!showLedger && termCount > 1 && (
                  <>
                    Built from {termCount} components that all move together.{" "}
                  </>
                )}
                Each assumption swept across its published range on its own, everything
                else held at its published value — the same arithmetic the sliders use.
              </p>
              <div className="space-y-3">
                {drivers.map((d) => {
                  const lo = Math.min(d.atLow, d.atHigh);
                  const hi = Math.max(d.atLow, d.atHigh);
                  return (
                    <div key={d.key}>
                      <div className="flex items-baseline justify-between gap-3 text-[13px]">
                        <span className="font-semibold leading-snug">{d.label}</span>
                        <span className="whitespace-nowrap tabular-nums text-muted">
                          {fmt(lo, metric.unit)} – {fmt(hi, metric.unit)}
                        </span>
                      </div>
                      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-strong">
                        <div
                          className="h-full rounded-full bg-teal"
                          style={{ width: `${Math.max(2, (d.swing / driverMax) * 100)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          <section className="mb-7">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-[1px] text-muted">
              Formula
            </h3>
            <div className="rounded-2xl border border-hairline bg-soft p-4">
              <MetricFormula
                metric={{
                  name: metric.name,
                  description: "",
                  method: metric.method,
                  assumptions: metric.assumptions,
                }}
              />
            </div>
          </section>

          {named.length > 0 && (
            <section className="mb-7">
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-[1px] text-muted">
                Assumptions behind it
              </h3>
              <div className="space-y-2.5">
                {named.map((a) => (
                  <AssumptionCard
                    key={a.key}
                    assumption={a}
                    locked={locked.some((l) => l.key === a.key)}
                  />
                ))}
              </div>
            </section>
          )}

          {metric.provenance.length > 0 && (
            <section className="mb-7">
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-[1px] text-muted">
                Sources
              </h3>
              <ul className="space-y-1.5 text-[12px] leading-[1.5]">
                {metric.provenance.map((p: ImpactProvenance, i) => (
                  <li key={i}>
                    {p.url ? (
                      <a
                        href={p.url}
                        target="_blank"
                        className="font-semibold underline underline-offset-2 hover:text-ink"
                      >
                        {p.source_name}
                      </a>
                    ) : (
                      <span className="font-semibold">{p.source_name}</span>
                    )}
                    {p.vintage && <span className="text-muted"> · {p.vintage}</span>}
                    {p.notes && <span className="text-muted"> · {p.notes}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!comp && (
            <p className="rounded-2xl bg-soft p-4 text-[12px] leading-snug text-muted">
              This metric has no live decomposition: it comes out of the travel and
              destination-choice model, where the inputs do not rescale the result
              arithmetically. Changing those parameters requires a full model re-run.
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}

function LedgerSide({
  title,
  groups,
  total,
  unit,
  max,
  positive,
}: {
  title: string;
  groups: CompositionGroup[];
  total: number;
  unit: string;
  max: number;
  positive: boolean;
}) {
  const bar = positive ? "bg-mint" : "bg-tint-coral";
  const chip = positive
    ? "bg-tint-mint text-tint-mint-text"
    : "bg-tint-coral text-tint-coral-text";
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.5px] ${chip}`}>
          {title}
        </span>
        <span className="text-[13px] font-semibold tabular-nums">
          {fmtSigned(total, unit)}
        </span>
      </div>
      <div className="space-y-2">
        {groups.map((g, i) => (
          <div key={i}>
            <div className="flex items-baseline justify-between gap-3 text-[12px]">
              <span className="leading-snug text-body">
                <span className="font-semibold">{groupTitle(g)}</span>
                {g.terms > 1 && (
                  <span className="text-muted"> · {g.terms} components</span>
                )}
                {groupDrivers(g) && (
                  <span className="block text-[11px] text-muted-soft">
                    {groupDrivers(g)}
                  </span>
                )}
              </span>
              <span className="whitespace-nowrap tabular-nums text-body">
                {fmtSigned(g.value, unit)}
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-hairline-soft">
              <div
                className={`h-full rounded-full ${bar}`}
                style={{ width: `${Math.max(2, (Math.abs(g.value) / max) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssumptionCard({
  assumption: a,
  locked,
}: {
  assumption: ImpactAssumption;
  locked: boolean;
}) {
  const basis = typeof a.basis === "string" ? a.basis : a.basis.source_name;
  const basisUrl = typeof a.basis === "string" ? null : a.basis.url;
  return (
    <div className="rounded-xl border border-hairline bg-canvas p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold leading-snug">{labelFor(a.key)}</span>
        <span className="whitespace-nowrap text-[12px] tabular-nums text-muted">
          {a.value.toLocaleString(undefined, { maximumFractionDigits: 3 })}
          <span className="text-muted-soft">
            {" "}
            ({a.low.toLocaleString(undefined, { maximumFractionDigits: 3 })}–
            {a.high.toLocaleString(undefined, { maximumFractionDigits: 3 })})
          </span>
        </span>
      </div>
      <p className="mt-1 text-[12px] leading-snug text-muted">{a.rationale}</p>
      {basis && (
        <p className="mt-1 text-[11px] leading-snug text-muted-soft">
          Basis:{" "}
          {basisUrl ? (
            <a href={basisUrl} target="_blank" className="underline underline-offset-2">
              {basis}
            </a>
          ) : (
            basis
          )}
        </p>
      )}
      {locked && (
        <p className="mt-1.5 text-[11px] font-semibold text-muted">
          Requires a full model re-run — not slider-adjustable
        </p>
      )}
    </div>
  );
}
