// The jurisdiction this deployment serves, fetched once from the API
// (GET /jurisdiction/) so nothing about the city or county — its name,
// bodies, map, timezone, copy — is baked into the web image.
//
// Server components `await getJurisdiction()`; client components read the
// same object from <JurisdictionProvider>. Both populate a module-level memo
// so the small synchronous helpers below (bodyLabel, bodyDot, ...) work in
// either kind of component once the config has been loaded.

import { api } from "@/lib/api";

export interface JurisdictionBody {
  key: string;
  label: string;
  short: string;
  color: number;
  hot: boolean;
  recommends: boolean;
  recorded: boolean;
  roles: string[]; // roster role titles ("Mayor", "Councilmember", "Supervisor")
}

export interface Jurisdiction {
  slug: string;
  name: string;
  identity: {
    short_name: string;
    noun: string;
    state_abbr: string;
    timezone: string;
    legislative_body_label: string;
    record_phrase: string;
    activity_noun: string;
  };
  site: { site_base_url: string; api_base_url: string };
  bodies: JurisdictionBody[];
  display: {
    map_center: [number, number];
    map_zoom: { compact: number; full: number };
    map_bounds: [[number, number], [number, number]];
    nearby_radii_m: number[];
    example_address: string;
    address_strip_regex: string;
    ask_suggestions: string[];
    ask_placeholder: string;
    boilerplate_terms: string[];
    glossary_overrides: GlossaryOverride[];
  };
  features: { impact: boolean; projects: boolean };
}

export interface GlossaryOverride {
  slug: string;
  term?: string;
  definition?: string;
  aliases?: string[];
  remove?: boolean;
}

// Body identity colors, by the body's palette index: the first body is deep
// teal, then ochre, plum, moss, sky. Literal class names so Tailwind keeps
// them. Dots (not filled badges) so they never read as status badges.
export const BODY_PALETTE = ["bg-teal", "bg-ochre", "bg-plum", "bg-moss", "bg-sky"];
export const BODY_BAR_PALETTE = BODY_PALETTE;

let memo: Jurisdiction | null = null;

/** Populate the memo (the client provider does this during render). */
export function setJurisdiction(j: Jurisdiction): Jurisdiction {
  memo = j;
  return j;
}

/** Fetch (cached by the API client) and memoise the jurisdiction. */
export async function getJurisdiction(): Promise<Jurisdiction> {
  if (memo) return memo;
  return setJurisdiction(await api.jurisdiction());
}

/** The memoised jurisdiction, or null before the first load. */
export const jurisdiction = (): Jurisdiction | null => memo;

const body = (key: string | null | undefined): JurisdictionBody | undefined =>
  key ? memo?.bodies.find((b) => b.key === key) : undefined;

/** Label for a body key; unknown or missing keys read as the key itself. */
export const bodyLabel = (key: string | null | undefined): string => body(key)?.label ?? key ?? "";

/** The noun for "Follow ... meetings"; falls back to the label. */
export const bodyShort = (key: string | null | undefined): string => body(key)?.short ?? bodyLabel(key);

/** Dot class for a body, grey for anything untracked. */
export const bodyDot = (key: string | null | undefined): string => {
  const b = body(key);
  return b ? BODY_PALETTE[b.color % BODY_PALETTE.length] : "bg-muted-soft";
};

/** Is this an advisory body whose outcomes are recommendations? */
export const bodyRecommends = (key: string | null | undefined): boolean => body(key)?.recommends ?? false;

/** The legislative body: the first configured body (City Council, Board of
 * Supervisors), whose members' votes are the record's spine. */
export const legislativeBody = (): JurisdictionBody | undefined => memo?.bodies[0];

/** Bodies with a hot-topics panel, in display order. */
export const hotBodies = (): JurisdictionBody[] => memo?.bodies.filter((b) => b.hot) ?? [];

/** The jurisdiction's IANA timezone (meetings are dated in it). */
export const timezone = (): string => memo?.identity.timezone ?? "America/New_York";
