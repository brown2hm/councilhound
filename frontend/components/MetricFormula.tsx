import katex from "katex";
import type { MetricMethod } from "@/lib/metric-methods";

const HUFF_PROBABILITY = String.raw`P_{j,c}^{(m)} &= \frac{A_{j,c}^{\alpha}\,\omega_{c,m}\,e^{-\beta_m t_{j,m}}}
  {\sum_k\sum_r A_{k,c}^{\alpha}\,\omega_{c,r}\,e^{-\beta_r t_{k,r}}}`;

const WALK_PROBABILITY = String.raw`P_{j,c}^{(\mathrm{walk})} &=
  \frac{A_{j,c}^{\alpha}\,\omega_{c,\mathrm{walk}}\,e^{-\beta_{\mathrm{walk}}t_{j,\mathrm{walk}}}}
  {\sum_k\sum_r A_{k,c}^{\alpha}\,\omega_{c,r}\,e^{-\beta_r t_{k,r}}}`;

function formulaForMetric(name: string): string | null {
  if (name === "New households") return String.raw`H = U \times o`;
  if (name === "New residents") return String.raw`R = H \times \bar{h}`;
  if (name === "Aggregate household income") {
    return String.raw`I = H \times M_{\mathrm{tract}} \times p_{\mathrm{new}}`;
  }
  if (name.startsWith("New annual spending:" ) || name === "New annual spending by category") {
    return String.raw`S_c = I \times s_c^{\mathrm{CES}} \times k_{\mathrm{CES}}`;
  }
  if (name.startsWith("In-city capture share:" ) || name === "In-city capture share") {
    return String.raw`\begin{aligned}
      ${HUFF_PROBABILITY} \\
      C_j &= \sum_c S_c \sum_m P_{j,c}^{(m)} \\
      q_{\mathrm{city}} &= \frac{\sum_{j \in \mathrm{city}} C_j}{\sum_j C_j}
    \end{aligned}`;
  }
  if (name === "Annual capture: project's own ground-floor retail") {
    return String.raw`\begin{aligned}
      ${HUFF_PROBABILITY} \\
      C_{\mathrm{own}} &= \sum_c S_c \sum_m P_{\mathrm{own},c}^{(m)}
    \end{aligned}`;
  }
  if (name.startsWith("Annual capture:") || name === "Annual capture at a destination") {
    return String.raw`\begin{aligned}
      ${HUFF_PROBABILITY} \\
      C_j &= \sum_c S_c \sum_m P_{j,c}^{(m)}
    \end{aligned}`;
  }
  if (name === "On-site jobs removed (existing space)") {
    return String.raw`J_{\mathrm{removed}} = \frac{F_{\mathrm{existing}}}{f_{\mathrm{office/job}}}`;
  }
  if (name === "On-site retail jobs added") {
    return String.raw`J_{\mathrm{added}} = \frac{F_{\mathrm{retail}}}{f_{\mathrm{retail/job}}}`;
  }
  if (name === "Net on-site job change") {
    return String.raw`\Delta J = J_{\mathrm{added}} - J_{\mathrm{removed}}`;
  }
  if (name === "New annual spending arriving on foot") {
    return String.raw`\begin{aligned}
      ${WALK_PROBABILITY} \\
      W &= \sum_j\sum_c S_c\,P_{j,c}^{(\mathrm{walk})}
    \end{aligned}`;
  }
  if (name === "Spending arriving on foot at project's own retail" || name === "Spending arriving on foot at project retail") {
    return String.raw`\begin{aligned}
      ${WALK_PROBABILITY} \\
      W_{\mathrm{own}} &= \sum_c S_c\,P_{\mathrm{own},c}^{(\mathrm{walk})}
    \end{aligned}`;
  }
  if (name === "Implied spending per resident walk trip") {
    return String.raw`\bar{w}_{\mathrm{trip}} = \frac{W}{365\,T_{\mathrm{walk/day}}}`;
  }
  if (name === "New resident walk trips per day") {
    return String.raw`T_{\mathrm{walk/day}} = R \times r_{\mathrm{walk}}`;
  }
  if (name.startsWith("Foot-traffic index change")) {
    return String.raw`\begin{aligned}
      w_{ij}^{\mathrm{walk}} &= e^{-\beta_{\mathrm{walk}}t_{ij}} \\
      \Delta_e &= 100\,\frac{F_e^{\mathrm{new}}}{F_e^{\mathrm{baseline}}} \\
      \Delta_{10} &= \frac{1}{10}\sum_{e \in N_{10}} \Delta_e
    \end{aligned}`;
  }
  if (name === "Current real estate tax (site)") {
    return String.raw`T_{\mathrm{RE},0} = V_0 \times \frac{r_{\mathrm{RE}}}{100}`;
  }
  if (name === "Current value per acre") return String.raw`V_{0,\mathrm{acre}} = \frac{V_0}{A}`;
  if (name === "Projected assessed value") {
    return String.raw`V_1 = U\,v_{\mathrm{unit}} + F_{\mathrm{retail}}\,v_{\mathrm{sf}}`;
  }
  if (name === "Projected real estate tax") {
    return String.raw`T_{\mathrm{RE},1} = V_1 \times \frac{r_{\mathrm{RE}}}{100}`;
  }
  if (name === "Real estate tax increase") {
    return String.raw`\Delta T_{\mathrm{RE}} = T_{\mathrm{RE},1} - T_{\mathrm{RE},0}`;
  }
  if (name === "Projected value per acre") return String.raw`V_{1,\mathrm{acre}} = \frac{V_1}{A}`;
  if (name === "Personal property tax on resident vehicles (rough estimate)") {
    return String.raw`T_{\mathrm{pp}} \approx H \times \nu_{\mathrm{hh}} \times \bar{v}_{\mathrm{veh}} \times \frac{r_{\mathrm{pp}}}{100}`;
  }
  if (name === "BPOL business license tax on project retail (rough estimate)") {
    return String.raw`T_{\mathrm{bpol}} \approx F_{\mathrm{retail}} \times g_{\mathrm{sf}} \times \frac{r_{\mathrm{bpol}}}{100}`;
  }
  if (name === "Meals tax on captured in-city dining") {
    return String.raw`T_{\mathrm{meals}} = S_{\mathrm{restaurant}}\,q_{\mathrm{city,food}}\,r_{\mathrm{meals}}`;
  }
  if (name === "Local sales tax share on captured in-city retail") {
    return String.raw`T_{\mathrm{sales}} = S_{\mathrm{retail}}\,q_{\mathrm{city,retail}}\,r_{\mathrm{local}}`;
  }
  if (name === "Estimated K-12 students") {
    return String.raw`S_{\mathrm{K12}} = U \times s_{\mathrm{unit}}`;
  }
  if (name === "Annual service cost — naive per-capita method" || name === "Annual service cost - naive per-capita method") {
    return String.raw`C_{\mathrm{naive}} = R \times c_{\mathrm{non\text{-}school}} + S_{\mathrm{K12}} \times c_{\mathrm{pupil}}`;
  }
  if (name === "Annual service cost — marginal framing" || name === "Annual service cost - marginal framing") {
    return String.raw`C_{\mathrm{marginal}} = R \times c_{\mathrm{non\text{-}school}} \times k_{\mathrm{marginal}} + S_{\mathrm{K12}} \times c_{\mathrm{pupil}}`;
  }
  if (name === "Net annual fiscal impact — naive per-capita method" || name === "Net annual fiscal impact - naive per-capita method") {
    return String.raw`N_{\mathrm{naive}} = \sum_r T_r - C_{\mathrm{naive}}`;
  }
  if (name === "Net annual fiscal impact — marginal framing" || name === "Net annual fiscal impact - marginal framing") {
    return String.raw`N_{\mathrm{marginal}} = \sum_r T_r - C_{\mathrm{marginal}}`;
  }
  if (name === "Net annual fiscal impact (range across both cost methods)" || name === "Net annual fiscal impact range") {
    return String.raw`N \in \left[\sum_r T_r-C_{\mathrm{naive}},\;\sum_r T_r-C_{\mathrm{marginal}}\right]`;
  }
  if (name === "New annual spending arriving by bike") {
    return String.raw`S_{\mathrm{bike}} = \sum_c \sum_j S_c\,P_{\mathrm{bike}}(j \mid c)`;
  }
  if (name === "Bike catchment population (decay-weighted)") {
    return String.raw`P_{\mathrm{eff}} = \sum_b \mathrm{pop}_b\,e^{-\beta_{\mathrm{bike}} t_b}`;
  }
  if (name === "Induced bike visits per day (corridor)") {
    return String.raw`V = P_{\mathrm{eff}} \times \tau_{\mathrm{bike}} \times \sigma_{\mathrm{induced}}`;
  }
  if (name === "New annual spending at corridor businesses") {
    return String.raw`S_{\mathrm{corridor}} = 365 \sum_g V\,m_g\,\bar{s}_g`;
  }
  if (name.startsWith("Implied corridor sales uplift")) {
    return String.raw`u = \frac{S_{\mathrm{corridor}}}{n_{\mathrm{biz}} \times \bar{F} \times g_{\mathrm{sf}}}`;
  }
  if (name === "Trail catchment population (decay-weighted)") {
    return String.raw`P_{\mathrm{eff}} = \sum_b \mathrm{pop}_b\,e^{-\beta_{\mathrm{access}} d_b}`;
  }
  if (name === "Annual trail user-days") {
    return String.raw`D = P_{\mathrm{eff}} \times u_{\mathrm{capita}}`;
  }
  if (name === "Annual trail-user spending at nearby businesses") {
    return String.raw`S_{\mathrm{trail}} = D \times \bar{s}_{\mathrm{day}}`;
  }
  if (name === "Assessed value within the trail premium band") {
    return String.raw`V_{\mathrm{band}} = \sum_{p \in \mathrm{band}} \mathrm{AV}_p`;
  }
  if (name === "Trail property value uplift (capitalization)") {
    return String.raw`\Delta V = V_{\mathrm{band}} \times \pi_{\mathrm{trail}}`;
  }
  if (name === "Annual real estate tax increment (trail premium)") {
    return String.raw`\Delta T_{\mathrm{RE}} = \Delta V \times \frac{r_{\mathrm{RE}}}{100}`;
  }
  return null;
}

function explanationForMetric(metric: MetricMethod): string {
  if (metric.name.startsWith("Foot-traffic index change")) {
    return "Exact marginal trip flows from the site using POI-weighted destinations and shortest paths, compared with seeded sampled baseline betweenness for the current population";
  }

  if (!metric.method.startsWith("Huff model over individual retail POIs:")) {
    return metric.method;
  }

  const qualifiers = metric.method
    .split(";")
    .slice(1)
    .map((part) => part.trim())
    .filter(Boolean)
    .join("; ");
  const base = "Joint walk/drive Huff destination choice using CES category spending";
  return qualifiers ? `${base}; ${qualifiers}` : base;
}

export default function MetricFormula({ metric }: { metric: MetricMethod }) {
  const formula = formulaForMetric(metric.name);
  if (!formula) return <span>{metric.method}</span>;

  const html = katex.renderToString(formula, {
    displayMode: true,
    fleqn: true,
    output: "html",
    strict: false,
    throwOnError: false,
  });

  return (
    <div>
      <div
        className="metric-formula overflow-x-auto text-[14px]"
        dangerouslySetInnerHTML={{ __html: html }}
      />
      <p className="mt-1.5 text-[12px] leading-snug text-muted">
        {explanationForMetric(metric)}
      </p>
    </div>
  );
}
