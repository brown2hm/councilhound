// Typed client for the CouncilHound API. Server components fetch directly
// (API_URL, in-cluster/localhost); the Ask page fetches from the browser
// (NEXT_PUBLIC_API_URL).

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface MeetingSummary {
  id: number;
  date: string;
  title: string;
  body: string;
  meeting_type: string;
  status: string;
  duration_seconds: number | null;
  agenda_item_count: number;
}

export interface VoteInfo {
  description: string | null;
  motion_result: string | null;
  vote_breakdown: Record<string, string>;
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
}

export interface MeetingDetail extends Omit<MeetingSummary, "agenda_item_count" | "status"> {
  granicus_clip_id: string;
  video_url: string | null;
  agenda_url: string | null;
  minutes_url: string | null;
  agenda_items: AgendaItemInfo[];
  documents: { doc_type: string; title: string | null; source_url: string }[];
}

export interface EntitySummary {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  update_count: number;
  last_seen: string | null;
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
  related: RelatedEntity[];
  discussion: DiscussionPoint[];
  upcoming: UpcomingEvent[];
  timeline: TimelineEntry[];
}

export interface MemberSummary {
  slug: string;
  name: string;
  roles: string[];
  votes_cast: number;
  last_vote: string | null;
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
  watch_url: string | null;
}

export interface MemberCommentaryEntry {
  topic_slug: string;
  topic_name: string;
  topic_status: string | null;
  summary: string;
}

export interface MemberDetail {
  slug: string;
  name: string;
  roles: string[];
  vote_stats: Record<string, number>;
  votes: MemberVote[];
  commentary: MemberCommentaryEntry[];
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

export interface AskResponse {
  answer: string;
  citations: Citation[];
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`API ${path} -> ${resp.status}`);
  return resp.json();
}

export const api = {
  meetings: (params: URLSearchParams) => get<MeetingSummary[]>(`/meetings/?${params}`),
  meeting: (id: string) => get<MeetingDetail>(`/meetings/${id}`),
  entities: (params: URLSearchParams) => get<EntitySummary[]>(`/entities/?${params}`),
  entity: (slug: string) => get<EntityDetail>(`/entities/${encodeURIComponent(slug)}`),
  hotTopics: (body?: string, days = 60) =>
    get<HotTopicsResponse>(`/entities/hot?days=${days}${body ? `&body=${body}` : ""}`),
  stats: (days = 30) => get<MeetingStats>(`/meetings/stats?days=${days}`),
  members: () => get<MemberSummary[]>("/members/"),
  upcoming: () => get<UpcomingEvent[]>("/meetings/upcoming"),
  member: (slug: string) => get<MemberDetail>(`/members/${encodeURIComponent(slug)}`),
};

export const BODY_LABELS: Record<string, string> = {
  city_council: "City Council",
  planning_commission: "Planning Commission",
};

export function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
