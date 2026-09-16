import Link from "next/link";
import { cache } from "react";
import FollowButton from "@/components/FollowButton";
import MemberLedger from "@/components/MemberLedger";
import { AlignmentList, CategoryBars, MattersList, MeetingStrip, NoVotesByMember, SplitBar, SplitPatterns } from "@/components/MemberRecord";
import StatusBadge from "@/components/StatusBadge";
import { api, BODY_SHORT, bodyLabel, formatDate, type MemberDetail, type MemberVote } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";
import { resultLine, subjectOf } from "@/lib/subject";

export const dynamic = "force-dynamic";

const getMember = cache((slug: string) => api.member(slug));

export async function generateMetadata({ params }: { params: { slug: string } }) {
  const member = await requireRecord(getMember(params.slug));
  return {
    title: member.name,
    description: `${member.name}'s record in City of Fairfax meetings: ${member.record.votes} votes, where the no votes fall, who they vote with, and positions recorded in the minutes.`,
  };
}

const INSTRUMENTS = new Set(["ordinance", "resolution", "case_number"]);
const monthYear = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });
const firstName = (name: string) => name.split(" ")[0];

/** One sentence that states the record before any figure does. */
function lede(m: MemberDetail): string {
  const r = m.record;
  const first = firstName(m.name);
  const isMayor = m.roles.includes("Mayor");
  if (r.votes === 0) return `No recorded votes yet${isMayor ? "; the mayor votes only to break a tie" : ""}.`;
  const body = m.body ? BODY_SHORT[m.body] ?? "" : "";
  const parts = [
    `${r.votes} recorded ${r.votes === 1 ? "vote" : "votes"} in ${r.meetings} ${body} ${r.meetings === 1 ? "meeting" : "meetings"} since ${r.first_vote ? monthYear(r.first_vote) : ""}${isMayor ? ", cast only to break ties" : ""}.`,
  ];
  if (r.contested > 0) {
    const mt = r.minority;
    const detail =
      mt.total > 0
        ? `: ${mt.no_on_passed} no ${mt.no_on_passed === 1 ? "vote" : "votes"} on motions that passed${mt.yes_on_failed ? ` and ${mt.yes_on_failed} yes ${mt.yes_on_failed === 1 ? "vote" : "votes"} on motions that failed` : ""}.`
        : ".";
    const times = mt.total === 0 ? "never in the minority" : `in the minority ${mt.total === 1 ? "once" : `${mt.total} times`}`;
    parts.push(`On the ${r.contested} where anyone voted no, ${first} was ${times}${detail}`);
  }
  const top = m.colleagues.find((c) => c.agree_pct !== null && c.agree_n >= 5);
  if (r.comparisons && top) parts.push(`Votes most often with ${top.name}, on ${top.agree_pct}% of contested votes.`);
  return parts.join(" ");
}

/** Who else voted no on a motion, as names when they are colleagues. */
function alsoNo(v: MemberVote, m: MemberDetail): string[] {
  const byLast = new Map<string, string>();
  for (const c of m.colleagues) {
    const last = c.name.split(" ").slice(-1)[0];
    byLast.set(last.toLowerCase(), last);
    if (last.includes("-")) byLast.set(last.split("-").slice(-1)[0].toLowerCase(), last);
  }
  const mine = m.name.split(" ").slice(-1)[0].toLowerCase();
  return Object.entries(v.breakdown)
    .filter(([who, cast]) => cast === "no" && who.toLowerCase() !== mine && !(mine.includes("-") && mine.endsWith(who.toLowerCase())))
    .map(([who]) => byLast.get(who.toLowerCase()) ?? who);
}

/** The no votes, grouped by the matter each motion was about, identical
 * motions on one item collapsed. */
function NoVotesByMatter({ member }: { member: MemberDetail }) {
  const nos = member.votes.filter((v) => v.vote === "no");
  if (nos.length === 0) return null;
  type Motion = { v: MemberVote; count: number };
  const groups = new Map<string, { href: string | null; motions: Map<string, Motion> }>();
  for (const v of nos) {
    // a project or topic names the matter better than the parcel it sits on
    const topic =
      v.topics.find((t) => t.entity_type === "project" || t.entity_type === "topic") ??
      v.topics.find((t) => !INSTRUMENTS.has(t.entity_type));
    const name = topic?.name ?? subjectOf(v.item_title ?? v.description, 60);
    const g = groups.get(name) ?? { href: topic ? `/topics/${topic.slug}` : null, motions: new Map() };
    const k = `${v.meeting_id}|${v.item_label}`;
    const motion = g.motions.get(k);
    if (motion) motion.count += 1;
    else g.motions.set(k, { v, count: 1 });
    groups.set(name, g);
  }
  return (
    <section className="border-t-2 border-ink pt-4">
      <h2 className="text-[22px] font-semibold tracking-[-0.3px]">
        The {nos.length} no {nos.length === 1 ? "vote" : "votes"}
      </h2>
      <p className="mb-2 mt-1 text-[13px] text-muted">
        Grouped by what was before the {member.body ? BODY_SHORT[member.body] : "body"}. The tally is the whole body&apos;s; &ldquo;with&rdquo; names who voted no alongside{" "}
        {firstName(member.name)}.
      </p>
      {Array.from(groups.entries()).map(([name, g]) => (
        <div key={name} className="border-t border-hairline py-3">
          <div className="mb-0.5 text-[15px] font-semibold">
            {g.href ? (
              <Link href={g.href} className="underline-offset-2 hover:underline">
                {name}
              </Link>
            ) : (
              name
            )}
          </div>
          {Array.from(g.motions.values()).map(({ v, count }) => {
            const others = alsoNo(v, member);
            return (
              <div key={`${v.meeting_id}-${v.item_label}`} className="grid grid-cols-[110px_minmax(0,1fr)] items-baseline gap-x-3 gap-y-0.5 py-1 text-[13px] sm:grid-cols-[110px_minmax(0,1fr)_160px]">
                <Link href={`/meetings/${v.meeting_id}`} className="font-semibold tabular-nums underline-offset-2 hover:underline">
                  {formatDate(v.date)}
                </Link>
                <span className="text-body">
                  {g.href ? subjectOf(v.item_title ?? v.description, 110) : v.description ?? ""}
                  {count > 1 && <span className="text-muted-soft"> · {count} motions</span>}
                  {v.item_label && <span className="text-muted"> · item {v.item_label}</span>}
                </span>
                <span className="col-start-2 tabular-nums sm:col-start-3 sm:text-right">
                  <span className={`font-semibold ${v.motion_result === "failed" ? "text-tint-coral-text" : v.motion_result === "passed" ? "text-tint-mint-text" : "text-tint-ochre-text"}`}>
                    {resultLine(v.tally, v.motion_result)}
                  </span>
                  <span className="block text-[12px] text-muted">{others.length ? `with ${others.join(", ")}` : "the only no vote"}</span>
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </section>
  );
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div>
      <span className="text-[15px] font-semibold tabular-nums text-ink">{value}</span> {label}
    </div>
  );
}

export default async function MemberPage({ params }: { params: { slug: string } }) {
  const member = await requireRecord(getMember(params.slug));
  const r = member.record;
  const first = firstName(member.name);
  const isMayor = member.roles.includes("Mayor");
  const names: Record<string, string> = { [member.slug]: member.name };
  for (const c of member.colleagues) names[c.slug] = c.name;
  const votingColleagues = member.colleagues.filter((c) => c.votes_cast > 0);
  const eyebrow = [
    member.is_current ? null : "Former",
    member.roles.join(" · ") || "Member",
    member.body ? bodyLabel(member.body) : null,
    r.first_vote ? `on the record since ${monthYear(r.first_vote)}` : null,
    r.meetings > 1 ? `${r.meetings} meetings` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const upcoming = member.upcoming.length > 0 && member.is_current && (
    <div className="rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-sm text-tint-ochre-text">
      <span className="font-semibold">Next:</span>{" "}
      {member.upcoming.map((u, i) => (
        <span key={u.event_id}>
          {i > 0 && " · "}
          {u.title}
          {u.starts_at && ` · ${new Date(u.starts_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}`}
          {" · "}
          <Link href={`/meetings/upcoming/${encodeURIComponent(u.event_id)}`} className="font-semibold underline underline-offset-2">
            {u.in_progress ? "in progress" : "meeting brief"}
          </Link>
        </span>
      ))}
    </div>
  );

  const categories = r.comparisons && member.categories.length >= 2 && (
    <section className="border-t-2 border-ink pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[22px] font-semibold tracking-[-0.3px]">Where the no votes fall</h2>
        <span className="text-[11px] text-muted">
          <span aria-hidden className="mr-1 inline-block h-2.5 w-2.5 rounded-[3px] bg-teal opacity-20" />
          votes cast
          <span aria-hidden className="ml-2.5 mr-1 inline-block h-2.5 w-2.5 rounded-[3px] bg-hound" />
          no votes
        </span>
      </div>
      <p className="mb-2.5 mt-1 text-[13px] text-muted">{first}&apos;s {r.votes} votes by the kind of item, read from the agenda titles.</p>
      <CategoryBars categories={member.categories} />
    </section>
  );

  const mattersShown = member.matters.filter((m) => m.n >= 2);
  const matters = mattersShown.length >= 3 && (
    <section className="border-t-2 border-ink pt-4">
      <h2 className="text-[22px] font-semibold tracking-[-0.3px]">The matters {first} has voted on most</h2>
      <p className="mb-2 mt-1 text-[13px] text-muted">
        Every motion links to the topic it was about. Several motions on one night count separately.
      </p>
      <MattersList matters={mattersShown} />
    </section>
  );

  const commentary = member.commentary.length > 0 && (
    <section className="border-t-2 border-ink pt-4">
      <h2 className="text-[22px] font-semibold tracking-[-0.3px]">On the record</h2>
      <p className="mb-1.5 mt-1 text-[13px] text-muted">
        What the minutes and transcripts record {first} saying, by topic. {member.commentary.length} topics.
      </p>
      <ul className="border-t border-hairline">
        {member.commentary.map((c, i) => (
          <li key={i} className="grid gap-x-4 gap-y-1 border-b border-hairline py-3 sm:grid-cols-[200px_minmax(0,1fr)]">
            <div>
              <Link href={`/topics/${c.topic_slug}`} className="text-sm font-semibold underline-offset-2 hover:underline">
                {c.topic_name}
              </Link>
              <div className="mt-1">
                <StatusBadge status={c.topic_status} />
              </div>
            </div>
            <p className="text-sm leading-[1.6] text-body">{c.summary}</p>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-muted">Positions as recorded in meeting minutes; votes without recorded comment aren&apos;t summarized.</p>
    </section>
  );

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <Link href="/members" className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
        ← All members
      </Link>
      <div className="mb-1.5 mt-5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">{eyebrow}</div>

      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-8">
          <div>
            <h1 className="mb-2.5 text-[36px] font-medium leading-[1.1] tracking-[-0.7px]">{member.name}</h1>
            <p className="max-w-[70ch] text-[19px] leading-[1.45] tracking-[-0.2px] text-body-strong">{lede(member)}</p>
            {upcoming && <div className="mt-6">{upcoming}</div>}
          </div>
          {categories}
          <NoVotesByMatter member={member} />
          {matters}
          {commentary}
          <section className="border-t-2 border-ink pt-4">
            <h2 className="mb-3 text-[22px] font-semibold tracking-[-0.3px]">Voting record</h2>
            <MemberLedger votes={member.votes} possessive={`${first}’s`} />
          </section>
        </div>

        <aside className="flex min-w-0 flex-col gap-6 lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-2xl bg-card px-5 py-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Record</div>
            <div className="flex items-baseline gap-2">
              <span className="text-[28px] font-medium tabular-nums tracking-[-0.5px]">{r.votes}</span>
              <span className="text-sm text-muted">
                {r.votes === 1 ? "vote" : "votes"} in {r.meetings} {r.meetings === 1 ? "meeting" : "meetings"}
              </span>
            </div>
            {r.votes > 0 && <SplitBar stats={member.vote_stats} className="my-2.5" />}
            {r.votes > 0 && (
              <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[13px] text-muted">
                {r.with_outcome_pct !== null && <Stat value={`${r.with_outcome_pct}%`} label="with the outcome" />}
                <Stat value={r.minority.total} label="in the minority" />
                {r.close_votes.total > 0 && <Stat value={`${r.close_votes.lost} of ${r.close_votes.total}`} label="one-vote margins lost" />}
                <Stat value={r.lone_no} label={r.lone_no === 1 ? "lone no vote" : "lone no votes"} />
              </div>
            )}
            <div className="mt-3 text-[12px] text-muted">
              {r.absent_meetings.length > 0 && (
                <>
                  Absent{" "}
                  {r.absent_meetings.map((a, i) => (
                    <span key={a.meeting_id}>
                      {i > 0 && ", "}
                      <Link href={`/meetings/${a.meeting_id}`} className="underline underline-offset-2 hover:text-ink">
                        {formatDate(a.date)}
                      </Link>
                    </span>
                  ))}
                  .{" "}
                </>
              )}
              {isMayor && "The mayor votes only to break a tie. "}
              {r.last_vote && !member.is_current && `Last vote ${formatDate(r.last_vote)}.`}
            </div>
            <div className="mt-3.5">
              <FollowButton target={{ kind: "member", entitySlug: member.slug }} label={`Follow ${first}'s votes`} />
            </div>
          </div>

          {r.comparisons && votingColleagues.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-[1.5px] text-muted">No votes, current {member.body ? BODY_SHORT[member.body] : "members"}</div>
              <p className="mb-2.5 text-[12px] text-muted">Members who joined later have fewer votes on record.</p>
              <NoVotesByMember colleagues={member.colleagues} self={{ slug: member.slug, name: member.name, no_votes: member.vote_stats.no ?? 0 }} />
            </div>
          )}

          {r.comparisons && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Votes with</div>
              <p className="mb-2.5 text-[12px] text-muted">Share of the {r.contested} contested votes (someone voted no) where each colleague voted the same way.</p>
              <AlignmentList colleagues={member.colleagues} />
            </div>
          )}

          {r.comparisons && member.splits.length > 0 && (
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">How the {member.body ? BODY_SHORT[member.body] : "body"} splits</span>
                <span className="text-[11px] text-muted">
                  <span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full bg-teal" />
                  yes
                  <span aria-hidden className="ml-2 mr-1 inline-block h-2 w-2 rounded-full bg-hound" />
                  no
                </span>
              </div>
              <p className="mb-2 text-[12px] text-muted">
                The most common line-ups on {first}&apos;s contested votes. Ringed dot is {first}; then{" "}
                {member.split_order
                  .slice(1)
                  .map((s) => names[s]?.split(" ").slice(-1)[0] ?? s)
                  .join(", ")}
                .
              </p>
              <SplitPatterns splits={member.splits} order={member.split_order} names={names} self={member.slug} />
            </div>
          )}

          {member.by_meeting.length >= 2 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Meeting by meeting</div>
              <p className="mb-2 text-[12px] text-muted">Votes per meeting, {r.meetings} meetings. Bars link to the meeting.</p>
              <MeetingStrip meetings={member.by_meeting} />
            </div>
          )}

          {member.colleagues.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Colleagues</div>
              <div className="text-[13px] leading-[1.7] text-body">
                {member.colleagues
                  .slice()
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((c, i) => (
                    <span key={c.slug}>
                      {i > 0 && " · "}
                      <Link href={`/members/${c.slug}`} className="underline-offset-2 hover:underline">
                        {c.name}
                      </Link>
                      {c.roles[0] && c.roles[0] !== "Councilmember" && c.roles[0] !== "Commissioner" && c.roles[0] !== "School Board Member" && (
                        <span className="text-muted-soft"> {c.roles[0]}</span>
                      )}
                    </span>
                  ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

