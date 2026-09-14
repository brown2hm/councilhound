import type { ImpactMetric } from "@/lib/api";

/** One scalar in a metric's unit: "−$1.7M", "$33k", "472", "95%". The
 * minus sign (U+2212) leads the currency symbol — never "$-1.7M". */
export function fmtScalar(value: number, unit: string, mDecimals = 1): string {
  if (unit === "fraction") return `${Math.round(value * 100)}%`;
  const dollars = unit.startsWith("$");
  const sign = value < 0 ? "−" : "";
  const x = Math.abs(value);
  if (dollars && x >= 1_000_000) return `${sign}$${(x / 1_000_000).toFixed(mDecimals)}M`;
  if (dollars && x >= 10_000) return `${sign}$${Math.round(x / 1_000).toLocaleString()}k`;
  if (dollars) return `${sign}$${Math.round(x).toLocaleString()}`;
  if (x >= 100) return `${sign}${Math.round(x).toLocaleString()}`;
  return `${sign}${x.toLocaleString(undefined, { maximumFractionDigits: 1 })}`;
}

const MARGINAL = "Net annual fiscal impact — marginal framing";

function money(v: number): string {
  return fmtScalar(Math.abs(v), "$/yr");
}

function describeNet(v: number): string {
  if (Math.abs(v) < 25_000) return "roughly break-even";
  return v < 0 ? `a net cost of about ${money(v)} a year` : `a net gain of about ${money(v)} a year`;
}

/** A deterministic, jargon-free reading of the fiscal headline numbers.
 * Computed from the same metrics the tiles show — no LLM, no drift. */
export function plainLanguageImpact(metrics: ImpactMetric[]): string | null {
  const net = metrics.find((m) => m.name === MARGINAL);
  if (!net) return null;

  const residents = metrics.find((m) => m.name === "New residents");
  const tax = metrics.find((m) => m.name === "Real estate tax increase");

  const parts: string[] = [];
  if (residents && tax) {
    parts.push(
      `In plain terms: the project would add roughly ${fmtScalar(residents.value, residents.unit)} residents ` +
      `and about ${fmtScalar(tax.value, tax.unit)} a year in new property tax, but serving those residents costs money too.`,
    );
  } else {
    parts.push("In plain terms: the project brings the city new tax revenue, but serving its residents costs money too.");
  }

  // the assumption ranges bracket the figure; lead with the central estimate
  const lo = Math.min(net.low ?? net.value, net.high ?? net.value);
  const hi = Math.max(net.low ?? net.value, net.high ?? net.value);
  const sameSign = Math.sign(lo) === Math.sign(hi) && Math.abs(lo) >= 25_000 && Math.abs(hi) >= 25_000;
  if (sameSign) {
    const range = hi < 0 ? `between ${money(hi)} and ${money(lo)}` : `between ${money(lo)} and ${money(hi)}`;
    parts.push(`Counting the city services that actually grow with new residents, that nets out to ${describeNet(net.value)}, ${range} across the assumption ranges.`);
  } else {
    parts.push(
      `Counting the city services that actually grow with new residents, that nets out to ${describeNet(net.value)}, ` +
      `anywhere between ${describeNet(lo)} and ${describeNet(hi)} across the assumption ranges.`,
    );
  }
  parts.push(
    "Fixed citywide costs are not charged to new residents; school costs follow the project's own student estimate.",
  );
  return parts.join(" ");
}
