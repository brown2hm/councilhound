import type { ImpactMetric } from "@/lib/api";

/** Human labels for assumption keys — shared by the assumptions lab and the
 * metric detail panel so the same knob never reads two different ways. */
export const ASSUMPTION_LABELS: Record<string, string> = {
  occupancy_rate: "Occupancy rate",
  avg_hh_size_multifamily: "Household size (multifamily)",
  income_premium_new_construction: "New-construction income premium",
  ces_scale: "Spending-survey scaling",
  walk_trips_per_resident_day: "Walk trips per resident per day",
  sqft_per_office_job: "Sq ft per office job",
  sqft_per_retail_job: "Sq ft per retail job",
  residential_value_per_unit: "Assessed value per dwelling unit ($)",
  commercial_value_per_sqft: "Retail value per sq ft ($)",
  office_value_per_sqft: "Office value per sq ft ($)",
  office_receipts_per_sqft: "Office gross receipts per sq ft ($/yr)",
  bpp_value_per_sqft: "Business equipment value per sq ft ($)",
  net_new_share: "Share of on-site sales that is new to the city",
  onsite_restaurant_share_of_retail: "Restaurant share of ground-floor space",
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
  beta_bike: "Bike-time decay (β)",
  bike_share_neighborhood: "Bike share — neighborhood trips",
  bike_share_comparison: "Bike share — comparison goods",
  bike_share_grocery_entertainment: "Bike share — grocery/entertainment",
  bike_trips_per_resident_day: "Bike trips per resident per day",
  induced_corridor_visit_share: "Induced corridor visit share",
  bike_spend_per_trip_restaurant: "Bike spend per trip — food/drink ($)",
  bike_spend_per_trip_convenience: "Bike spend per trip — convenience ($)",
  bike_spend_per_trip_other_retail: "Bike spend per trip — other retail ($)",
  beta_trail_access_km: "Trail-access decay (β per km)",
  trail_user_days_per_capita: "Trail user-days per resident per year",
  trail_spend_per_user_day: "Trail spending per user-day ($)",
  trail_property_premium: "Trail property premium",
};

export function labelFor(key: string): string {
  return ASSUMPTION_LABELS[key] ?? key;
}

/** Exact client-side recompute. Each adjustable metric ships a power-law
 * decomposition (metric.adjust); evaluating
 *   value' = sum_t t.value x prod_k (adjusted[k]/baseline[k])^t.exps[k]
 * reproduces what the pipeline itself would compute for those assumptions.
 * Network-model parameters (travel decay, mode shares) appear in no term —
 * changing those requires a full re-run. */
export function recompute(
  m: ImpactMetric,
  baseline: Record<string, number>,
  adjusted: Record<string, number>,
): number {
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
