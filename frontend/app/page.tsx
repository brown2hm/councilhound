import Image from "next/image";
import Link from "next/link";
import BodyTag from "@/components/BodyTag";
import {
  api,
  formatDate,
  type HotTopicsResponse,
  type MeetingDetail,
  type MeetingStats,
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
  return decisions.slice(0, 6);
}

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const word = (n: number) => WORDS[n] ?? String(n);

function headline(decisions: Decision[]): string {
  const passed = decisions.filter((d) => d.badge.startsWith("PASSED")).length;
  const failed = decisions.filter((d) => d.badge.startsWith("FAILED")).length;
  const other = decisions.length - passed - failed;
  const parts: string[] = [];
  if (passed) parts.push(`${word(passed)} measure${passed === 1 ? "" : "s"} passed`);
  if (failed) parts.push(`${word(failed)} failed`);
  if (other) parts.push(`${word(other)} still in motion`);
  if (parts.length === 0) return "The latest from city hall.";
  const sentence =
    parts.length > 1 ? parts.slice(0, -1).join(", ") + ", and " + parts.at(-1) : parts[0];
  return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
}

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
                className={`h-1.5 rounded-full ${teal ? "bg-mint" : "bg-ochre"}`}
                style={{ width: `${Math.max(6, (t.seconds / max) * 100)}%` }}
              />
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
          href="/topics?type=hot"
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

function StatTiles({ stats }: { stats: MeetingStats }) {
  const tiles = [
    { value: stats.meetings_held, label: "meetings held" },
    { value: stats.hours_of_meetings, label: "hours in session" },
    { value: stats.votes_taken, label: "votes taken" },
    {
      value: `${stats.motions_passed}–${stats.motions_failed}`,
      label: "passed vs. failed",
    },
  ];
  return (
    <div className="mb-7 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-2xl border border-hairline bg-canvas p-4 px-5">
          <div className="text-[26px] font-medium leading-none tracking-[-0.5px]">{t.value}</div>
          <div className="mt-1.5 text-[13px] text-muted">
            {t.label} <span className="text-muted-soft">· {stats.days} days</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default async function Briefing() {
  const [meetings, hotCouncil, hotPC, stats] = await Promise.all([
    api.meetings(new URLSearchParams({ limit: "6" })),
    api.hotTopics("city_council"),
    api.hotTopics("planning_commission"),
    api.stats(30),
  ]);
  const withItems = meetings.filter((m) => m.agenda_item_count > 0).slice(0, 4);
  const details = await Promise.all(withItems.map((m) => api.meeting(String(m.id))));
  const decisions = deriveDecisions(details);
  const latest = meetings[0] ? formatDate(meetings[0].date) : "";

  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        The briefing · Week of {latest} · City of Fairfax, VA
      </div>
      <StatTiles stats={stats} />
      <div className="grid gap-8 md:grid-cols-[1.5fr_1fr]">
        <div>
          <h1 className="mb-5 text-[32px] font-medium leading-[1.15] tracking-[-0.5px]">
            {headline(decisions)}
          </h1>
          <div className="flex flex-col gap-3">
            {decisions.map((d, i) => (
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
                <p className="text-sm leading-[1.55] text-body">{d.text.slice(0, 220)}</p>
              </Link>
            ))}
            {decisions.length === 0 && (
              <p className="text-sm text-muted">No recent decisions extracted yet.</p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-5">
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

          <section className="rounded-3xl bg-card p-6">
            <div className="mb-2.5 flex items-center gap-2.5">
              <Image src="/brand/hound.png" alt="" width={34} height={30} className="h-[30px] w-auto" />
              <span className="font-semibold">Ask the hound</span>
            </div>
            <form
              action="/ask"
              method="get"
              className="flex items-center justify-between gap-2 rounded-xl border border-hairline bg-canvas p-1.5 pl-4"
            >
              <input
                name="q"
                placeholder="Search the meeting record…"
                className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted-soft"
              />
              <button className="shrink-0 rounded-lg bg-ink px-3.5 py-2 text-[13px] font-semibold text-white">
                Ask
              </button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
