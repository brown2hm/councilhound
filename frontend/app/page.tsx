import Image from "next/image";
import Link from "next/link";
import BodyTag from "@/components/BodyTag";
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

export const dynamic = "force-dynamic";

interface Decision {
  badge: string;
  tint: string;
  body: string;
  meta: string;
  title: string;
  text: string;
  meetingId: number;
}

const TINTS: Record<string, string> = {
  approved: "bg-tint-mint text-tint-mint-text",
  denied: "bg-tint-coral text-tint-coral-text",
  proposed: "bg-tint-lavender text-tint-lavender-text",
  deferred: "bg-strong text-body",
};

function deriveDecisions(details: MeetingDetail[]): Decision[] {
  const decisions: Decision[] = [];
  for (const m of details) {
    const meta = (label: string) => `${formatDate(m.date)} · item ${label}`;
    for (const item of m.agenda_items) {
      if (!item.title) continue;
      // procedural housekeeping doesn't belong on the front page
      if (/\b(minutes|remote participation|adoption of (the )?agenda|adjourn)\b/i.test(item.title)) {
        continue;
      }
      const vote = item.votes[0];
      if (vote) {
        const counts = Object.values(vote.vote_breakdown ?? {});
        const yes = counts.filter((v) => v === "yes").length;
        const no = counts.filter((v) => v === "no").length;
        const tally = yes || no ? ` ${yes}–${no}` : "";
        const badge =
          vote.motion_result === "passed"
            ? `PASSED${tally}`
            : vote.motion_result === "failed"
              ? `FAILED${tally}`
              : "CONTINUED";
        const tint =
          vote.motion_result === "passed"
            ? TINTS.approved
            : vote.motion_result === "failed"
              ? TINTS.denied
              : TINTS.deferred;
        decisions.push({
          badge,
          tint,
          body: m.body,
          meta: meta(item.label),
          title: item.title,
          text: item.outcome ?? vote.description ?? "",
          meetingId: m.id,
        });
      } else if (item.outcome && /recommend/i.test(item.outcome) && m.body === "planning_commission") {
        decisions.push({
          badge: "RECOMMENDED",
          tint: TINTS.proposed,
          body: m.body,
          meta: meta(item.label),
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

function headline(decisions: Decision[], changed: number): string {
  const passed = decisions.filter((d) => d.badge.startsWith("PASSED")).length;
  const failed = decisions.filter((d) => d.badge.startsWith("FAILED")).length;
  const other = decisions.length - passed - failed;
  const parts: string[] = [];
  if (passed) parts.push(`${word(passed)} measure${passed === 1 ? "" : "s"} passed`);
  if (failed) parts.push(`${word(failed)} failed`);
  if (other) parts.push(`${word(other)} still in motion`);
  const votes =
    parts.length > 1 ? parts.slice(0, -1).join(", ") + ", and " + parts.at(-1) : parts[0];
  const sentences: string[] = [];
  if (votes) sentences.push(votes.charAt(0).toUpperCase() + votes.slice(1) + ".");
  if (changed) {
    const t = `${word(changed)} topic${changed === 1 ? "" : "s"} changed status.`;
    sentences.push(t.charAt(0).toUpperCase() + t.slice(1));
  }
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

function HotPanel({
  hot,
  variant,
  eyebrow,
  heading,
}: {
  hot: HotTopicsResponse;
  variant: "teal" | "cream";
  eyebrow: string;
  heading: string;
}) {
  const topics = hot.topics.slice(0, 5);
  const max = Math.max(1, ...topics.map((t) => t.seconds));
  const teal = variant === "teal";
  // chronological left -> right so the bar doubles as a mini trend
  const meetingsAsc = [...hot.meetings].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <section className={`rounded-3xl p-7 ${teal ? "bg-teal text-white" : "bg-card text-ink"}`}>
      <div
        className={`mb-2 text-xs font-semibold uppercase tracking-[1.5px] ${
          teal ? "text-mint" : "text-tint-ochre-text"
        }`}
      >
        {eyebrow}
      </div>
      <h2 className="mb-1 text-2xl font-medium leading-tight tracking-[-0.3px]">{heading}</h2>
      <p className={`mb-5 text-[13px] ${teal ? "text-white/60" : "text-muted"}`}>
        Named discussion time, last 60 days.
      </p>
      <div className="flex flex-col gap-3.5">
        {topics.map((t, i) => (
          <Link key={t.slug} href={`/topics/${t.slug}`} className="block">
            <div className="mb-[5px] flex items-baseline justify-between gap-3">
              <span className="text-sm font-semibold">
                {i + 1}&nbsp; {t.name}
              </span>
              <span
                className={`shrink-0 text-[13px] font-semibold ${
                  teal ? "text-mint" : "text-tint-ochre-text"
                }`}
              >
                {Math.round(t.seconds / 60)} min
              </span>
            </div>
            <div className={`h-1.5 rounded-full ${teal ? "bg-white/[0.14]" : "bg-strong"}`}>
              <div
                className="flex h-1.5 gap-px"
                style={{ width: `${Math.max(6, (t.seconds / max) * 100)}%` }}
              >
                {meetingsAsc
                  .map((m) => ({ m, secs: t.per_meeting[String(m.id)] ?? 0 }))
                  .filter(({ secs }) => secs > 0)
                  .map(({ m, secs }, si, arr) => (
                    <div
                      key={m.id}
                      title={`${Math.round(secs / 60)} min · ${m.title}`}
                      className={`h-1.5 ${teal ? "bg-mint" : "bg-ochre"} ${si === 0 ? "rounded-l-full" : ""} ${si === arr.length - 1 ? "rounded-r-full" : ""}`}
                      style={{ flexGrow: secs }}
                    />
                  ))}
              </div>
            </div>
          </Link>
        ))}
        {topics.length === 0 && (
          <p className={`text-sm ${teal ? "text-white/70" : "text-muted"}`}>
            No transcribed meetings in the window yet.
          </p>
        )}
      </div>
      <div className="mt-5">
        <Link
          href="/topics?view=hot"
          className={`inline-block rounded-xl px-5 py-3 text-sm font-semibold leading-none ${
            teal ? "bg-canvas text-ink" : "bg-ink text-white"
          }`}
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

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }) + " · " + new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function NextUp({ events }: { events: UpcomingEvent[] }) {
  const shown = events.slice(0, 4);
  if (shown.length === 0) return null;
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
      <ul className="space-y-3">
        {shown.map((e) => (
          <li
            key={e.event_id}
            className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-sm sm:flex-nowrap"
          >
            <span className="flex min-w-0 items-baseline gap-2">
              {e.body && (
                <span
                  className={`h-2 w-2 shrink-0 self-center rounded-full ${e.body === "planning_commission" ? "bg-ochre" : "bg-teal"}`}
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
              {e.in_progress ? (
                <span className="font-semibold text-tint-coral-text">● Live now</span>
              ) : e.starts_at ? (
                fmtWhen(e.starts_at)
              ) : (
                ""
              )}
              {e.agenda_url && (
                <>
                  {" · "}
                  <a href={e.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
                    agenda
                  </a>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ChangedRecently({ changes }: { changes: ChangesResponse }) {
  const shown = changes.changes.slice(0, 8);
  return (
    <section>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">Changed this week</h2>
        <span className="flex gap-3 text-[12px] font-semibold text-muted">
          <Link href="/topics?days=30" className="underline underline-offset-2 hover:text-ink">
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
      <p className="mb-3 text-[13px] text-muted">
        Topics whose status moved, and topics on the record for the first time, in the last{" "}
        {changes.days} days.
      </p>
      {shown.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
          No status changes in the window yet.
        </p>
      ) : (
        <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
          {shown.map((c) => (
            <li key={c.id}>
              <Link
                href={`/topics/${c.slug}#m-${c.meeting_id}`}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3.5 text-[15px] hover:bg-soft"
              >
                <span className="min-w-0 flex-1 basis-56 font-semibold">{c.name}</span>
                <span className="flex items-center gap-1.5 text-[13px]">
                  {c.kind === "new" ? (
                    <span className="rounded-full bg-tint-lavender px-2.5 py-[3px] text-xs font-semibold text-tint-lavender-text">
                      NEW
                    </span>
                  ) : (
                    <>
                      <StatusBadge status={c.from_status} />
                      <span aria-hidden className="text-muted-soft">→</span>
                    </>
                  )}
                  <StatusBadge status={c.to_status} />
                </span>
                <span className="w-full text-[13px] text-muted sm:w-auto">
                  <BodyTag body={c.body} /> · {formatDate(c.date)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const NO_HOT: HotTopicsResponse = { meetings: [], topics: [] };
const NO_CHANGES: ChangesResponse = { days: 7, since: "", changes: [] };
export default async function Briefing() {
  // The briefing is a dashboard of independent panels: one failing endpoint
  // should blank its own panel, not the page. Only the meetings list is
  // load-bearing enough to fall through to the error boundary.
  const [meetings, hotCouncil, hotPC, upcoming, changes] = await Promise.all([
    api.meetings(new URLSearchParams({ limit: "8" })),
    api.hotTopics("city_council").catch(() => NO_HOT),
    api.hotTopics("planning_commission").catch(() => NO_HOT),
    api.upcoming().catch(() => []),
    api.changes(7, 30).catch(() => NO_CHANGES),
  ]);
  // The headline counts the same window the change feed uses, so its two
  // halves describe the same week. When nothing met in that window, fall
  // back to the last meeting and say so, rather than showing an empty page.
  const withItems = meetings.filter((m) => m.agenda_item_count > 0);
  const inWindow = changes.since ? withItems.filter((m) => m.date >= changes.since) : [];
  const stale = inWindow.length === 0;
  const chosen = (stale ? withItems.slice(0, 1) : inWindow).slice(0, 4);
  const details = (
    await Promise.all(chosen.map((m) => api.meeting(String(m.id)).catch(() => null)))
  ).filter((m): m is MeetingDetail => m !== null);
  const decisions = deriveDecisions(details);
  // substantive votes first; consent agendas are real votes but read as housekeeping
  const shownDecisions = [
    ...decisions.filter((d) => !isConsent(d)),
    ...decisions.filter(isConsent),
  ].slice(0, 8);
  const latest = meetings[0] ? formatDate(meetings[0].date) : "";
  const sub = provenance(details, stale, changes.days);

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">
          The briefing · Week of {latest} · City of Fairfax, VA
        </div>
        <FollowButton target={{ kind: "briefing" }} label="Get this weekly by email" size="sm" />
      </div>
      <AskHound />
      <div className="mb-6 max-w-[900px]">
        <h1 className="text-[32px] font-medium leading-[1.15] tracking-[-0.5px] [text-wrap:balance]">
          {headline(decisions, changes.changes.length)}
        </h1>
        {sub && <p className="mt-2 text-sm text-muted">{sub}</p>}
      </div>
      {/* min-w-0: on phones both columns share one track, and a no-wrap row
          inside would otherwise widen the whole page */}
      <div className="grid gap-8 md:grid-cols-[1.5fr_1fr]">
        <div className="flex min-w-0 flex-col gap-8">
          <ChangedRecently changes={changes} />

          <section>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-xl font-semibold">Measures passed</h2>
              {details.length === 1 && (
                <Link
                  href={`/meetings/${details[0].id}`}
                  className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                >
                  full {formatDate(details[0].date)} meeting
                </Link>
              )}
            </div>
            <p className="mb-3 text-[13px] text-muted">
              Every vote taken, with the outcome in a line. Consent agendas last.
            </p>
            <div className="flex flex-col gap-3">
              {shownDecisions.map((d, i) =>
                isConsent(d) ? (
                  <Link
                    key={i}
                    href={`/meetings/${d.meetingId}`}
                    className="rounded-2xl border border-hairline bg-canvas px-5 py-3 hover:border-ink"
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2.5 py-[3px] text-xs font-semibold ${d.tint}`}>
                        {d.badge}
                      </span>
                      <BodyTag body={d.body} className="text-[13px] text-muted" />
                      <span className="text-[13px] text-muted">{d.meta}</span>
                    </div>
                    <div className="text-sm">
                      <span className="font-medium">{d.title}.</span>{" "}
                      <span className="text-muted">{clip(d.text, 140)}</span>
                    </div>
                  </Link>
                ) : (
                  <Link
                    key={i}
                    href={`/meetings/${d.meetingId}`}
                    className="rounded-2xl border border-hairline bg-canvas p-4 px-5 hover:border-ink"
                  >
                    <div className="mb-1.5 flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2.5 py-[3px] text-xs font-semibold ${d.tint}`}>
                        {d.badge}
                      </span>
                      <BodyTag body={d.body} className="text-[13px] text-muted" />
                      <span className="text-[13px] text-muted">{d.meta}</span>
                    </div>
                    <div className="mb-1 font-semibold">{d.title}</div>
                    <p className="text-sm leading-[1.55] text-body">{clip(d.text, 220)}</p>
                  </Link>
                ),
              )}
              {shownDecisions.length === 0 && (
                <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
                  No recent decisions extracted yet.
                </p>
              )}
            </div>
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <NextUp events={upcoming} />
          <HotPanel
            hot={hotCouncil}
            variant="teal"
            eyebrow="Hot right now · City Council"
            heading="What the council is spending its time on"
          />
          <HotPanel
            hot={hotPC}
            variant="cream"
            eyebrow="Hot right now · Planning Commission"
            heading="What the commission is spending its time on"
          />
        </div>
      </div>
    </div>
  );
}
