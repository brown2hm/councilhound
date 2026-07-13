import Image from "next/image";
import Link from "next/link";
import { api, BODY_LABELS, formatDate, type MeetingDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

interface Decision {
  badge: string;
  tint: string;
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
    const meta = (label: string) =>
      `${BODY_LABELS[m.body] ?? m.body} · ${formatDate(m.date)} · item ${label}`;
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
          meta: meta(item.label),
          title: item.title,
          text: item.outcome ?? vote.description ?? "",
          meetingId: m.id,
        });
      } else if (item.outcome && /recommend/i.test(item.outcome) && m.body === "planning_commission") {
        decisions.push({
          badge: "RECOMMENDED",
          tint: TINTS.proposed,
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

export default async function Briefing() {
  const [meetings, hot] = await Promise.all([
    api.meetings(new URLSearchParams({ limit: "6" })),
    api.hotTopics(),
  ]);
  const withItems = meetings.filter((m) => m.agenda_item_count > 0).slice(0, 4);
  const details = await Promise.all(withItems.map((m) => api.meeting(String(m.id))));
  const decisions = deriveDecisions(details);
  const hotTop = hot.topics.slice(0, 5);
  const maxSeconds = Math.max(1, ...hotTop.map((t) => t.seconds));
  const latest = meetings[0] ? formatDate(meetings[0].date) : "";

  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        The briefing · Week of {latest} · City of Fairfax, VA
      </div>
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
                <div className="mb-1.5 flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-[3px] text-xs font-semibold ${d.tint}`}>
                    {d.badge}
                  </span>
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
          <section className="rounded-3xl bg-teal p-7 text-white">
            <div className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-mint">
              Hot right now
            </div>
            <h2 className="mb-5 text-2xl font-medium leading-tight tracking-[-0.3px]">
              What the council is spending its time on
            </h2>
            <div className="flex flex-col gap-3.5">
              {hotTop.map((t, i) => (
                <Link key={t.slug} href={`/topics/${t.slug}`} className="block">
                  <div className="mb-[5px] flex items-baseline justify-between gap-3">
                    <span className="text-sm font-semibold">
                      {i + 1}&nbsp; {t.name}
                    </span>
                    <span className="shrink-0 text-[13px] font-semibold text-mint">
                      {Math.round(t.seconds / 60)} min
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/[0.14]">
                    <div
                      className="h-1.5 rounded-full bg-mint"
                      style={{ width: `${Math.max(6, (t.seconds / maxSeconds) * 100)}%` }}
                    />
                  </div>
                </Link>
              ))}
            </div>
            <div className="mt-5">
              <Link
                href="/topics?type=hot"
                className="inline-block rounded-xl bg-canvas px-5 py-3 text-sm font-semibold leading-none text-ink"
              >
                See all hot topics
              </Link>
            </div>
          </section>

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
