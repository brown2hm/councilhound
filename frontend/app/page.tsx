import Image from "next/image";
import Link from "next/link";
import BodyTag, { bodyDot } from "@/components/BodyTag";
import FollowButton from "@/components/FollowButton";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  BODY_LABELS,
  formatDate,
  PUBLIC_API_URL,
  type ChangesResponse,
  type EntityChange,
  type HotTopic,
  type HotTopicsResponse,
  type MeetingDetail,
  type MeetingStats,
  type UpcomingAgendaTopic,
  type UpcomingDetail,
  type UpcomingEvent,
} from "@/lib/api";
import { voteShape } from "@/lib/briefing";

export const dynamic = "force-dynamic";

// The briefing is a front page, not a dashboard: one lede, a line of
// figures, then ruled ledgers. Every row carries a noun and a reason.

interface Decision {
  badge: string; // PASSED | FAILED | CONTINUED | RECOMMENDED
  tally: string; // "unanimous" | "4–2" | "5–0–1" | "" when the record has no count
  split: boolean; // at least one no vote
  dissent: string[]; // last names recorded as voting no
  tint: string;
  body: string;
  date: string;
  title: string;
  text: string;
  meetingId: number;
}

const TINTS: Record<string, string> = {
  approved: "bg-tint-mint text-tint-mint-text",
  split: "bg-tint-ochre text-tint-ochre-text",
  denied: "bg-tint-coral text-tint-coral-text",
  proposed: "bg-tint-lavender text-tint-lavender-text",
  deferred: "bg-strong text-body",
};

function deriveDecisions(details: MeetingDetail[]): Decision[] {
  const decisions: Decision[] = [];
  for (const m of details) {
    for (const item of m.agenda_items) {
      if (!item.title) continue;
      // procedural housekeeping doesn't belong on the front page
      if (/\b(minutes|remote participation|adoption of (the )?agenda|adjourn)\b/i.test(item.title)) {
        continue;
      }
      const vote = item.votes[0];
      const text = item.outcome ?? vote?.description ?? "";
      if (vote) {
        const shape = voteShape(vote, item.outcome);
        const badge =
          vote.motion_result === "passed" ? "PASSED" : vote.motion_result === "failed" ? "FAILED" : "CONTINUED";
        const tint =
          vote.motion_result === "passed"
            ? shape.split
              ? TINTS.split
              : TINTS.approved
            : vote.motion_result === "failed"
              ? TINTS.denied
              : TINTS.deferred;
        const dissent = Object.entries(vote.vote_breakdown ?? {})
          .filter(([, cast]) => cast === "no")
          .map(([name]) => name);
        decisions.push({
          badge,
          tally: shape.tally,
          split: shape.split,
          dissent,
          tint,
          body: m.body,
          date: m.date,
          title: item.title,
          text,
          meetingId: m.id,
        });
      } else if (item.outcome && /recommend/i.test(item.outcome) && m.body === "planning_commission") {
        decisions.push({
          badge: "RECOMMENDED",
          tally: "",
          split: false,
          dissent: [],
          tint: TINTS.proposed,
          body: m.body,
          date: m.date,
          title: item.title,
          text: item.outcome,
          meetingId: m.id,
        });
      }
    }
  }
  return decisions;
}

const isConsent = (d: Decision) => /^consent agenda/i.test(d.title);

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const word = (n: number) => WORDS[n] ?? String(n);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const plural = (n: number, noun: string) => `${word(n)} ${noun}${n === 1 ? "" : "s"}`;
const clip = (text: string, n: number) => (text.length > n ? text.slice(0, n).trimEnd() + "…" : text);

/** The agenda excerpt is a fixed window around the name: it opens mid-word
 * and runs on into "Staff Report Presentation 9. Second public comment…".
 * Trim to the sentence that names the item. */
function agendaWords(context: string, name: string): string {
  let text = context;
  if (text.startsWith("…")) text = "…" + text.slice(1).replace(/^\S*\s+/, "");
  const at = text.toLowerCase().indexOf(name.toLowerCase());
  const tail = at >= 0 ? text.slice(at + name.length) : text;
  const stop = tail.search(/\s(staff report|presentation\b|motion\b)|\s\d{1,2}\.\s+[A-Z(]|\.\s+[A-Z]/);
  if (stop >= 0) text = text.slice(0, (at >= 0 ? at + name.length : 0) + stop) + (/[.!?]$/.test(tail.slice(0, stop)) ? "" : ".");
  return clip(text, 240);
}
// update texts open with the agenda label the extractor saw: "[7b] Carports were…"
const unlabel = (text: string) => text.replace(/^\s*\[[^\]]*\]\s*/, "");

/** "five measures passed, all unanimous, and one failed" — lowercase, no period. */
function voteSentence(decisions: Decision[]): string {
  const passed = decisions.filter((d) => d.badge === "PASSED");
  const failed = decisions.filter((d) => d.badge === "FAILED").length;
  const other = decisions.length - passed.length - failed;
  const parts: string[] = [];
  if (passed.length) parts.push(`${plural(passed.length, "measure")} passed`);
  if (failed) parts.push(`${word(failed)} failed`);
  if (other) parts.push(`${word(other)} still in motion`);
  if (!parts.length) return "";
  let s = parts.length > 1 ? parts.slice(0, -1).join(", ") + ", and " + parts.at(-1) : parts[0];
  const voted = decisions.filter((d) => d.badge === "PASSED" || d.badge === "FAILED");
  const split = voted.filter((d) => d.split).length;
  const known = voted.filter((d) => d.tally).length;
  if (split) s += split === 1 ? ", one on a split vote" : `, ${word(split)} on split votes`;
  else if (known === voted.length && voted.length > 1) s += ", all unanimous";
  else if (known === voted.length && voted.length === 1) s += ", unanimously";
  return s;
}

function countHeadline(decisions: Decision[], changes: ChangesResponse): string {
  const moved = changes.changes.filter((c) => c.kind === "status_change").length;
  const fresh = changes.changes.length - moved;
  const sentences: string[] = [];
  const votes = voteSentence(decisions);
  if (votes) sentences.push(cap(votes) + ".");
  if (moved) sentences.push(cap(plural(moved, "topic")) + " changed status.");
  if (!sentences.length && fresh) sentences.push(cap(plural(fresh, "topic")) + " new to the record.");
  return sentences.length ? sentences.join(" ") : "The latest from city hall.";
}

const meetingNames = (details: MeetingDetail[]) =>
  details.map((m) => `the ${BODY_LABELS[m.body] ?? m.body} meeting on ${formatDate(m.date)}`).join(" and ");

/** YYYY-MM-DD in the city's own time zone, so "today" and "tomorrow" hold
 * whether the page renders in Virginia or on a UTC box. */
const CITY_TZ = "America/New_York";
const localDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: CITY_TZ });
const daysBetween = (fromDay: string, toDay: string) =>
  Math.round((Date.parse(toDay) - Date.parse(fromDay)) / 86_400_000);
const dayOf = (iso: string) => iso.slice(0, 10);
const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const fmtWeekday = (iso: string) => new Date(iso).toLocaleDateString("en-US", { weekday: "long" });
const fmtShort = (iso: string) =>
  new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** "today", "tomorrow", "Monday", or "Mon, Sep 22" once it's more than a week out. */
function relativeDay(iso: string, today: string): string {
  const gap = daysBetween(today, dayOf(iso));
  if (gap <= 0) return "today";
  if (gap === 1) return "tomorrow";
  if (gap < 7) return fmtWeekday(iso);
  return new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// The docket: upcoming meetings with what's on them

// agenda furniture that is tracked as a topic but is never the news
const BOILERPLATE =
  /personnel|closed (session|meeting)|city hall|appointment|proclamation|heritage month|safety month|\bminutes\b|adjourn|call to order|comment period|pledge|council chambers/i;
const substantiveTopic = (t: UpcomingAgendaTopic) => !BOILERPLATE.test(t.name);
// what's concretely being decided outranks the plan it's decided under
const TYPE_RANK: Record<string, number> = { location: 0, project: 1, case_number: 2, ordinance: 3, resolution: 4 };
const typeRank = (t: UpcomingAgendaTopic) => TYPE_RANK[t.entity_type] ?? 5;
const byConcreteness = (a: UpcomingAgendaTopic, b: UpcomingAgendaTopic) =>
  typeRank(a) - typeRank(b) || b.update_count - a.update_count;

interface DocketEntry {
  event: UpcomingEvent;
  detail: UpcomingDetail | null;
  hearings: UpcomingAgendaTopic[];
  rest: UpcomingAgendaTopic[];
}

function docketEntry(event: UpcomingEvent, detail: UpcomingDetail | null): DocketEntry {
  const topics = (detail?.topics ?? []).filter(substantiveTopic);
  const hearings = topics.filter((t) => t.hearing).sort(byConcreteness);
  const rest = topics.filter((t) => !t.hearing).sort((a, b) => b.update_count - a.update_count);
  return { event, detail, hearings, rest };
}

// ---------------------------------------------------------------------------
// The lede

interface Lede {
  eyebrow: string;
  headline: React.ReactNode;
  quote?: string; // the agenda's own words
  meta: React.ReactNode;
}

function hearingLede(entry: DocketEntry, today: string): Lede {
  const e = entry.event;
  const lead = entry.hearings[0];
  const others = entry.hearings.slice(1, 4);
  const who = e.body ? BODY_LABELS[e.body] ?? e.body : e.title;
  const when = e.starts_at ? `${relativeDay(e.starts_at, today)} at ${fmtTime(e.starts_at)}` : "soon";
  return {
    eyebrow: `Public hearing · ${who} · ${e.starts_at ? `${fmtShort(e.starts_at)}, ${fmtTime(e.starts_at)}` : ""}`,
    headline: (
      <>
        {who} holds a public hearing {when} on{" "}
        <Link href={`/topics/${lead.slug}`} className="underline decoration-mint/60 decoration-2 underline-offset-[6px] hover:decoration-mint">
          {lead.name}
        </Link>
        .
      </>
    ),
    quote: lead.agenda_context ? agendaWords(lead.agenda_context, lead.name) : undefined,
    meta: (
      <>
        {others.length > 0 && (
          <>
            Also at the hearing:{" "}
            {others.map((t, i) => (
              <span key={t.slug}>
                {i > 0 && ", "}
                <Link href={`/topics/${t.slug}`} className="underline underline-offset-2 hover:text-white">
                  {t.name}
                </Link>
              </span>
            ))}
            {". "}
          </>
        )}
        {lead.update_count > 0 && (
          <>
            {lead.update_count} prior discussion{lead.update_count === 1 ? "" : "s"} on the record.{" "}
          </>
        )}
        {lead.evaluation_slug && (
          <>
            <Link href={`/development/${lead.evaluation_slug}/analysis`} className="underline underline-offset-2 hover:text-white">
              impact analysis
            </Link>
            {" · "}
          </>
        )}
        <Link href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`} className="underline underline-offset-2 hover:text-white">
          the pre-meeting brief
        </Link>
        {e.agenda_url && (
          <>
            {" · "}
            <a href={e.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-white">
              agenda
            </a>
          </>
        )}
      </>
    ),
  };
}

function contestedLede(d: Decision): Lede {
  const who = BODY_LABELS[d.body] ?? d.body;
  const verb = d.badge === "FAILED" ? "rejected" : `split ${d.tally || ""} on`.replace("  ", " ");
  return {
    eyebrow: `${d.badge === "FAILED" ? "Failed vote" : "Split vote"} · ${who} · ${fmtShort(d.date)}`,
    headline: (
      <>
        {who} {verb}{" "}
        <Link href={`/meetings/${d.meetingId}`} className="underline decoration-mint/60 decoration-2 underline-offset-[6px] hover:decoration-mint">
          {clip(d.title, 120)}
        </Link>
        .
      </>
    ),
    quote: d.text ? clip(d.text, 220) : undefined,
    meta: (
      <>
        {d.dissent.length > 0 && <>Voting no: {d.dissent.join(", ")}. </>}
        <Link href={`/meetings/${d.meetingId}`} className="underline underline-offset-2 hover:text-white">
          the full meeting
        </Link>
      </>
    ),
  };
}

function meetingLede(entry: DocketEntry, today: string): Lede {
  const e = entry.event;
  const who = e.body ? BODY_LABELS[e.body] ?? e.body : e.title;
  const top = entry.rest.slice(0, 3);
  return {
    eyebrow: `Next meeting · ${who} · ${e.starts_at ? `${fmtShort(e.starts_at)}, ${fmtTime(e.starts_at)}` : ""}`,
    headline: (
      <>
        {who} meets {e.starts_at ? relativeDay(e.starts_at, today) : "soon"}
        {e.starts_at ? ` at ${fmtTime(e.starts_at)}` : ""}
        {top.length > 0 && (
          <>
            {" "}
            with{" "}
            {top.map((t, i) => (
              <span key={t.slug}>
                {i > 0 && (i === top.length - 1 ? " and " : ", ")}
                <Link href={`/topics/${t.slug}`} className="underline decoration-mint/60 decoration-2 underline-offset-[6px] hover:decoration-mint">
                  {t.name}
                </Link>
              </span>
            ))}{" "}
            on the agenda
          </>
        )}
        .
      </>
    ),
    meta: (
      <>
        <Link href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`} className="underline underline-offset-2 hover:text-white">
          the pre-meeting brief
        </Link>
        {e.agenda_url && (
          <>
            {" · "}
            <a href={e.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-white">
              agenda
            </a>
          </>
        )}
      </>
    ),
  };
}

function countLede(decisions: Decision[], changes: ChangesResponse, details: MeetingDetail[], stale: boolean): Lede {
  const named = meetingNames(details);
  return {
    eyebrow: stale ? `The last meeting · ${details[0] ? fmtShort(details[0].date) : ""}` : `The last ${changes.days} days`,
    headline: countHeadline(decisions, changes),
    meta: details.length
      ? stale
        ? `No meetings in the last ${changes.days} days. The record below is from ${named}.`
        : `From ${named}.`
      : "",
  };
}

// ---------------------------------------------------------------------------
// Pieces

function Masthead({ latest }: { latest: string }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-ink pb-3">
      <div className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        The briefing · Week of {latest} · City of Fairfax, VA
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-end gap-3 sm:flex-none">
        <form
          action="/ask"
          method="get"
          aria-label="Ask the hound"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-hairline bg-canvas py-1 pl-2.5 pr-1 sm:w-[380px] sm:flex-none"
        >
          <Image src="/brand/hound.png" alt="" width={34} height={30} className="h-5 w-auto shrink-0" />
          <input
            name="q"
            placeholder="What has the council decided about affordable housing?"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-muted-soft"
          />
          <button className="shrink-0 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold text-white hover:bg-ink-active">
            Ask
          </button>
        </form>
        <FollowButton target={{ kind: "briefing" }} label="Get this weekly" size="sm" />
      </div>
    </div>
  );
}

function LedeBlock({ lede }: { lede: Lede }) {
  return (
    <section className="rounded-2xl bg-teal px-6 py-6 text-white sm:px-8 sm:py-7">
      <div className="mb-3 text-xs font-semibold uppercase tracking-[1.5px] text-mint">{lede.eyebrow}</div>
      <h1 className="max-w-[960px] font-display text-[30px] font-medium leading-[1.12] tracking-[-0.3px] [text-wrap:balance] sm:text-[40px]">
        {lede.headline}
      </h1>
      {lede.quote && (
        <p className="mt-4 max-w-[820px] border-l-2 border-mint/50 pl-4 font-display text-[17px] italic leading-snug text-white/85">
          {lede.quote}
        </p>
      )}
      {lede.meta && <p className="mt-4 max-w-[860px] text-[13px] leading-relaxed text-white/70">{lede.meta}</p>}
    </section>
  );
}

interface Figure {
  value: string;
  label: string;
  href?: string;
}

function Figures({ figures }: { figures: Figure[] }) {
  return (
    <ul className="mb-8 grid grid-cols-2 gap-x-6 gap-y-3 border-b border-hairline py-3 sm:grid-cols-3 lg:grid-cols-6">
      {figures.map((f) => {
        const inner = (
          <>
            <span className="text-[22px] font-semibold leading-none tracking-[-0.5px] tabular-nums">{f.value}</span>
            <span className="mt-1 block text-[12px] leading-snug text-muted">{f.label}</span>
          </>
        );
        return (
          <li key={f.label} className="min-w-0">
            {f.href ? (
              <Link href={f.href} className="block hover:underline">
                {inner}
              </Link>
            ) : (
              inner
            )}
          </li>
        );
      })}
    </ul>
  );
}

function SectionHead({ title, aside }: { title: string; aside?: React.ReactNode }) {
  return (
    <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3 border-b-2 border-ink pb-1.5">
      <h2 className="font-display text-[24px] font-medium leading-none tracking-[-0.2px]">{title}</h2>
      {aside && <span className="flex gap-3 text-[12px] font-semibold text-muted">{aside}</span>}
    </div>
  );
}

const hearingPill = (
  <span className="rounded-full bg-tint-coral px-2 py-[2px] text-[11px] font-semibold uppercase tracking-[0.5px] text-tint-coral-text">
    hearing
  </span>
);

function Docket({
  entries,
  advisory,
  today,
}: {
  entries: DocketEntry[];
  advisory: UpcomingEvent[];
  today: string;
}) {
  if (entries.length === 0 && advisory.length === 0) return null;
  const when = (e: UpcomingEvent) =>
    e.in_progress ? (
      <span className="font-semibold text-tint-coral-text">● Live now</span>
    ) : e.starts_at ? (
      <>
        {cap(relativeDay(e.starts_at, today))}
        <span className="text-muted"> · {fmtTime(e.starts_at)}</span>
      </>
    ) : null;
  return (
    <section>
      <SectionHead
        title="On the docket"
        aside={
          <>
            <Link href="/meetings" className="underline underline-offset-2 hover:text-ink">
              all upcoming
            </Link>
            <a href={`${PUBLIC_API_URL}/meetings/upcoming.ics`} className="underline underline-offset-2 hover:text-ink">
              calendar feed
            </a>
          </>
        }
      />
      <ul className="divide-y divide-hairline">
        {entries.map(({ event: e, hearings, rest, detail }) => {
          const shown = [...hearings, ...rest].slice(0, 5);
          const more = hearings.length + rest.length - shown.length;
          return (
            <li key={e.event_id} className="grid gap-x-5 gap-y-1 py-3 sm:grid-cols-[120px_1fr]">
              <div className="text-[13px] leading-snug">
                <div className="font-semibold">{when(e)}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-muted">
                  {e.body && <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${bodyDot(e.body)}`} />}
                  <Link
                    href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`}
                    className="underline-offset-2 hover:underline"
                  >
                    {e.body ? BODY_LABELS[e.body] ?? e.body : e.title}
                  </Link>
                </div>
              </div>
              <div className="min-w-0">
                {shown.length > 0 ? (
                  // one item per line: the docket reads as a list, not a sentence
                  <ul className="text-[13px] leading-snug">
                    {shown.map((t) => (
                      <li key={t.slug} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-[3px]">
                        <Link
                          href={`/topics/${t.slug}`}
                          className={`underline-offset-2 hover:underline ${t.hearing ? "font-semibold" : ""}`}
                        >
                          {t.name}
                        </Link>
                        {t.hearing ? hearingPill : <StatusBadge status={t.current_status} variant="outline" />}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-[13px] text-muted">
                    {e.title}
                    {detail && !detail.has_agenda_text ? " · agenda not posted yet" : " · nothing tracked on this agenda"}
                  </span>
                )}
                {(more > 0 || e.agenda_url) && (
                  <div className="mt-1 flex gap-3 text-[12px] font-semibold text-muted">
                    {more > 0 && (
                      <Link
                        href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`}
                        className="underline underline-offset-2 hover:text-ink"
                      >
                        and {more} more
                      </Link>
                    )}
                    {e.agenda_url && (
                      <a href={e.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
                        agenda
                      </a>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        })}
        {advisory.length > 0 && (
          <li className="grid gap-x-5 gap-y-1 py-3 text-[13px] sm:grid-cols-[120px_1fr]">
            <div className="font-semibold text-muted">Also ahead</div>
            <div className="leading-relaxed text-muted">
              {advisory.map((e, i) => (
                <span key={e.event_id}>
                  {i > 0 && " · "}
                  <Link
                    href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`}
                    className="text-body underline-offset-2 hover:underline"
                  >
                    {e.title.replace(/\s+(Regular )?Meeting$/i, "")}
                  </Link>
                  {e.starts_at && <> ({relativeDay(e.starts_at, today)})</>}
                </span>
              ))}
            </div>
          </li>
        )}
      </ul>
    </section>
  );
}

type Row =
  // a status move, carrying the vote that caused it when the record has both
  | { kind: "move"; c: EntityChange; vote?: Decision }
  | { kind: "vote"; d: Decision };

function Kind({ row }: { row: Row }) {
  if (row.kind === "move") {
    return (
      <span className="flex flex-wrap items-center gap-1.5 text-[13px]">
        {row.c.from_status && (
          <>
            <StatusBadge status={row.c.from_status} variant="outline" />
            <span aria-hidden className="font-semibold text-ink">→</span>
          </>
        )}
        <StatusBadge status={row.c.to_status} />
        {row.vote?.tally && <span className="text-[12px] text-muted">· {row.vote.tally}</span>}
      </span>
    );
  }
  const d = row.d;
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-[3px] text-xs font-semibold ${d.tint}`}>
      {d.badge}
      {d.tally && <span className="font-medium"> · {d.tally}</span>}
    </span>
  );
}

function Moved({ rows, fresh, days }: { rows: Row[]; fresh: EntityChange[]; days: number }) {
  // where the first appearances came from: one sentence, not fifteen rows
  const byMeeting = new Map<number, { n: number; body: string; date: string }>();
  for (const c of fresh) {
    const cur = byMeeting.get(c.meeting_id) ?? { n: 0, body: c.body, date: c.date };
    cur.n += 1;
    byMeeting.set(c.meeting_id, cur);
  }
  const top = Array.from(byMeeting.values()).sort((a, b) => b.n - a.n)[0];
  return (
    <section>
      <SectionHead
        title={`What moved, last ${days} days`}
        aside={
          <>
            <Link href={`/topics?days=${days}`} className="underline underline-offset-2 hover:text-ink">
              all activity
            </Link>
            <a href={`${PUBLIC_API_URL}/entities/changes.atom`} className="underline underline-offset-2 hover:text-ink">
              feed
            </a>
          </>
        }
      />
      {rows.length === 0 && fresh.length === 0 ? (
        <p className="py-3 text-sm text-muted">No decisions or status changes in the window.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {rows.map((row, i) => {
            const href =
              row.kind === "move" ? `/topics/${row.c.slug}#m-${row.c.meeting_id}` : `/meetings/${row.d.meetingId}`;
            const name = row.kind === "move" ? row.c.name : row.d.title;
            const vote = row.kind === "move" ? row.vote : row.d;
            const why = [
              clip(row.kind === "move" ? unlabel(row.c.update_text) : row.d.text, 150),
              vote?.dissent.length ? `No: ${vote.dissent.join(", ")}.` : "",
            ]
              .filter(Boolean)
              .join(" ");
            const body = row.kind === "move" ? row.c.body : row.d.body;
            const date = row.kind === "move" ? row.c.date : row.d.date;
            return (
              <li key={i} className="grid gap-x-5 gap-y-1 py-3 md:grid-cols-[minmax(0,1.1fr)_auto_minmax(0,1.6fr)_110px]">
                <Link href={href} className="min-w-0 text-[15px] font-semibold leading-snug underline-offset-2 hover:underline">
                  {clip(name, 90)}
                </Link>
                <div className="md:pt-0.5">
                  <Kind row={row} />
                </div>
                <div className="min-w-0 text-[13px] leading-relaxed text-body">{why}</div>
                <div className="text-[12px] text-muted md:text-right">
                  <BodyTag body={body} className="md:hidden" />
                  <span className="md:hidden"> · </span>
                  <span className="hidden md:inline">{BODY_LABELS[body]?.replace("City ", "") ?? body} · </span>
                  {fmtShort(date)}
                </div>
              </li>
            );
          })}
          {fresh.length > 0 && (
            <li className="py-3 text-[13px] text-muted">
              <Link href={`/topics?days=${days}`} className="underline-offset-2 hover:text-ink hover:underline">
                {cap(plural(fresh.length, "topic"))} first appeared on the record
                {top && top.n > 1 && byMeeting.size > 1
                  ? `, ${top.n} of them at the ${BODY_LABELS[top.body] ?? top.body} meeting on ${fmtShort(top.date)}`
                  : top && byMeeting.size === 1
                    ? `, all at the ${BODY_LABELS[top.body] ?? top.body} meeting on ${fmtShort(top.date)}`
                    : ""}
                .
              </Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

interface HotRow {
  body: string;
  topic: HotTopic;
  share: number;
  meetingsAsc: { id: number; title: string; date: string }[];
  cellMax: number;
}

function Attention({ panels }: { panels: { body: string; hot: HotTopicsResponse }[] }) {
  const rows: HotRow[] = [];
  for (const { body, hot } of panels) {
    const meetingsAsc = [...hot.meetings].sort((a, b) => a.date.localeCompare(b.date));
    const cellMax = Math.max(1, ...hot.topics.flatMap((t) => Object.values(t.per_meeting)));
    for (const topic of hot.topics) {
      rows.push({
        body,
        topic,
        share: hot.window_seconds ? Math.round((topic.seconds / hot.window_seconds) * 100) : 0,
        meetingsAsc,
        cellMax,
      });
    }
  }
  rows.sort((a, b) => b.topic.seconds - a.topic.seconds);
  const shown = rows.slice(0, 8);
  const max = Math.max(1, ...shown.map((r) => r.topic.seconds));
  const transcribed = panels
    .filter((p) => p.hot.meetings.length)
    .map((p) => `${p.hot.meetings.length} ${BODY_LABELS[p.body] ?? p.body}`)
    .join(" and ");
  return (
    <section>
      <SectionHead
        title="Where the time went"
        aside={
          <Link href="/topics?view=hot" className="underline underline-offset-2 hover:text-ink">
            all hot topics
          </Link>
        }
      />
      {shown.length === 0 ? (
        <p className="py-3 text-sm text-muted">No transcribed meetings in the last 60 days yet.</p>
      ) : (
        <>
          <ul className="divide-y divide-hairline">
            {shown.map((r) => {
              const at = r.meetingsAsc.filter((m) => (r.topic.per_meeting[String(m.id)] ?? 0) > 0).length;
              return (
                <li key={`${r.body}-${r.topic.slug}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 py-2 sm:grid-cols-[minmax(0,1fr)_64px_minmax(80px,120px)_84px]">
                  <span className="flex min-w-0 items-center gap-2 text-[14px]">
                    <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${bodyDot(r.body)}`} />
                    <Link href={`/topics/${r.topic.slug}`} className="truncate font-semibold underline-offset-2 hover:underline">
                      {r.topic.name}
                    </Link>
                    <StatusBadge status={r.topic.current_status} variant="outline" />
                  </span>
                  <span className="text-right text-[13px] font-semibold tabular-nums">
                    {Math.round(r.topic.seconds / 60)} min
                    {r.share > 0 && <span className="font-normal text-muted"> · {r.share}%</span>}
                  </span>
                  <span className="hidden h-1.5 rounded-full bg-strong sm:block">
                    <span
                      className="block h-1.5 rounded-full bg-ink"
                      style={{ width: `${Math.max(4, (r.topic.seconds / max) * 100)}%` }}
                    />
                  </span>
                  <span
                    className="hidden items-center justify-end gap-1.5 sm:flex"
                    aria-label={`Discussed at ${at} of ${r.meetingsAsc.length} meetings`}
                  >
                    <span className="flex gap-[2px]">
                      {r.meetingsAsc.map((m) => {
                        const secs = r.topic.per_meeting[String(m.id)] ?? 0;
                        return (
                          <span
                            key={m.id}
                            title={`${fmtShort(m.date)} · ${m.title} · ${secs ? `${Math.round(secs / 60)} min` : "not mentioned"}`}
                            className={`block h-2 w-2 rounded-[2px] ${secs ? "bg-ink" : "border border-ink/20"}`}
                            style={secs ? { opacity: 0.3 + 0.7 * (secs / r.cellMax) } : undefined}
                          />
                        );
                      })}
                    </span>
                    <span className="text-[11px] tabular-nums text-muted">
                      {at}/{r.meetingsAsc.length}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
            {panels.map((p) => (
              <span key={p.body} className="flex items-center gap-1.5">
                <span aria-hidden className={`h-2 w-2 rounded-full ${bodyDot(p.body)}`} />
                {BODY_LABELS[p.body] ?? p.body}
              </span>
            ))}
            <span>Named discussion time across {transcribed || "no"} transcribed meetings, last 60 days. Share is of that body&apos;s hours.</span>
          </p>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

const NO_HOT: HotTopicsResponse = { meetings: [], topics: [], window_seconds: 0 };
const NO_STATS: MeetingStats = { days: 30, meetings_held: 0, hours_of_meetings: 0, votes_taken: 0, motions_passed: 0, motions_failed: 0 };
// Council meets about every other week, so a 7-day window left every other
// briefing empty. Two weeks always holds the last regular meeting.
const WINDOW_DAYS = 14;
// a hearing this far out leads the page; beyond that, the last meeting does
const LEDE_DAYS = 10;
// the docket looks this far ahead
const DOCKET_DAYS = 21;
const NO_CHANGES: ChangesResponse = { days: WINDOW_DAYS, since: "", changes: [] };

export default async function Briefing() {
  // A front page of independent parts: one failing endpoint blanks its own
  // part, not the page. Only the meetings list is load-bearing enough to fall
  // through to the error boundary.
  const [meetings, hotCouncil, hotPC, upcoming, changes, stats, projects] = await Promise.all([
    api.meetings(new URLSearchParams({ limit: "8" })),
    api.hotTopics("city_council").catch(() => NO_HOT),
    api.hotTopics("planning_commission").catch(() => NO_HOT),
    api.upcoming().catch(() => [] as UpcomingEvent[]),
    api.changes(WINDOW_DAYS, 100).catch(() => NO_CHANGES),
    api.stats(30).catch(() => NO_STATS),
    api.developmentProjects(new URLSearchParams()).catch(() => []),
  ]);
  const today = localDay(new Date());

  // The record: meetings in the same window the change feed uses. When
  // nothing met in that window, fall back to the last meeting and say so.
  const withItems = meetings.filter((m) => m.agenda_item_count > 0);
  const inWindow = changes.since ? withItems.filter((m) => m.date >= changes.since) : [];
  const stale = inWindow.length === 0;
  const chosen = (stale ? withItems.slice(0, 1) : inWindow).slice(0, 4);

  // The docket: tracked bodies get their agenda read; advisory boards are listed.
  const ahead = upcoming.filter(
    (e) => e.in_progress || (e.starts_at && daysBetween(today, dayOf(e.starts_at)) >= 0 && daysBetween(today, dayOf(e.starts_at)) <= DOCKET_DAYS),
  );
  const tracked = ahead.filter((e) => e.body).slice(0, 5);
  const advisory = ahead.filter((e) => !e.body).slice(0, 6);

  const [details, docketDetails] = await Promise.all([
    Promise.all(chosen.map((m) => api.meeting(String(m.id)).catch(() => null))),
    Promise.all(tracked.map((e) => api.upcomingDetail(e.event_id).catch(() => null))),
  ]);
  const meetingDetails = details.filter((m): m is MeetingDetail => m !== null);
  const docket = tracked.map((e, i) => docketEntry(e, docketDetails[i]));

  const decisions = deriveDecisions(meetingDetails);
  const substantive = decisions.filter((d) => !isConsent(d));
  const contested = substantive.filter((d) => d.split || d.badge === "FAILED");

  // The lede, in order of consequence: a hearing within days, a contested
  // vote, the next meeting with tracked business, then the plain count.
  const soonHearing = docket.find(
    (x) => x.hearings.length > 0 && x.event.starts_at && daysBetween(today, dayOf(x.event.starts_at)) <= LEDE_DAYS,
  );
  const nextBusiness = docket.find((x) => x.rest.length > 0 || x.hearings.length > 0);
  const lede: Lede = soonHearing
    ? hearingLede(soonHearing, today)
    : contested[0]
      ? contestedLede(contested[0])
      : nextBusiness
        ? meetingLede(nextBusiness, today)
        : countLede(decisions, changes, meetingDetails, stale);

  // The ledger: contested votes, then status moves, then the rest of the votes.
  // A vote that moved a topic's status is one event, not two rows: the move
  // keeps the row and borrows the vote's tally.
  const moves = changes.changes.filter((c) => c.kind === "status_change");
  const fresh = changes.changes.filter((c) => c.kind !== "status_change");
  const absorbed = new Set<Decision>();
  const moveRows = moves.map((c): Row => {
    const vote = decisions.find(
      (d) => d.meetingId === c.meeting_id && !absorbed.has(d) && d.title.toLowerCase().includes(c.name.toLowerCase()),
    );
    if (vote) absorbed.add(vote);
    return { kind: "move", c, vote };
  });
  const voteRow = (d: Decision): Row => ({ kind: "vote", d });
  const rows: Row[] = [
    ...contested.filter((d) => !absorbed.has(d)).map(voteRow),
    ...moveRows,
    ...substantive.filter((d) => !contested.includes(d) && !absorbed.has(d)).map(voteRow),
    ...decisions.filter((d) => isConsent(d) && !absorbed.has(d)).map(voteRow),
  ].slice(0, 10);

  const hearingMeetings = docket.filter((x) => x.hearings.length > 0).length;
  // an older API answers without the flag: then the count is unknown, not zero
  const hearingsKnown = docketDetails.some((d) => d?.topics.some((t) => "hearing" in t));
  const analysed = projects.filter((p) => p.has_evaluation).length;
  const figures: Figure[] = [
    { value: String(stats.meetings_held), label: `meetings in ${stats.days} days`, href: "/meetings" },
    { value: `${stats.hours_of_meetings.toFixed(1)} h`, label: "in session" },
    {
      value: String(stats.votes_taken),
      label: stats.motions_failed ? `votes, ${stats.motions_failed} failed` : stats.votes_taken ? "votes, none failed" : "votes",
    },
    { value: String(moves.length), label: `status moves in ${changes.days} days`, href: `/topics?days=${changes.days}` },
    ...(hearingsKnown
      ? [
          {
            value: String(hearingMeetings),
            label: hearingMeetings === 1 ? "meeting with a public hearing ahead" : "meetings with public hearings ahead",
          },
        ]
      : []),
    { value: String(analysed), label: "projects with an impact analysis", href: "/topics?official=true" },
  ];

  const latest = meetings[0] ? formatDate(meetings[0].date) : "";

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-16 pt-6 sm:px-8">
      <Masthead latest={latest} />
      <div className="mb-4">
        <LedeBlock lede={lede} />
      </div>
      <Figures figures={figures} />
      <div className="flex flex-col gap-10">
        <Docket entries={docket} advisory={advisory} today={today} />
        <Moved rows={rows} fresh={fresh} days={changes.days} />
        <Attention
          panels={[
            { body: "city_council", hot: hotCouncil },
            { body: "planning_commission", hot: hotPC },
          ]}
        />
      </div>
    </div>
  );
}
