import Link from "next/link";
import { bodyDot } from "@/components/BodyTag";
import FollowButton from "@/components/FollowButton";
import Pagination from "@/components/Pagination";
import { api, PUBLIC_API_URL, type MeetingDecision, type MeetingSummary, type UpcomingEvent } from "@/lib/api";
import { getJurisdiction, type Jurisdiction } from "@/lib/jurisdiction";

export async function generateMetadata() {
  const j = await getJurisdiction();
  return {
    title: "Meetings",
    description:
      `Every archived ${j.identity.short_name} public meeting (${j.bodies.map((b) => b.label).join(", ")}), newest first, with what each one decided and links to the agenda, recording, and transcript.`,
  };
}

/** Filter chips: a name too long for a chip gets its short noun instead
 * ("Parks Board" for the Parks and Recreation Advisory Board). */
const CHIP_MAX = 24;
const bodyChips = (j: Jurisdiction) => [
  { key: "", label: "All bodies", short: "" },
  ...j.bodies.map((b) => ({
    key: b.key,
    label: b.label.length > CHIP_MAX ? titleCase(b.short) : b.label,
    short: b.short,
  })),
];

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

const PAGE_SIZE = 40;
const SHOWN_PER_MEETING = 3;

const isCancelled = (m: MeetingSummary) => /cancell?ed/i.test(m.title);
const cleanTitle = (m: MeetingSummary) => m.title.replace(/\s*[-–]\s*cancell?ed\s*$/i, "");
const isConsent = (d: MeetingDecision) => /^consent agenda/i.test(d.title);

function duration(seconds: number | null): string | null {
  if (!seconds) return null;
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

/** Agenda titles arrive as filed ("Consideration of an ordinance amending…").
 * Drop the procedural opener and clip at a word so the row reads as a line. */
function shortTitle(title: string, max = 96): string {
  let t = title
    .replace(/^(consideration (of|to approve|to) |public hearing and council action on |public hearing on |public hearing:\s*|award of )(an? |the )?/i, "")
    .trim();
  if (t) t = t.charAt(0).toUpperCase() + t.slice(1);
  if (t.length <= max) return t;
  const cut = t.slice(0, max).replace(/\s+\S*$/, "");
  return cut.replace(/[\s,;:(–-]+$/, "") + "…";
}

function monthOf(date: string): string {
  return new Date(date + "T00:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function dayOf(date: string): number {
  return new Date(date + "T00:00:00").getDate();
}

function whenUpcoming(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString("en-US", { weekday: "short", day: "numeric" }) +
    " · " +
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
  );
}

function Dot({ body }: { body: string | null }) {
  if (!body) return null;
  return <span aria-hidden className={`mr-1.5 inline-block h-2 w-2 rounded-full ${bodyDot(body)}`} />;
}

const MARK: Record<string, { glyph: string; className: string }> = {
  passed: { glyph: "✓", className: "bg-tint-mint text-tint-mint-text" },
  failed: { glyph: "✕", className: "bg-tint-coral text-tint-coral-text" },
  other: { glyph: "·", className: "bg-strong text-muted" },
};

function Mark({ kind }: { kind: string }) {
  const m = MARK[kind] ?? MARK.other;
  return (
    <span
      aria-hidden
      className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${m.className}`}
    >
      {m.glyph}
    </span>
  );
}

function NextUp({ events }: { events: UpcomingEvent[] }) {
  const shown = events.slice(0, 4);
  if (shown.length === 0) return null;
  return (
    <section
      aria-label="Next up"
      className="mb-2 grid border-b border-hairline border-t-2 border-t-ink md:grid-cols-[150px_repeat(4,minmax(0,1fr))]"
    >
      <div className="py-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Next up</div>
      {shown.map((e) => (
        <div key={e.event_id} className="border-t border-hairline-soft px-0 py-3.5 md:border-l md:border-t-0 md:border-hairline md:px-4">
          <div className="text-[13px] font-semibold tabular-nums text-muted">
            {e.in_progress ? <span className="text-tint-coral-text">● Live now</span> : e.starts_at ? whenUpcoming(e.starts_at) : ""}
          </div>
          <Link
            href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`}
            className="mt-0.5 block text-sm font-semibold leading-snug underline-offset-2 hover:underline"
          >
            <Dot body={e.body} />
            {e.title}
          </Link>
          {e.agenda_url && (
            <a href={e.agenda_url} target="_blank" className="text-[12px] text-muted underline underline-offset-2 hover:text-ink">
              agenda
            </a>
          )}
        </div>
      ))}
    </section>
  );
}

function MeetingRow({ m }: { m: MeetingSummary }) {
  const day = dayOf(m.date);
  if (isCancelled(m)) {
    return (
      <li className="grid grid-cols-[56px_minmax(0,1fr)] items-baseline gap-4 border-t border-hairline py-3 text-muted-soft">
        <div className="text-2xl font-medium leading-none tabular-nums">{day}</div>
        <div className="text-[15px]">
          <Dot body={m.body} />
          {cleanTitle(m)}
          <span className="ml-2 rounded-full bg-strong px-2.5 py-[3px] text-xs font-medium text-body">cancelled</span>
        </div>
      </li>
    );
  }

  const votes = m.decisions ?? [];
  const ordered = [...votes.filter((d) => !isConsent(d)), ...votes.filter(isConsent)];
  const shownVotes = ordered.slice(0, SHOWN_PER_MEETING);
  const moreVotes = votes.length - shownVotes.length;
  const discussed = votes.length ? [] : (m.discussed ?? []).slice(0, SHOWN_PER_MEETING);
  const moreItems = votes.length ? 0 : Math.max(0, m.agenda_item_count - discussed.length);
  const passed = m.votes_passed ?? 0;
  const failed = m.votes_failed ?? 0;
  const lead = votes.length
    ? `${passed} passed${failed ? `, ${failed} failed` : ""}`
    : m.duration_seconds
      ? "No votes"
      : "No recording";
  const meta = [duration(m.duration_seconds), m.agenda_item_count ? `${m.agenda_item_count} items` : null].filter(Boolean).join(" · ");

  return (
    <li className="grid grid-cols-[56px_minmax(0,1fr)] gap-4 border-t border-hairline py-3.5">
      <div className="text-[26px] font-medium leading-none tracking-[-0.5px] tabular-nums">{day}</div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="text-base font-semibold leading-[1.3]">
            <Link href={`/meetings/${m.id}`} className="underline-offset-2 hover:underline">
              <Dot body={m.body} />
              {cleanTitle(m)}
            </Link>
            <span className="ml-2 text-[13px] font-medium text-muted">{lead}</span>
          </div>
          <div className="whitespace-nowrap text-[12px] tabular-nums text-muted">
            {meta}
            {m.duration_seconds ? (
              <>
                {meta ? " · " : ""}
                <Link href={`/meetings/${m.id}/transcript`} className="underline underline-offset-2 hover:text-ink">
                  Transcript
                </Link>
              </>
            ) : null}
          </div>
        </div>
        {(shownVotes.length > 0 || discussed.length > 0) && (
          <ul className="mt-1.5 flex flex-col gap-[3px] text-sm text-body">
            {shownVotes.map((d, i) => (
              <li key={i} className="flex items-baseline gap-2 leading-[1.45]">
                <Mark kind={d.result ?? "other"} />
                {d.label && <span className="text-[12px] tabular-nums text-muted">{d.label}</span>}
                <span>{shortTitle(d.title)}</span>
              </li>
            ))}
            {discussed.map((t, i) => (
              <li key={i} className="flex items-baseline gap-2 leading-[1.45]">
                <Mark kind="other" />
                <span>{shortTitle(t)}</span>
              </li>
            ))}
            {moreVotes > 0 && (
              <li className="pl-6 text-[13px] text-muted">
                +{moreVotes} more vote{moreVotes === 1 ? "" : "s"}
              </li>
            )}
            {moreItems > 0 && (
              <li className="pl-6 text-[13px] text-muted">
                +{moreItems} more item{moreItems === 1 ? "" : "s"}
              </li>
            )}
          </ul>
        )}
      </div>
    </li>
  );
}

export default async function MeetingsPage({
  searchParams,
}: {
  searchParams: { body?: string; page?: string };
}) {
  const BODIES = bodyChips(await getJurisdiction());
  const body = searchParams.body ?? "";
  const page = Math.max(1, Number(searchParams.page) || 1);
  // fetch one extra row to learn whether another page exists
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE + 1),
    offset: String((page - 1) * PAGE_SIZE),
    include_decisions: "true",
  });
  if (body) params.set("body", body);
  const [fetched, upcoming] = await Promise.all([
    api.meetings(params),
    page === 1 ? api.upcoming().catch(() => [] as UpcomingEvent[]) : Promise.resolve([] as UpcomingEvent[]),
  ]);
  const hasMore = fetched.length > PAGE_SIZE;
  const meetings = fetched.slice(0, PAGE_SIZE);

  // the month rail: consecutive runs of the same month
  const months: { key: string; rows: MeetingSummary[] }[] = [];
  for (const m of meetings) {
    const key = monthOf(m.date);
    const last = months[months.length - 1];
    if (last && last.key === key) last.rows.push(m);
    else months.push({ key, rows: [m] });
  }

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div>
          <h1 className="text-[32px] font-medium tracking-[-0.5px]">Meetings</h1>
          <p className="mt-1 text-sm text-muted">Every archived meeting, newest first, with what each one decided.</p>
        </div>
        <div className="flex flex-col items-start gap-2.5 sm:items-end">
          <div className="flex flex-wrap gap-1.5">
            {BODIES.map((b) => (
              <Link
                key={b.key}
                href={b.key ? `/meetings?body=${b.key}` : "/meetings"}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-[7px] text-[13px] font-medium ${
                  b.key === body ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
                }`}
              >
                {b.key && <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${bodyDot(b.key)}`} />}
                {b.label}
              </Link>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
            <span>Get new meetings by email:</span>
            {BODIES.filter((b) => b.key && (!body || b.key === body)).map((b) => (
              <FollowButton
                key={b.key}
                target={{ kind: "body", body: b.key }}
                label={b.short}
                size="sm"
              />
            ))}
            <span aria-hidden>·</span>
            <a href={`${PUBLIC_API_URL}/meetings/upcoming.ics`} className="font-semibold underline underline-offset-2 hover:text-ink">
              calendar feed
            </a>
          </div>
        </div>
      </div>

      {page === 1 && <NextUp events={upcoming} />}

      {months.map((group) => (
        <section key={group.key} className="grid gap-y-1 pt-7 md:grid-cols-[150px_minmax(0,1fr)]">
          <h2 className="text-xs font-semibold uppercase tracking-[1.5px] text-muted md:pt-5">{group.key}</h2>
          <ul className="min-w-0">
            {group.rows.map((m) => (
              <MeetingRow key={m.id} m={m} />
            ))}
          </ul>
        </section>
      ))}
      {meetings.length === 0 && (
        <p className="mt-6 rounded-2xl border border-dashed border-hairline p-6 text-sm text-muted">
          No meetings on this page. Back to the{" "}
          <Link href="/meetings" className="font-semibold underline underline-offset-2 hover:text-ink">
            most recent
          </Link>
          .
        </p>
      )}

      <Pagination page={page} hasMore={hasMore} basePath="/meetings" params={{ body: body || undefined }} />
    </div>
  );
}
