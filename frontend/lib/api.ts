// Typed client for the CouncilHound API. Server components fetch directly
// (API_URL, in-cluster/localhost); the Ask page fetches from the browser
// (NEXT_PUBLIC_API_URL).

import { unstable_cache } from "next/cache";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface MeetingDecision {
  label: string | null;
  title: string;
  result: string | null; // passed | failed | deferred
}

export interface MeetingSummary {
  id: number;
  date: string;
  title: string;
  body: string;
  meeting_type: string;
  status: string;
  duration_seconds: number | null;
  agenda_item_count: number;
  // present when the list was asked for include_decisions=true
  decisions?: MeetingDecision[];
  discussed?: string[];
  votes_passed?: number;
  votes_failed?: number;
}

export interface VoteInfo {
  description: string | null;
  motion_result: string | null;
  vote_breakdown: Record<string, string>;
}

export interface MeetingDocument {
  doc_type: string; // 'agenda' | 'minutes' | 'actions_report' | 'agenda_item_pdf' | 'other'
  title: string | null;
  source_url: string;
  agenda_item_id: number | null;
}

/** A tracked topic an agenda item touches — the meeting -> topic link. */
export interface AgendaItemEntity {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  status_after: string | null;
  // what the record filed for this topic at this item; null for a bare mention
  update_text: string | null;
  has_wiki: boolean;
  official_slug: string | null; // the city's project slug when it keeps a record (wiki lives under /development)
}

/** A tracked topic the transcript names inside an item's window, beyond the
 * topics the item is filed under. */
export interface NamedTopic {
  slug: string;
  name: string;
  count: number; // transcript passages
}

/** The transcript's account of a chaptered agenda item. */
export interface ItemDiscussion {
  seconds: number;
  exact: boolean; // false when unchaptered items sit inside this item's window
  chunks: number;
  named: NamedTopic[];
}

/** One topic the meeting touched, with what the wiki already knows. */
export interface MeetingTopic {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  status_after: string | null;
  has_wiki: boolean;
  official_slug: string | null;
  lede: string | null; // overview lede, else the profile's lead
  open_questions: string[];
  history_anchor: string | null; // this meeting's heading in the wiki history page, when it has one
}

/** A tracked topic the transcript names that no agenda item links. */
export interface NamedInDiscussion {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  has_wiki: boolean;
  official_slug: string | null;
  count: number;
  seconds: number;
  first: { start_seconds: number; watch_url: string | null; excerpt: string };
}

export interface AgendaItemInfo {
  id: number;
  label: string;
  title: string | null;
  description: string | null;
  outcome: string | null;
  start_seconds: number | null;
  watch_url: string | null;
  votes: VoteInfo[];
  entities: AgendaItemEntity[];
  documents: MeetingDocument[];
  discussion: ItemDiscussion | null; // null without an index point or a transcript
}

export interface MeetingDetail extends Omit<MeetingSummary, "agenda_item_count" | "status"> {
  granicus_clip_id: string;
  video_url: string | null;
  agenda_url: string | null;
  minutes_url: string | null;
  agenda_items: AgendaItemInfo[];
  documents: MeetingDocument[];
  other_discussion: AgendaItemEntity[]; // raised outside any numbered item (comments, reports, public comment)
  transcribed: boolean;
  topics: MeetingTopic[];
  named_in_discussion: NamedInDiscussion[];
}

/** The light official-record fields the directory needs for a project card. */
export interface EntityOfficialCard {
  slug: string;
  official_status: string | null;
  project_type: string | null;
  address: string | null;
  image_url: string | null;
  description: string | null;
  has_evaluation: boolean;
}

export interface EntitySummary {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  last_seen: string | null;
  first_seen: string | null;
  bodies: string[];
  lat: number | null;
  lng: number | null;
  has_wiki: boolean;
  official: EntityOfficialCard | null;
}

/** GET /entities/counts — the directory's size by kind, for the section
 * headers on /topics. */
export interface EntityCounts {
  total: number;
  people: number;
  records: number;
  official: number;
  recurring: number;
  by_type: Record<string, number>;
}

export interface EntitySuggestion {
  kind: "topic" | "member";
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  last_seen: string | null;
  href: string;
}

export interface EntityChange {
  id: number;
  kind: "status_change" | "new";
  slug: string;
  name: string;
  entity_type: string;
  from_status: string | null;
  to_status: string | null;
  current_status: string | null;
  date: string;
  meeting_id: number;
  meeting_title: string;
  body: string;
  agenda_item_label: string | null;
  update_text: string;
  watch_url: string | null;
}

export interface ChangesResponse {
  days: number;
  since: string;
  changes: EntityChange[];
}

export interface NearbyResult {
  slug: string | null;
  name: string;
  entity_type: string;
  current_status: string | null;
  distance_m: number;
  lat: number;
  lng: number;
  address: string | null;
  summary: string | null;
  update_count: number;
  last_seen: string | null;
  official: {
    slug: string;
    official_status: string | null;
    project_type: string | null;
    image_url: string | null;
    has_evaluation: boolean;
  } | null;
}

export interface NearbyResponse {
  lat: number;
  lng: number;
  radius_m: number;
  results: NearbyResult[];
}

export interface GeocodeHit {
  lat: number;
  lng: number;
  matched_address: string | null;
}

export interface TimelineEntry {
  date: string;
  meeting_id: number;
  meeting_title: string;
  body: string;
  agenda_item_label: string | null;
  agenda_item_title: string | null;
  update_text: string;
  status_after: string | null;
  agenda_url: string | null;
  minutes_url: string | null;
  watch_url: string | null;
  votes: VoteInfo[];
}

export interface StatusSource {
  date: string;
  meeting_id: number;
  meeting_title: string;
  watch_url: string | null;
}

export interface RelatedEntity {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  shared_meetings: number;
}

export interface MemberCommentary {
  member: string;
  slug: string | null;
  summary: string;
}

export interface EntityProfileInfo {
  summary: string | null;
  open_questions: string[];
  member_commentary: MemberCommentary[];
  updated_at: string | null;
}

export interface UpcomingEvent {
  event_id: string;
  title: string;
  body: string | null;
  starts_at: string | null;
  in_progress: boolean;
  agenda_url: string | null;
}

export interface UpcomingAgendaTopic {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  last_seen: string | null;
  agenda_context: string | null;
  // named inside a public-hearing section of the agenda (API ≥ Sep 2026)
  hearing?: boolean;
  latest_update: { date: string; text: string } | null;
  evaluation_slug: string | null;
}

export interface UpcomingDetail extends UpcomingEvent {
  has_agenda_text: boolean;
  topics: UpcomingAgendaTopic[];
}

export interface DiscussionPoint {
  meeting_id: number;
  date: string;
  title: string;
  body: string;
  seconds: number;
}

export interface EntityDetail {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  status_source: StatusSource | null;
  profile: EntityProfileInfo | null;
  has_wiki: boolean;
  official: CityProjectOfficial | null;
  location: { lat: number; lng: number; source: "city" | "geocode" } | null;
  related: RelatedEntity[];
  discussion: DiscussionPoint[];
  upcoming: UpcomingEvent[];
  timeline: TimelineEntry[];
  /** the history grouped by the project each row belongs to (see the API) */
  threads: EntityThread[];
}

export interface EntityThread {
  slug: string;
  name: string;
  current_status: string | null;
  official_status: string | null;
  project_type: string | null;
  official_slug: string | null;
  lead: string | null;
  rows: number[]; // indices into timeline
  last_date: string;
}

export interface CityProjectOfficial {
  slug: string;
  has_evaluation: boolean;
  name: string;
  project_type: string | null;
  division: string | null;
  official_status: string | null;
  description: string | null;
  requests: string | null;
  address: string | null;
  applicant: string | null;
  planner_name: string | null;
  planner_phone: string | null;
  planner_email: string | null;
  detail_url: string;
  image_url: string | null;
  documents: { label: string; url: string }[];
  official_timeline: string[];
  lat: number | null;
  lng: number | null;
  synced_at: string | null;
}

export interface CityProjectSummary {
  // "official": synced from the city's development directory;
  // "meetings": a project entity surfaced from council-meeting context
  source: "official" | "meetings";
  // meeting-derived rows are classified: "development" (built environment)
  // or "civic" (plans, contracts, studies, programs)
  category?: "development" | "civic" | null;
  slug: string | null;
  name: string;
  project_type: string | null;
  division: string | null;
  official_status: string | null;
  description: string | null;
  address: string | null;
  applicant: string | null;
  detail_url: string | null;
  image_url: string | null;
  entity_slug: string | null;
  entity_status: string | null;
  lat: number | null;
  lng: number | null;
  synced_at: string | null;
  has_evaluation: boolean;
  no_analysis_reason?: string | null;
  has_wiki: boolean;
  wiki_pushed_at: string | null;
}

/** GET /development/{slug} — the tab-shell payload: the full official record
 * plus which views (wiki / analysis / documents) exist for the project. */
export interface CityProjectDetail {
  slug: string;
  name: string;
  entity_slug: string | null;
  entity_status: string | null;
  project_type: string | null;
  division: string | null;
  official_status: string | null;
  description: string | null;
  requests: string | null;
  address: string | null;
  applicant: string | null;
  planner_name: string | null;
  planner_phone: string | null;
  planner_email: string | null;
  detail_url: string;
  image_url: string | null;
  documents: { label: string; url: string }[];
  official_timeline: string[];
  lat: number | null;
  lng: number | null;
  synced_at: string | null;
  has_wiki: boolean;
  wiki_pushed_at: string | null;
  evaluation_status: "extracted" | "confirmed" | "computed" | "synthesized" | null;
  has_evaluation: boolean;
  no_analysis_reason: string | null;
}

export interface ImpactProvenance {
  source_name: string;
  url: string;
  vintage: string;
  retrieved_at: string;
  notes: string | null;
}

export interface ImpactAssumption {
  key: string;
  value: number;
  low: number;
  high: number;
  basis: ImpactProvenance | string;
  rationale: string;
}

export interface ImpactAdjustTerm {
  value: number;
  exps: Record<string, number>;
  // what the piece IS ("Personal property tax"); null on rows computed
  // before terms carried labels
  label?: string | null;
}

export interface ImpactMetric {
  module: string;
  name: string;
  value: number;
  unit: string;
  low: number | null;
  high: number | null;
  provenance: ImpactProvenance[];
  assumptions: string[];
  method: string;
  headline: boolean;
  // exact client-side recompute model: adjusted value = sum of term.value x
  // prod((adjusted[k]/baseline[k])^exps[k]); absent = not client-adjustable
  adjust?: ImpactAdjustTerm[] | null;
}

export interface ProjectEvaluation {
  slug: string;
  name: string;
  entity_slug: string | null;
  has_wiki: boolean;
  official_status: string | null;
  detail_url: string;
  status: string;
  spec: {
    proposed: Record<string, number | null> & { corridor?: unknown };
    existing: Record<string, number | string | null>;
    extraction_confidence: Record<string, string>;
    extraction_quotes: Record<string, string>;
    extraction_notes: string[];
    parcels: string[];
  } & Record<string, unknown>;
  report_markdown: string;
  metrics: ImpactMetric[];
  narrative_notes: string[];
  assumptions: ImpactAssumption[];
  sources: ImpactProvenance[];
  map_layers: Record<string, GeoJSON.FeatureCollection>;
  report_model: string | null;
  report_prompt_version: string | null;
  synthesized_at: string | null;
}

/** The API's reading of a page's OKF v0.2 trust and lifecycle frontmatter
 * (api/app/wiki.py trust_block). */
export interface WikiTrust {
  producer: string | null;
  producer_kind: "pipeline" | "curator" | "human" | null;
  tier: "unverified" | "machine-confirmed" | "human-reviewed";
  verified_by: string | null;
  verified_at: string | null;
  edited_since_review: boolean;
  stale_after: string | null;
  stale: boolean;
}

export interface WikiPageInfo {
  page: string;
  path: string;
  title: string;
  type: string | null;
  description: string | null;
  timestamp: string | null;
  trust?: WikiTrust;
  frontmatter: Record<string, unknown>;
  body: string;
}

export interface ProjectWiki {
  entity_slug: string;
  official_slug?: string;
  name: string;
  pages: WikiPageInfo[];
  log: string | null;
  pushed_at: string | null;
}

export interface MemberLastNo {
  date: string;
  meeting_id: number;
  item_label: string | null;
  subject: string | null;
  motion_result: string | null;
}

export interface MemberSummary {
  slug: string;
  name: string;
  roles: string[];
  is_current: boolean;
  votes_cast: number;
  last_vote: string | null;
  vote_stats: Record<string, number>; // yes | no | abstain | absent
  with_outcome_pct: number | null; // share of yes/no votes cast on the winning side
  last_no: MemberLastNo | null;
}

export interface MemberVoteTopic {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
}

export interface MemberVote {
  date: string;
  meeting_id: number;
  meeting_title: string;
  body: string;
  item_label: string | null;
  item_title: string | null;
  description: string | null;
  motion_result: string | null;
  vote: string;
  tally: Record<string, number>; // the whole body's yes | no | abstain | absent on this motion
  contested: boolean; // someone voted no
  in_minority: boolean; // no on a motion that passed, or yes on one that failed
  breakdown: Record<string, string>; // last name -> cast, as the minutes record it
  category: string; // consent | hearing | closed | minutes | appointment | budget | ordinance | resolution | contract | other
  topics: MemberVoteTopic[];
  watch_url: string | null;
}

export interface MemberCommentaryEntry {
  topic_slug: string;
  topic_name: string;
  topic_status: string | null;
  summary: string;
}

export interface MemberRecord {
  votes: number;
  meetings: number;
  first_vote: string | null;
  last_vote: string | null;
  with_outcome_pct: number | null;
  contested: number;
  minority: { total: number; no_on_passed: number; yes_on_failed: number };
  close_votes: { total: number; lost: number }; // decided by one vote; lost = on the losing side
  lone_no: number;
  absent_meetings: { meeting_id: number; date: string }[];
  comparisons: boolean; // enough contested votes for alignment, splits and categories to mean something
}

export interface MemberMeeting {
  meeting_id: number;
  date: string;
  title: string;
  body: string;
  votes: number;
  no: number;
  contested: number;
  absent: number;
}

export interface MemberCategory {
  key: string;
  label: string;
  votes: number;
  no: number;
  absent: number;
}

export interface MemberMatter extends MemberVoteTopic {
  n: number;
  votes: Record<string, number>;
}

export interface MemberColleague {
  slug: string;
  name: string;
  roles: string[];
  votes_cast: number;
  no_votes: number;
  agree_pct: number | null; // share of this member's contested votes where the colleague voted the same way
  agree_n: number;
}

export interface MemberSplit {
  no: string[]; // slugs, in split_order, who voted no
  count: number;
}

export interface MemberDetail {
  slug: string;
  name: string;
  roles: string[];
  body: string | null;
  is_current: boolean;
  vote_stats: Record<string, number>;
  record: MemberRecord;
  votes: MemberVote[];
  by_meeting: MemberMeeting[]; // oldest first
  categories: MemberCategory[];
  matters: MemberMatter[];
  colleagues: MemberColleague[]; // current members of the same body, most aligned first
  split_order: string[]; // this member, then colleagues who vote regularly, by alignment
  splits: MemberSplit[];
  commentary: MemberCommentaryEntry[];
  upcoming: UpcomingEvent[];
}

export interface MapLocation {
  slug: string;
  name: string;
  entity_type: string;
  is_official_project: boolean;
  lat: number;
  lng: number;
  matched_address: string | null;
  address: string | null;
  current_status: string | null;
  official_status: string | null;
  summary: string | null;
  status_hint: string | null;
  related: RelatedEntity[];
}

export interface SearchResult {
  kind: "transcript" | "agenda_item";
  match: "keyword" | "semantic";
  meeting_id: number;
  meeting_title: string;
  body: string;
  date: string;
  item_label?: string | null;
  text: string;
  start_seconds: number | null;
  watch_url: string | null;
}

export interface SearchEntityHit {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  last_seen: string | null;
}

export interface SearchResponse {
  query: string;
  entities: SearchEntityHit[];
  results: SearchResult[];
}

export interface MeetingStats {
  days: number;
  meetings_held: number;
  hours_of_meetings: number;
  votes_taken: number;
  motions_passed: number;
  motions_failed: number;
}

export interface HotTopic {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  seconds: number;
  chunk_mentions: number;
  per_meeting: Record<string, number>;
}

export interface HotTopicsResponse {
  meetings: { id: number; title: string; date: string }[];
  // every timed transcript second across those meetings: the denominator for share of time
  window_seconds: number;
  topics: HotTopic[];
}

export interface Citation {
  index: number;
  kind: string;
  date: string;
  meeting_id: number;
  meeting_title: string;
  agenda_item_label: string | null;
  start_seconds: number | null;
  link: string | null;
  excerpt: string;
}

/** A tracked record the answer is about: the topics on the cited agenda
 * items, most-cited first. */
export interface AskTopic {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  official_slug: string | null;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  topics?: AskTopic[];
}

export interface TranscriptSegment {
  id: number;
  start_seconds: number | null;
  end_seconds: number | null;
  text: string;
  speaker_label: string | null;
  watch_url: string | null;
}

export interface MeetingTranscript {
  id: number;
  date: string;
  title: string;
  body: string;
  video_url: string | null;
  duration_seconds: number | null;
  segments: TranscriptSegment[];
  agenda_items: { id: number; label: string; title: string | null; start_seconds: number }[];
}

export interface RecordStatus {
  last_run: {
    started_at: string | null;
    finished_at: string | null;
    phase: string;
    meetings_processed: number;
    error_count: number;
    ok: boolean;
  } | null;
  latest_meeting: { id: number; date: string; title: string; body: string } | null;
  next_meeting: { event_id: string; title: string; starts_at: string } | null;
  counts: { meetings: number; meetings_transcribed: number; topics: number };
}

/** How long a fetched API payload is reused across requests. The record
 * changes once a night (plus an hourly catch-up), so five minutes of staleness
 * is invisible to readers and turns the briefing's nine API calls per view
 * into nine per five minutes. Pages stay dynamically rendered; only the data
 * layer is shared, via unstable_cache so it applies on force-dynamic routes
 * too. Errors are never cached — a blip retries on the next request. */
export const REVALIDATE_SECONDS = 300;

/** A non-2xx response from the API, with the status kept so a route can
 * treat a 404 as "no such record" without swallowing outages the same way. */
export class ApiError extends Error {
  readonly status: number;
  constructor(path: string, status: number) {
    super(`API ${path} -> ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/** FastAPI answers 404 for an unknown record and 422 for a path parameter it
 * can't parse (a non-numeric meeting id) — for a lookup, both mean "nothing
 * lives at this address". */
export function isMissingRecordStatus(status: number): boolean {
  return status === 404 || status === 422;
}

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!resp.ok) throw new ApiError(path, resp.status);
  return resp.json();
}

const cachedFetchJson = unstable_cache(fetchJson, ["councilhound-api"], {
  revalidate: REVALIDATE_SECONDS,
});

async function get<T>(path: string, opts: { fresh?: boolean } = {}): Promise<T> {
  // free-text queries would only bloat the cache with one-off keys
  return opts.fresh ? fetchJson<T>(path) : (cachedFetchJson(path) as Promise<T>);
}

export const api = {
  meetings: (params: URLSearchParams) => get<MeetingSummary[]>(`/meetings/?${params}`),
  meeting: (id: string) => get<MeetingDetail>(`/meetings/${id}`),
  transcript: (id: string) => get<MeetingTranscript>(`/meetings/${id}/transcript`),
  entities: (params: URLSearchParams) => get<EntitySummary[]>(`/entities/?${params}`),
  entity: (slug: string) => get<EntityDetail>(`/entities/${encodeURIComponent(slug)}`),
  entityCounts: () => get<EntityCounts>("/entities/counts"),
  hotTopics: (body?: string, days = 60) =>
    get<HotTopicsResponse>(`/entities/hot?days=${days}${body ? `&body=${body}` : ""}`),
  stats: (days = 30) => get<MeetingStats>(`/meetings/stats?days=${days}`),
  members: () => get<MemberSummary[]>("/members/"),
  upcoming: () => get<UpcomingEvent[]>("/meetings/upcoming"),
  upcomingDetail: (eventId: string) =>
    get<UpcomingDetail>(`/meetings/upcoming/${encodeURIComponent(eventId)}`),
  mapLocations: () => get<MapLocation[]>("/entities/map"),
  changes: (days = 7, limit = 30) =>
    get<ChangesResponse>(`/entities/changes?days=${days}&limit=${limit}`),
  near: (lat: number, lng: number, radiusM: number) =>
    get<NearbyResponse>(`/entities/near?lat=${lat}&lng=${lng}&radius_m=${radiusM}`),
  geocode: (q: string) =>
    get<GeocodeHit>(`/entities/geocode?q=${encodeURIComponent(q)}`, { fresh: true }),
  developmentProjects: (params: URLSearchParams) =>
    get<CityProjectSummary[]>(`/development/?${params}`),
  developmentProject: (slug: string) =>
    get<CityProjectDetail>(`/development/${encodeURIComponent(slug)}`),
  developmentEvaluation: (slug: string) =>
    get<ProjectEvaluation>(`/development/${encodeURIComponent(slug)}/evaluation`),
  developmentWiki: (slug: string) =>
    get<ProjectWiki>(`/development/${encodeURIComponent(slug)}/wiki`),
  entityWiki: (slug: string) => get<ProjectWiki>(`/entities/${encodeURIComponent(slug)}/wiki`),
  search: (q: string, body?: string) =>
    get<SearchResponse>(`/search/?q=${encodeURIComponent(q)}${body ? `&body=${body}` : ""}`, {
      fresh: true,
    }),
  member: (slug: string) => get<MemberDetail>(`/members/${encodeURIComponent(slug)}`),
  status: () => get<RecordStatus>("/status/"),
};

/** The bodies the tracker follows, in display order. Mirrors
 * ingestion/src/councilhound/bodies.py: `key` is the API/URL value, `label`
 * the name, `short` the noun for "Follow ... meetings". */
export const BODIES: { key: string; label: string; short: string }[] = [
  { key: "city_council", label: "City Council", short: "council" },
  { key: "planning_commission", label: "Planning Commission", short: "commission" },
  { key: "school_board", label: "School Board", short: "school board" },
  { key: "prab", label: "Parks and Recreation Advisory Board", short: "parks board" },
  { key: "hhcab", label: "Housing and Healthy Communities Advisory Board", short: "housing board" },
];

export const BODY_LABELS: Record<string, string> = Object.fromEntries(BODIES.map((b) => [b.key, b.label]));
export const BODY_SHORT: Record<string, string> = Object.fromEntries(BODIES.map((b) => [b.key, b.short]));

/** Label for a body key; unknown or missing keys read as the key itself. */
export const bodyLabel = (key: string | null | undefined): string => (key ? BODY_LABELS[key] ?? key : "");

export function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
