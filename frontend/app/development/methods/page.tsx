import Link from "next/link";
import MetricFormula from "@/components/MetricFormula";
import { METRIC_METHODS } from "@/lib/metric-methods";

export default function MetricMethodsPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-16 pt-8">
      <Link
        href="/development"
        className="text-sm font-semibold text-muted hover:text-ink"
      >
        &larr; Developments
      </Link>

      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Impact analysis methodology
      </div>
      <h1 className="text-[32px] font-medium tracking-[-0.5px]">Metric methods</h1>
      <p className="mb-7 mt-2 max-w-[760px] text-[13px] leading-[1.55] text-muted">
        General calculation methods and model inputs used across development impact analyses.
        Project-specific values and sensitivity ranges are reported on each development page.
      </p>

      <div className="overflow-x-auto rounded-2xl border border-hairline">
        <table className="w-full min-w-[920px] table-fixed text-[13px]">
          <thead className="bg-soft text-left text-muted">
            <tr>
              <th className="w-[25%] px-4 py-2.5 font-semibold">Metric</th>
              <th className="w-[45%] px-4 py-2.5 font-semibold">Calculation</th>
              <th className="w-[30%] px-4 py-2.5 font-semibold">Inputs and assumptions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline-soft">
            {METRIC_METHODS.map((metric) => (
              <tr key={metric.name} className="align-top">
                <td className="px-4 py-2.5 text-body">
                  <div className="font-semibold">{metric.name}</div>
                  <p className="mt-1.5 text-[12px] font-normal leading-[1.45] text-muted">
                    {metric.description}
                  </p>
                </td>
                <td className="px-4 py-3 leading-snug text-body">
                  <MetricFormula metric={metric} />
                </td>
                <td className="px-4 py-3 leading-snug text-muted">
                  <div className="space-y-1.5">
                    {metric.assumptions.map((assumption) => (
                      <div key={assumption}>{assumption}</div>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
