import type { ImpactAssumption, ImpactMetric } from "@/lib/api";
import { labelFor, recompute } from "@/lib/assumptions";

/** One signed piece of a metric: the adjustment terms grouped by sign and by
 * which assumptions scale them. The pipeline asserts on every run that the
 * terms sum to the metric value (evaluate._check_adjust_terms), so
 * adds + subtracts == the published number exactly — this is a decomposition,
 * not an approximation. */
export interface CompositionGroup {
  /** Assumption keys this piece scales with (empty = fixed). */
  keys: string[];
  /** "Occupancy rate × Spending-survey scaling", or "" when fixed. */
  label: string;
  value: number;
  /** How many raw terms collapsed into this group (e.g. per-category terms). */
  terms: number;
}

export interface Composition {
  adds: CompositionGroup[];
  subtracts: CompositionGroup[];
  addsTotal: number;
  /** Negative (or zero). */
  subtractsTotal: number;
  net: number;
  /** True when the metric is a net of opposing pieces, not just a sum. */
  mixed: boolean;
}

/** Group a metric's adjustment terms into signed, labelled pieces.
 * Grouping is by SIGN FIRST, then by the assumptions a term scales with:
 * a revenue piece and a cost piece that happen to share a driver must stay
 * on opposite sides of the ledger instead of silently netting out. */
export function composition(m: ImpactMetric): Composition | null {
  const terms = m.adjust ?? [];
  if (terms.length === 0) return null;

  const groups = new Map<string, CompositionGroup>();
  for (const t of terms) {
    if (t.value === 0) continue;
    const keys = Object.entries(t.exps)
      .filter(([, e]) => e !== 0)
      .map(([k]) => k)
      .sort();
    const id = `${t.value < 0 ? "-" : "+"}|${keys.join(",")}`;
    const existing = groups.get(id);
    if (existing) {
      existing.value += t.value;
      existing.terms += 1;
    } else {
      groups.set(id, {
        keys,
        label: keys.map(labelFor).join(" × "),
        value: t.value,
        terms: 1,
      });
    }
  }

  const all = Array.from(groups.values());
  const adds = all.filter((g) => g.value > 0).sort((a, b) => b.value - a.value);
  const subtracts = all.filter((g) => g.value < 0).sort((a, b) => a.value - b.value);
  const addsTotal = adds.reduce((s, g) => s + g.value, 0);
  const subtractsTotal = subtracts.reduce((s, g) => s + g.value, 0);
  return {
    adds,
    subtracts,
    addsTotal,
    subtractsTotal,
    net: addsTotal + subtractsTotal,
    mixed: adds.length > 0 && subtracts.length > 0,
  };
}

export interface SensitivityRow {
  key: string;
  label: string;
  assumption: ImpactAssumption;
  /** The metric recomputed with this assumption at its low / high bound,
   * every other assumption held at its published value. */
  atLow: number;
  atHigh: number;
  swing: number;
}

/** Which assumptions actually move this metric, and by how much: a
 * one-at-a-time sweep of each driver across its published bounds, using the
 * same arithmetic the sliders use. Sorted by influence. */
export function sensitivity(
  m: ImpactMetric,
  assumptions: ImpactAssumption[],
): SensitivityRow[] {
  const terms = m.adjust ?? [];
  if (terms.length === 0) return [];

  const drivers = new Set<string>();
  for (const t of terms) {
    for (const [k, e] of Object.entries(t.exps)) if (e !== 0) drivers.add(k);
  }
  const baseline = Object.fromEntries(assumptions.map((a) => [a.key, a.value]));

  return assumptions
    .filter((a) => drivers.has(a.key))
    .map((a) => {
      const atLow = recompute(m, baseline, { ...baseline, [a.key]: a.low });
      const atHigh = recompute(m, baseline, { ...baseline, [a.key]: a.high });
      return {
        key: a.key,
        label: labelFor(a.key),
        assumption: a,
        atLow,
        atHigh,
        swing: Math.abs(atHigh - atLow),
      };
    })
    .filter((r) => r.swing > 0)
    .sort((x, y) => y.swing - x.swing);
}

/** Assumptions a metric names but that no term scales — the network-model
 * parameters that require a full pipeline re-run to change. */
export function lockedAssumptions(
  m: ImpactMetric,
  assumptions: ImpactAssumption[],
): ImpactAssumption[] {
  const drivers = new Set<string>();
  for (const t of m.adjust ?? []) {
    for (const [k, e] of Object.entries(t.exps)) if (e !== 0) drivers.add(k);
  }
  const named = new Set(m.assumptions);
  return assumptions.filter((a) => named.has(a.key) && !drivers.has(a.key));
}
