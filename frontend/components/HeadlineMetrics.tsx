"use client";

import { useState } from "react";
import MetricDetailPanel from "@/components/MetricDetailPanel";
import type { ImpactAssumption, ImpactMetric } from "@/lib/api";
import { fmtScalar } from "@/lib/format";

function fmtRange(m: ImpactMetric): string | null {
  if (m.low == null || m.high == null || (m.low === m.value && m.high === m.value)) return null;
  return `${fmtScalar(m.low, m.unit)} – ${fmtScalar(m.high, m.unit)}`;
}

function unitLabel(unit: string): string {
  if (unit === "fraction") return "";
  return unit.replace("$/yr", "per year").replace("$/acre", "per acre").replace("$", "");
}

/** Headline tiles that open a detail panel explaining how each number is
 * built — its signed composition, what moves it, formula, and assumptions. */
export default function HeadlineMetrics({
  metrics,
  assumptions,
}: {
  metrics: ImpactMetric[];
  assumptions: ImpactAssumption[];
}) {
  const [selected, setSelected] = useState<ImpactMetric | null>(null);

  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {metrics.map((m) => (
          <button
            key={m.name}
            type="button"
            onClick={() => setSelected(m)}
            aria-haspopup="dialog"
            aria-expanded={selected?.name === m.name}
            className="group rounded-2xl border border-hairline bg-canvas p-4 text-left transition hover:border-muted-soft hover:bg-soft focus:outline-none focus-visible:ring-2 focus-visible:ring-teal"
          >
            <div className="text-[22px] font-semibold tracking-[-0.3px]">
              {fmtScalar(m.value, m.unit)}
            </div>
            {fmtRange(m) && (
              <div className="text-[12px] font-medium text-muted">range {fmtRange(m)}</div>
            )}
            <div className="mt-1 text-[12px] leading-snug text-muted">
              {m.name}
              {unitLabel(m.unit) && ` (${unitLabel(m.unit).trim()})`}
            </div>
            <div className="mt-2 text-[11px] font-semibold text-muted-soft group-hover:text-body">
              How this is built →
            </div>
          </button>
        ))}
      </div>

      {selected && (
        <MetricDetailPanel
          metric={selected}
          assumptions={assumptions}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
