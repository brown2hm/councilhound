// Typed client for the CouncilLens API. Server components fetch directly
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
  votes: VoteInfo[];
}

export interface MeetingDetail extends Omit<MeetingSummary, "agenda_item_count" | "duration_seconds" | "status"> {
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
}

export interface EntityDetail {
  slug: string;
  name: string;
  entity_type: string;
  current_status: string | null;
  timeline: TimelineEntry[];
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
