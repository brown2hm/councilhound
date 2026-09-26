/** Plain-language definitions for the vocabulary that shows up in agendas
 * and minutes. Matched case-insensitively on whole words, longest term
 * first, so "special use permit" wins over "permit". Keep entries short:
 * they render as hover tooltips as well as on /glossary. */
import type { Jurisdiction } from "@/lib/jurisdiction";

export interface GlossaryEntry {
  slug: string;
  term: string;
  aliases?: string[];
  definition: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    slug: "special-use-permit",
    term: "Special use permit",
    aliases: ["special use permits", "SUP"],
    definition:
      "Permission for a use the zoning allows only case by case (a drive-through, a school, a larger building). Needs a public hearing and a {{legislative_body}} vote, and can carry conditions.",
  },
  {
    slug: "special-exception",
    term: "Special exception",
    aliases: ["special exceptions"],
    definition:
      "A {{legislative_body}}-approved departure from a specific zoning rule, such as parking counts or height, for one property.",
  },
  {
    slug: "rezoning",
    term: "Rezoning",
    aliases: ["rezone", "rezoned", "zoning map amendment"],
    definition:
      "Changing which zoning district a property sits in, which changes what can be built there. Goes to the Planning Commission for a recommendation, then to {{legislative_body}} for the vote.",
  },
  {
    slug: "zoning",
    term: "Zoning",
    aliases: ["zoning ordinance", "zoning district"],
    definition:
      "The {{noun}} rules that say what can be built where: uses, height, density, setbacks, and parking, by district.",
  },
  {
    slug: "text-amendment",
    term: "Text amendment",
    aliases: ["zoning text amendment", "text amendments"],
    definition:
      "A change to the words of the zoning ordinance itself, {{noun}}wide, rather than to one property's district.",
  },
  {
    slug: "comprehensive-plan",
    term: "Comprehensive plan",
    aliases: ["comp plan", "2035 comprehensive plan"],
    definition:
      "The {{noun}}'s long-range vision for land use, transportation, housing, and parks. Rezonings are judged partly on whether they fit it.",
  },
  {
    slug: "small-area-plan",
    term: "Small area plan",
    aliases: ["small area plans"],
    definition:
      "A detailed plan for one neighborhood or corridor that fills in the comprehensive plan's broad goals with block-level guidance.",
  },
  {
    slug: "site-plan",
    term: "Site plan",
    aliases: ["site plans"],
    definition:
      "The engineered drawings of a project: buildings, parking, grading, stormwater, landscaping. Reviewed by staff for code compliance after zoning is settled.",
  },
  {
    slug: "general-development-plan",
    term: "General development plan",
    aliases: ["GDP"],
    definition:
      "The conceptual layout submitted with a rezoning or special use permit that shows what the applicant commits to build.",
  },
  {
    slug: "proffer",
    term: "Proffer",
    aliases: ["proffers", "proffered", "proffer conditions"],
    definition:
      "A written promise an applicant volunteers with a rezoning, such as a cash contribution, a road improvement, or a use limit. Once accepted it binds the land.",
  },
  {
    slug: "variance",
    term: "Variance",
    aliases: ["variances"],
    definition:
      "Relief from a zoning rule granted by the Board of Zoning Appeals when a property's shape or situation makes strict compliance a hardship.",
  },
  {
    slug: "board-of-zoning-appeals",
    term: "Board of Zoning Appeals",
    aliases: ["BZA"],
    definition:
      "The appointed board that hears variance requests and appeals of zoning decisions.",
  },
  {
    slug: "board-of-architectural-review",
    term: "Board of Architectural Review",
    aliases: ["BAR"],
    definition:
      "The appointed board that reviews building design, signs, and exterior changes in the historic and commercial districts.",
  },
  {
    slug: "certificate-of-appropriateness",
    term: "Certificate of appropriateness",
    aliases: ["certificates of appropriateness", "COA"],
    definition:
      "Board of Architectural Review approval that an exterior change fits the district's design standards.",
  },
  {
    slug: "planning-commission",
    term: "Planning Commission",
    definition:
      "The appointed body that reviews land-use applications and plans first and sends a recommendation to {{legislative_body}}, which makes the final decision.",
  },
  {
    slug: "public-hearing",
    term: "Public hearing",
    aliases: ["public hearings"],
    definition:
      "The formal, legally advertised part of a meeting where anyone can speak on an item before the body votes.",
  },
  {
    slug: "work-session",
    term: "Work session",
    aliases: ["work sessions"],
    definition:
      "A meeting for discussion and briefing only. No formal votes are taken, but positions get set here.",
  },
  {
    slug: "consent-agenda",
    term: "Consent agenda",
    aliases: ["consent items", "consent item"],
    definition:
      "Routine items bundled into a single vote with no discussion. Any member can pull an item out for separate debate.",
  },
  {
    slug: "first-reading",
    term: "First reading",
    aliases: ["first readings"],
    definition:
      "The introduction of an ordinance. Approval here schedules the public hearing; the binding vote is at the second reading.",
  },
  {
    slug: "second-reading",
    term: "Second reading",
    aliases: ["second readings"],
    definition:
      "The final vote on an ordinance after its public hearing. This is the vote that adopts or rejects it.",
  },
  {
    slug: "ordinance",
    term: "Ordinance",
    aliases: ["ordinances"],
    definition:
      "A local law. Ordinances amend the {{noun}} code and need a public hearing and two readings.",
  },
  {
    slug: "resolution",
    term: "Resolution",
    aliases: ["resolutions"],
    definition:
      "A formal statement of {{legislative_body}} position or a one-time action, such as approving a contract. Passes on a single vote.",
  },
  {
    slug: "motion",
    term: "Motion",
    aliases: ["motions", "moved and seconded"],
    definition:
      "A member's formal proposal to act. It needs a second from another member before the body votes on it.",
  },
  {
    slug: "deferred",
    term: "Deferred",
    aliases: ["defer", "continued", "continuance", "tabled"],
    definition:
      "Postponed to a later meeting without a decision. Items can be deferred to a set date or indefinitely.",
  },
  {
    slug: "abstain",
    term: "Abstain",
    aliases: ["abstained", "abstention"],
    definition:
      "A member present who chooses not to vote yes or no, usually because of a conflict of interest.",
  },
  {
    slug: "closed-session",
    term: "Closed session",
    aliases: ["closed meeting", "executive session"],
    definition:
      "A portion of a meeting closed to the public under state law, typically for legal advice, personnel, or property negotiations. Votes must still happen in open session.",
  },
  {
    slug: "capital-improvement-program",
    term: "Capital improvement program",
    aliases: ["CIP", "capital improvement plan"],
    definition:
      "The multi-year budget for big physical projects: roads, buildings, parks, utilities.",
  },
  {
    slug: "appropriation",
    term: "Appropriation",
    aliases: ["appropriations", "supplemental appropriation"],
    definition:
      "{{legislative_body}} authorization to spend a specific amount of money. Budget changes mid-year come as supplemental appropriations.",
  },
  {
    slug: "accessory-dwelling-unit",
    term: "Accessory dwelling unit",
    aliases: ["accessory dwelling units", "ADU", "ADUs"],
    definition:
      "A second, smaller home on a single-family lot: a basement apartment, a garage conversion, or a backyard cottage.",
  },
  {
    slug: "setback",
    term: "Setback",
    aliases: ["setbacks"],
    definition:
      "The required distance between a building and the property line.",
  },
  {
    slug: "floor-area-ratio",
    term: "Floor area ratio",
    aliases: ["FAR"],
    definition:
      "Total building floor area divided by lot area. A FAR of 2.0 means two square feet of building per square foot of land.",
  },
  {
    slug: "density",
    term: "Density",
    aliases: ["dwelling units per acre"],
    definition:
      "How many homes are allowed per acre of land.",
  },
  {
    slug: "mixed-use",
    term: "Mixed-use",
    aliases: ["mixed use"],
    definition:
      "A building or project that combines homes with shops, offices, or other uses.",
  },
  {
    slug: "staff-report",
    term: "Staff report",
    aliases: ["staff reports"],
    definition:
      "The {{noun}} staff's written analysis and recommendation on an agenda item, published with the agenda packet.",
  },
  {
    slug: "quorum",
    term: "Quorum",
    definition:
      "The minimum number of members who must be present for the body to conduct business.",
  },
  {
    slug: "proclamation",
    term: "Proclamation",
    aliases: ["proclamations"],
    definition:
      "A ceremonial statement recognizing a person, group, or occasion. No legal effect.",
  },
];

/** Every spelling that should match, mapped back to its entry. Longest
 * first so multi-word terms win over their fragments. */
export const GLOSSARY_LOOKUP: { needle: string; entry: GlossaryEntry }[] = GLOSSARY.flatMap(
  (entry) => [entry.term, ...(entry.aliases ?? [])].map((needle) => ({ needle, entry })),
).sort((a, b) => b.needle.length - a.needle.length);

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** One regex over every needle, whole-word, case-insensitive. Short all-caps
 * acronyms (FAR, BAR, SUP) only match when written in caps so "far" and
 * "bar" in prose stay untouched. */
export const GLOSSARY_RE = new RegExp(
  "\\b(" + GLOSSARY_LOOKUP.map((l) => escapeRe(l.needle)).join("|") + ")\\b",
  "gi",
);

export function lookupTerm(match: string): GlossaryEntry | null {
  const low = match.toLowerCase();
  for (const { needle, entry } of GLOSSARY_LOOKUP) {
    if (needle.toLowerCase() !== low) continue;
    const isAcronym = needle.length <= 4 && needle === needle.toUpperCase();
    if (isAcronym && match !== needle) return null;
    return entry;
  }
  return null;
}

/** The glossary for one jurisdiction: `{{legislative_body}}` and `{{noun}}`
 * in the base definitions become its words, and display.glossary_overrides
 * remove or rewrite entries whose meaning differs there (a county's
 * "special exception" is not a city's). Memoised per jurisdiction slug. */
export interface GlossaryVariant {
  entries: GlossaryEntry[];
  lookup: { needle: string; entry: GlossaryEntry }[];
  regex: RegExp;
  lookupTerm: (match: string) => GlossaryEntry | null;
}

function buildVariant(entries: GlossaryEntry[]): GlossaryVariant {
  const lookup = entries.flatMap((entry) => [entry.term, ...(entry.aliases ?? [])].map((needle) => ({ needle, entry })));
  lookup.sort((a, b) => b.needle.length - a.needle.length);
  const regex = new RegExp(`\\b(?:${lookup.map((l) => escapeRe(l.needle)).join("|")})\\b`, "gi");
  const lookupTerm = (match: string): GlossaryEntry | null => {
    const low = match.toLowerCase();
    for (const { needle, entry } of lookup) {
      if (needle.toLowerCase() !== low) continue;
      // short all-caps acronyms (FAR, BAR, SUP) only match when written in caps
      const isAcronym = needle.length <= 4 && needle === needle.toUpperCase();
      if (isAcronym && match !== needle) return null;
      return entry;
    }
    return null;
  };
  return { entries, lookup, regex, lookupTerm };
}

const variants = new Map<string, GlossaryVariant>();

export function glossaryFor(j: Jurisdiction | null): GlossaryVariant {
  const key = j?.slug ?? "";
  const cached = variants.get(key);
  if (cached) return cached;
  const legislative = j?.identity.legislative_body_label ?? "City Council";
  const noun = j?.identity.noun ?? "city";
  const fill = (t: string) => t.replace(/\{\{legislative_body\}\}/g, legislative).replace(/\{\{noun\}\}/g, noun);
  const overrides = new Map((j?.display.glossary_overrides ?? []).map((o) => [o.slug, o]));
  const entries: GlossaryEntry[] = [];
  for (const base of GLOSSARY) {
    const o = overrides.get(base.slug);
    if (o?.remove) continue;
    entries.push({
      slug: base.slug,
      term: o?.term ?? fill(base.term),
      aliases: o?.aliases ?? base.aliases,
      definition: o?.definition ?? fill(base.definition),
    });
  }
  const v = buildVariant(entries);
  variants.set(key, v);
  return v;
}
