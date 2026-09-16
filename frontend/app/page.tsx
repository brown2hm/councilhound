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
  type HotTopicsResponse,
  type MeetingDetail,
  type UpcomingEvent,
} from "@/lib/api";
import { figure, voteShape, type Figure } from "@/lib/briefing";

export const dynamic = "force-dynamic";

interface Decision {
  badge: string; // PASSED | FAILED | CONTINUED | RECOMMENDED
  tally: string; // "unanimous" | "4–2" | "5–0–1" | "" when the record has no count
  split: boolean; // at least one no vote
  tint: string;
  body: string;
  meta: string;
  title: string;
  text: string;
  meetingId: number;
  figure: Figure | null;
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
    // the item label belongs on the meeting page; up here the date is enough
    const meta = () => formatDate(m.date);
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
        decisions.push({
          badge,
          tally: shape.tally,
          split: shape.split,
          tint,
          body: m.body,
          meta: meta(),
          title: item.title,
          text,
          meetingId: m.id,
          figure: figure(text),
        });
      } else if (item.outcome && /recommend/i.test(item.outcome) && m.body === "planning_commission") {
        decisions.push({
          badge: "RECOMMENDED",
          tally: "",
          split: false,
          tint: TINTS.proposed,
          body: m.body,
          meta: meta(),
          title: item.title,
          text: item.outcome,
          meetingId: m.id,
          figure: figure(item.outcome),
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
  // unanimity is the signal: say it when the record supports it
  const voted = decisions.filter((d) => d.badge === "PASSED" || d.badge === "FAILED");
  const split = voted.filter((d) => d.split).length;
  const known = voted.filter((d) => d.tally).length;
  if (split) s += split === 1 ? ", one on a split vote" : `, ${word(split)} on split votes`;
  else if (known === voted.length && voted.length > 1) s += ", all unanimous";
  else if (known === voted.length && voted.length === 1) s += ", unanimously";
  return s;
}

function headline(decisions: Decision[], changes: ChangesResponse): string {
  const moved = changes.changes.filter((c) => c.kind === "status_change").length;
  const fresh = changes.changes.length - moved;
  const sentences: string[] = [];
  const votes = voteSentence(decisions);
  if (votes) sentences.push(cap(votes) + ".");
  if (moved) sentences.push(cap(plural(moved, "topic")) + " changed status.");
  // first appearances are only news when nothing else happened
  if (!sentences.length && fresh) sentences.push(cap(plural(fresh, "topic")) + " new to the record.");
  return sentences.length ? sentences.join(" ") : "The latest from city hall.";
}

// "From the City Council meeting on Sep 8." — which meetings the headline counts
function provenance(details: MeetingDetail[], stale: boolean, days: number): string {
  if (details.length === 0) return "";
  const named = details
    .map((m) => `the ${BODY_LABELS[m.body] ?? m.body} meeting on ${formatDate(m.date)}`)
    .join(" and ");
  if (stale) {
    return `No meetings in the last ${days} days. The votes below are from the last one, ${named}.`;
  }
  return `From ${named}.`;
}

const clip = (text: string, n: number) => (text.length > n ? text.slice(0, n).trimEnd() + "…" : text);

/** YYYY-MM-DD in the city's own time zone, so "today" and "tomorrow" hold
 * whether the page renders in Virginia or on a UTC box. */
const CITY_TZ = "America/New_York";
const localDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: CITY_TZ });
const daysBetween = (fromDay: string, toDay: string) =>
  Math.round((Date.parse(toDay) - Date.parse(fromDay)) / 86_400_000);

/** "City Council meets today at 6:00 PM." — the quiet-week headline. */
function nextUpHeadline(e: UpcomingEvent, today: string): string {
  const day = e.starts_at!.slice(0, 10);
  const gap = daysBetween(today, day);
  const when =
    gap <= 0
      ? "today"
      : gap === 1
        ? "tomorrow"
        : new Date(e.starts_at!).toLocaleDateString("en-US", { weekday: "long" });
  const time = new Date(e.starts_at!).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  const who = e.body ? BODY_LABELS[e.body] ?? e.body : null;
  return who ? `${who} meets ${when} at ${time}.` : `${e.title} is ${when} at ${time}.`;
}

const fmtShort = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

function HotPanel({
  hot,
  body,
  eyebrow,
  heading,
}: {
  hot: HotTopicsResponse;
  body: string;
  eyebrow: string;
  heading: string;
}) {
  const topics = hot.topics.slice(0, 5);
  const max = Math.max(1, ...topics.map((t) => t.seconds));
  // chronological left -> right: one cell per transcribed meeting in the window
  const meetingsAsc = [...hot.meetings].sort((a, b) => a.date.localeCompare(b.date));
  // one shade scale for the whole panel, so a dark cell means the same minutes on every row
  const cellMax = Math.max(1, ...topics.flatMap((t) => Object.values(t.per_meeting)));
  // the API field is new; an older API answers without it and the panel simply drops the share
  const windowSeconds = hot.window_seconds ?? 0;
  const hours = windowSeconds / 3600;
  const strip = meetingsAsc.length > 1;
  return (
    <section className="rounded-3xl bg-card p-7 text-ink">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${bodyDot(body)}`} />
        {eyebrow}
      </div>
      <h2 className="mb-1 text-2xl font-medium leading-tight tracking-[-0.3px]">{heading}</h2>
      <p className="mb-5 text-[13px] text-muted">
        {hot.meetings.length
          ? `Named discussion time across ${hot.meetings.length} transcribed meeting${hot.meetings.length === 1 ? "" : "s"}${windowSeconds ? ` (${hours.toFixed(1)} h)` : ""}, last 60 days.`
          : "Named discussion time, last 60 days."}
      </p>
      <div className="flex flex-col gap-3.5">
        {topics.map((t, i) => {
          const at = meetingsAsc.filter((m) => (t.per_meeting[String(m.id)] ?? 0) > 0).length;
          const share = windowSeconds ? Math.round((t.seconds / windowSeconds) * 100) : 0;
          return (
            <Link key={t.slug} href={`/topics/${t.slug}`} className="block">
              <div className="mb-[5px] flex items-baseline justify-between gap-3">
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold">
                  <span>
                    {i + 1}&nbsp; {t.name}
                  </span>
                  <StatusBadge status={t.current_status} variant="outline" />
                </span>
                <span
                  className="shrink-0 text-[13px] font-semibold"
                  title={share ? `${share}% of the ${hours.toFixed(1)} transcribed hours in the window` : undefined}
                >
                  {Math.round(t.seconds / 60)} min
                  {share > 0 && <span className="font-normal text-muted"> · {share}%</span>}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-1.5 min-w-0 flex-1 rounded-full bg-strong">
                  <div
                    className="h-1.5 rounded-full bg-ink"
                    style={{ width: `${Math.max(4, (t.seconds / max) * 100)}%` }}
                  />
                </div>
                {strip && (
                  // fixed width so the strips line up down the panel whatever the bar does
                  <span
                    className="flex w-[4.5rem] shrink-0 items-center justify-end gap-1.5"
                    aria-label={`Discussed at ${at} of ${meetingsAsc.length} meetings`}
                  >
                    <span className="flex gap-[2px]">
                      {meetingsAsc.map((m) => {
                        const secs = t.per_meeting[String(m.id)] ?? 0;
                        const level = secs ? 0.3 + 0.7 * (secs / cellMax) : 0;
                        return (
                          <span
                            key={m.id}
                            title={`${fmtShort(m.date)} · ${m.title} · ${secs ? `${Math.round(secs / 60)} min` : "not mentioned"}`}
                            className={`block h-2 w-2 rounded-[2px] ${secs ? "bg-ink" : "border border-ink/20"}`}
                            style={secs ? { opacity: level } : undefined}
                          />
                        );
                      })}
                    </span>
                    <span className="text-[11px] tabular-nums text-muted">
                      {at}/{meetingsAsc.length}
                    </span>
                  </span>
                )}
              </div>
            </Link>
          );
        })}
        {topics.length === 0 && (
          <p className="text-sm text-muted">No transcribed meetings in the window yet.</p>
        )}
      </div>
      <div className="mt-5">
        <Link
          href="/topics?view=hot"
          className="inline-block rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white"
        >
          See all hot topics
        </Link>
      </div>
    </section>
  );
}

function AskHound() {
  return (
    <section
      aria-label="Ask the hound"
      className="mb-6 grid items-center gap-3 rounded-3xl bg-card p-3 pl-5 sm:grid-cols-[auto_1fr] sm:gap-5"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-semibold">
          <Image src="/brand/hound.png" alt="" width={34} height={30} className="h-6 w-auto" />
          Ask the hound
        </div>
        <div className="text-[12px] text-muted">
          Answers drawn from the meeting record, with citations you can verify.
        </div>
      </div>
      <form
        action="/ask"
        method="get"
        className="flex items-center justify-between gap-2 rounded-xl border border-hairline bg-canvas p-1 pl-4"
      >
        <input
          name="q"
          placeholder="e.g. What's the status of the George Snyder Trail?"
          className="min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted-soft"
        />
        <button className="shrink-0 rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-white hover:bg-ink-active">
          Ask
        </button>
      </form>
    </section>
  );
}

/** "Today · 6:00 PM", "Tomorrow · 7:00 PM", "Wed, Sep 23 · 7:00 PM". */
function fmtRelative(iso: string, today: string): string {
  const gap = daysBetween(today, iso.slice(0, 10));
  const day =
    gap <= 0
      ? "Today"
      : gap === 1
        ? "Tomorrow"
        : new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day} · ${new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

function NextUp({ events, today }: { events: UpcomingEvent[]; today: string }) {
  const shown = events.slice(0, 4);
  if (shown.length === 0) return null;
  const [first, ...rest] = shown;
  const firstSoon = first.in_progress || (first.starts_at ? daysBetween(today, first.starts_at.slice(0, 10)) <= 0 : false);
  const agenda = (e: UpcomingEvent) =>
    e.agenda_url && (
      <>
        {" · "}
        <a href={e.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
          agenda
        </a>
      </>
    );
  const when = (e: UpcomingEvent) =>
    e.in_progress ? (
      <span className="font-semibold text-tint-coral-text">● Live now</span>
    ) : e.starts_at ? (
      fmtRelative(e.starts_at, today)
    ) : (
      ""
    );
  return (
    <section className="rounded-3xl border border-hairline bg-canvas p-6">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">
          Next up
        </span>
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/meetings/upcoming.ics`}
          className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
        >
          📅 calendar feed
        </a>
      </div>
      {/* the nearest meeting is the one that matters: bigger, with the day spelled out */}
      <div className="mb-3 border-b border-hairline-soft pb-3">
        <div className="flex items-center gap-2">
          {first.body && <span className={`h-2 w-2 shrink-0 rounded-full ${bodyDot(first.body)}`} />}
          <Link
            href={`/meetings/upcoming/${encodeURIComponent(first.event_id)}`}
            className="min-w-0 text-base font-semibold leading-snug underline-offset-2 hover:underline"
          >
            {first.title}
          </Link>
        </div>
        <div className={`mt-1 text-[13px] ${firstSoon ? "font-semibold text-tint-coral-text" : "font-semibold text-ink"}`}>
          {when(first)}
          <span className="font-normal text-muted">{agenda(first)}</span>
        </div>
      </div>
      <ul className="space-y-2.5">
        {rest.map((e) => (
          <li
            key={e.event_id}
            className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-sm sm:flex-nowrap"
          >
            <span className="flex min-w-0 items-baseline gap-2">
              {e.body && (
                <span
                  className={`h-2 w-2 shrink-0 self-center rounded-full ${bodyDot(e.body)}`}
                />
              )}
              <Link
                href={`/meetings/upcoming/${encodeURIComponent(e.event_id)}`}
                className="truncate font-medium underline-offset-2 hover:underline"
              >
                {e.title}
              </Link>
            </span>
            <span className="shrink-0 text-[13px] text-muted">
              {when(e)}
              {agenda(e)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ChangedRecently({ changes }: { changes: ChangesResponse }) {
  // status moves are the news; first appearances follow
  const ordered = [
    ...changes.changes.filter((c) => c.kind === "status_change"),
    ...changes.changes.filter((c) => c.kind !== "status_change"),
  ];
  const shown = ordered.slice(0, 8);
  const more = ordered.length - shown.length;
  const moved = changes.changes.filter((c) => c.kind === "status_change").length;
  const fresh = changes.changes.length - moved;
  const counts = [
    moved ? `${plural(moved, "status move")}` : "",
    fresh ? `${plural(fresh, "topic")} new to the record` : "",
  ].filter(Boolean);
  return (
    <section>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">What changed</h2>
        <span className="flex gap-3 text-[12px] font-semibold text-muted">
          <Link href={`/topics?days=${changes.days}`} className="underline underline-offset-2 hover:text-ink">
            all recent activity
          </Link>
          <a
            href={`${PUBLIC_API_URL}/entities/changes.atom`}
            className="underline underline-offset-2 hover:text-ink"
          >
            feed
          </a>
        </span>
      </div>
      {counts.length > 0 && (
        <p className="mb-3 text-[13px] text-muted">
          {cap(counts.join(" and "))} in the last {changes.days} days.
        </p>
      )}
      {shown.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
          No status changes in the window yet.
        </p>
      ) : (
        <ul className="divide-y divide-hairline border-y border-hairline">
          {shown.map((c) => (
            <li key={c.id}>
              <Link
                href={`/topics/${c.slug}#m-${c.meeting_id}`}
                className="-mx-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-2 py-3 text-[15px] hover:bg-soft"
              >
                <span className="min-w-0 flex-1 basis-56 font-semibold">{c.name}</span>
                <span className="flex items-center gap-1.5 text-[13px]">
                  {c.kind === "new" ? (
                    <>
                      <span className="rounded-full bg-tint-lavender px-2.5 py-[3px] text-xs font-semibold text-tint-lavender-text">
                        NEW
                      </span>
                      {c.to_status && <span aria-hidden className="text-muted-soft">·</span>}
                    </>
                  ) : c.from_status ? (
                    // emphasis: the move is the news, so only the destination is tinted
                    <>
                      <StatusBadge status={c.from_status} variant="outline" />
                      <span aria-hidden className="font-semibold text-ink">→</span>
                    </>
                  ) : null}
                  <StatusBadge status={c.to_status} />
                </span>
                <span className="w-full text-[13px] text-muted sm:w-auto">
                  <BodyTag body={c.body} /> · {formatDate(c.date)}
                </span>
              </Link>
            </li>
          ))}
          {more > 0 && (
            <li>
              <Link
                href={`/topics?days=${changes.days}`}
                className="block py-3 text-[13px] font-semibold text-muted underline-offset-2 hover:text-ink hover:underline"
              >
                and {more} more
              </Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

function DecisionCard({ d }: { d: Decision }) {
  const badge = (
    <span className={`rounded-full px-2.5 py-[3px] text-xs font-semibold ${d.tint}`}>
      {d.badge}
      {d.tally && <span className="font-medium"> · {d.tally}</span>}
    </span>
  );
  if (isConsent(d)) {
    return (
      <Link href={`/meetings/${d.meetingId}`} className="rounded-2xl border border-hairline bg-canvas px-5 py-3 hover:border-ink">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          {badge}
          <BodyTag body={d.body} className="text-[13px] text-muted" />
          <span className="text-[13px] text-muted">{d.meta}</span>
        </div>
        <div className="text-sm">
          <span className="font-medium">{d.title}.</span>{" "}
          <span className="text-muted">{clip(d.text, 140)}</span>
        </div>
      </Link>
    );
  }
  return (
    <Link href={`/meetings/${d.meetingId}`} className="flex gap-4 rounded-2xl border border-hairline bg-canvas p-4 px-5 hover:border-ink">
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          {badge}
          <BodyTag body={d.body} className="text-[13px] text-muted" />
          <span className="text-[13px] text-muted">{d.meta}</span>
        </div>
        <div className="mb-1 font-semibold">{d.title}</div>
        <p className="text-sm leading-[1.55] text-body">{clip(d.text, 220)}</p>
      </div>
      {d.figure && (
        // the number is the chart: one figure per card, proportional digits, label under it
        <div className="shrink-0 self-start pl-2 text-right">
          <div className="text-[22px] font-semibold leading-none tracking-[-0.3px]">{d.figure.value}</div>
          <div className="mt-1 text-[11px] uppercase tracking-[1px] text-muted">{d.figure.label}</div>
        </div>
      )}
    </Link>
  );
}

const NO_HOT: HotTopicsResponse = { meetings: [], topics: [], window_seconds: 0 };
// Council meets about every other week, so a 7-day window left every other
// briefing empty. Two weeks always holds the last regular meeting.
const WINDOW_DAYS = 14;
// ...but a week without a meeting is still quiet: then the next one is the news
const QUIET_DAYS = 7;
const SOON_DAYS = 3;
const NO_CHANGES: ChangesResponse = { days: WINDOW_DAYS, since: "", changes: [] };

export default async function Briefing() {
  // The briefing is a dashboard of independent panels: one failing endpoint
  // should blank its own panel, not the page. Only the meetings list is
  // load-bearing enough to fall through to the error boundary.
  const [meetings, hotCouncil, hotPC, upcoming, changes] = await Promise.all([
    api.meetings(new URLSearchParams({ limit: "8" })),
    api.hotTopics("city_council").catch(() => NO_HOT),
    api.hotTopics("planning_commission").catch(() => NO_HOT),
    api.upcoming().catch(() => []),
    api.changes(WINDOW_DAYS, 100).catch(() => NO_CHANGES),
  ]);
  // The headline counts the same window the change feed uses, so its two
  // halves describe the same fortnight. When nothing met in that window, fall
  // back to the last meeting and say so, rather than showing an empty page.
  const withItems = meetings.filter((m) => m.agenda_item_count > 0);
  const inWindow = changes.since ? withItems.filter((m) => m.date >= changes.since) : [];
  const stale = inWindow.length === 0;
  const chosen = (stale ? withItems.slice(0, 1) : inWindow).slice(0, 4);
  const details = (
    await Promise.all(chosen.map((m) => api.meeting(String(m.id)).catch(() => null)))
  ).filter((m): m is MeetingDetail => m !== null);
  const decisions = deriveDecisions(details);
  // split votes first, then the rest; consent agendas are real votes but read as housekeeping
  const substantive = decisions.filter((d) => !isConsent(d));
  const shownDecisions = [
    ...substantive.filter((d) => d.split),
    ...substantive.filter((d) => !d.split),
    ...decisions.filter(isConsent),
  ].slice(0, 8);
  const latest = meetings[0] ? formatDate(meetings[0].date) : "";
  const sub = provenance(details, stale, changes.days);

  // Quiet week + a meeting within days: lead with the meeting, not a stale count.
  const today = localDay(new Date());
  const quiet = !withItems.some((m) => daysBetween(m.date, today) < QUIET_DAYS);
  const next = upcoming.find((e) => e.starts_at && daysBetween(today, e.starts_at.slice(0, 10)) >= 0);
  const leadWithNext =
    quiet && next?.starts_at && daysBetween(today, next.starts_at.slice(0, 10)) <= SOON_DAYS ? next : null;
  const lastVotes = voteSentence(decisions);

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">
          The briefing · Week of {latest} · City of Fairfax, VA
        </div>
        <FollowButton target={{ kind: "briefing" }} label="Get this weekly by email" size="sm" />
      </div>
      <AskHound />
      {/* the one dark object on the page: whatever leads this week */}
      <section className="mb-8 rounded-3xl bg-teal p-7 text-white sm:p-9">
        {leadWithNext ? (
          <>
            <h1 className="max-w-[900px] text-[32px] font-medium leading-[1.15] tracking-[-0.5px] [text-wrap:balance]">
              <Link
                href={`/meetings/upcoming/${encodeURIComponent(leadWithNext.event_id)}`}
                className="underline decoration-mint/50 decoration-2 underline-offset-[6px] hover:decoration-mint"
              >
                {nextUpHeadline(leadWithNext, today)}
              </Link>
            </h1>
            <p className="mt-3 max-w-[820px] text-sm text-white/70">
              {leadWithNext.title}
              {leadWithNext.agenda_url && (
                <>
                  {" · "}
                  <a href={leadWithNext.agenda_url} target="_blank" className="text-white underline underline-offset-2">
                    agenda
                  </a>
                </>
              )}
              {details.length > 0 && (
                <>
                  {" · "}
                  No meeting in the last {QUIET_DAYS} days.
                  {lastVotes ? ` Last time out, ${lastVotes}, at ` : " The last one was "}
                  {details
                    .map((m) => `the ${BODY_LABELS[m.body] ?? m.body} meeting on ${formatDate(m.date)}`)
                    .join(" and ")}
                  .
                </>
              )}
            </p>
          </>
        ) : (
          <>
            <h1 className="max-w-[900px] text-[32px] font-medium leading-[1.15] tracking-[-0.5px] [text-wrap:balance]">
              {headline(decisions, changes)}
            </h1>
            {sub && <p className="mt-3 max-w-[820px] text-sm text-white/70">{sub}</p>}
          </>
        )}
      </section>
      {/* min-w-0: on phones both columns share one track, and a no-wrap row
          inside would otherwise widen the whole page */}
      <div className="grid gap-8 md:grid-cols-[1.5fr_1fr]">
        <div className="flex min-w-0 flex-col gap-8">
          <ChangedRecently changes={changes} />

          <section>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-xl font-semibold">Votes taken</h2>
              {details.length === 1 && (
                <Link
                  href={`/meetings/${details[0].id}`}
                  className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                >
                  full {formatDate(details[0].date)} meeting
                </Link>
              )}
            </div>
            <div className="mt-3 flex flex-col gap-3">
              {shownDecisions.map((d, i) => (
                <DecisionCard key={i} d={d} />
              ))}
              {shownDecisions.length === 0 && (
                <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
                  No recent decisions extracted yet.
                </p>
              )}
            </div>
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <NextUp events={upcoming} today={today} />
          <HotPanel
            hot={hotCouncil}
            body="city_council"
            eyebrow="Hot right now · City Council"
            heading="What the council is spending its time on"
          />
          <HotPanel
            hot={hotPC}
            body="planning_commission"
            eyebrow="Hot right now · Planning Commission"
            heading="What the commission is spending its time on"
          />
        </div>
      </div>
    </div>
  );
}
