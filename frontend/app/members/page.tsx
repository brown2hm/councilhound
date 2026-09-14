import Link from "next/link";
import { api, formatDate, type MemberSummary } from "@/lib/api";

export const metadata = {
  title: "Members",
  description:
    "City of Fairfax council members and commissioners: how each one votes, how often, and where they last said no, parsed from meeting minutes and rosters.",
};

export const dynamic = "force-dynamic";

const isCouncil = (m: MemberSummary) => m.roles.some((r) => r === "Mayor" || r === "Councilmember");
const isMayor = (m: MemberSummary) => m.roles.includes("Mayor");

/** Motion descriptions arrive as filed ("Motion to approve…"). Drop the
 * opener and clip at a word so the cell reads as a subject. */
function subjectOf(text: string | null, max = 72): string {
  if (!text) return "";
  let t = text
    .replace(/^(motion to |approval of |approve |consideration of |adopt(ion of)? )(an? |the )?/i, "")
    .trim();
  if (t) t = t.charAt(0).toUpperCase() + t.slice(1);
  if (t.length <= max) return t;
  let cut = t.slice(0, max).replace(/\s+\S*$/, "");
  // never end inside a parenthetical, or on a joining word
  const open = cut.lastIndexOf("(");
  if (open > 0 && !cut.slice(open).includes(")")) cut = cut.slice(0, open);
  cut = cut.replace(/\s+(and|or|of|the|to|for|a|an|in|on|at|by|with)$/i, "");
  return cut.replace(/[\s,;:(–-]+$/, "") + "…";
}

function split(m: MemberSummary) {
  const s = m.vote_stats ?? {};
  const yes = s.yes ?? 0;
  const no = s.no ?? 0;
  const away = (s.absent ?? 0) + (s.abstain ?? 0);
  const total = Math.max(1, yes + no + away);
  return { yes, no, away, pct: (n: number) => `${(100 * n) / total}%` };
}

function SplitBar({ m }: { m: MemberSummary }) {
  const { yes, no, away, pct } = split(m);
  if (m.votes_cast === 0) return <span className="text-[13px] text-muted-soft">No recorded votes</span>;
  return (
    <div>
      <div
        className="flex h-2 w-[140px] overflow-hidden rounded-full bg-strong"
        role="img"
        aria-label={`${yes} yes, ${no} no, ${away} absent or abstained`}
      >
        <span className="bg-teal" style={{ width: pct(yes) }} />
        <span className="bg-hound" style={{ width: pct(no) }} />
        <span className="bg-[#d9d3c2]" style={{ width: pct(away) }} />
      </div>
      <div className="mt-1 text-[12px] tabular-nums text-muted">
        {yes} yes · {no} no · {away} absent
      </div>
    </div>
  );
}

function Legend() {
  const items = [
    ["bg-teal", "yes"],
    ["bg-hound", "no"],
    ["bg-[#d9d3c2]", "absent or abstained"],
  ];
  return (
    <span className="flex flex-wrap gap-3.5 text-[12px] text-muted">
      {items.map(([cls, label]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-[3px] ${cls}`} />
          {label}
        </span>
      ))}
    </span>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={`whitespace-nowrap border-b border-ink px-3 pb-2 text-left text-[11px] font-semibold uppercase tracking-[1px] text-muted first:pl-0 last:pr-0 ${className}`}
    >
      {children}
    </th>
  );
}

function RecordTable({ list, dot }: { list: MemberSummary[]; dot: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <Th className="w-[26%]">Member</Th>
            <Th className="text-right">Votes</Th>
            <Th className="hidden md:table-cell">Split</Th>
            <Th className="text-right">With the outcome</Th>
            <Th className="w-[34%]">Last no vote</Th>
            <Th className="hidden text-right md:table-cell">Last vote</Th>
          </tr>
        </thead>
        <tbody>
          {list.map((m) => (
            <tr key={m.slug} className="border-b border-hairline align-top hover:bg-soft">
              <td className="py-3 pr-3">
                <Link href={`/members/${m.slug}`} className="text-base font-semibold underline-offset-2 hover:underline">
                  <span aria-hidden className={`mr-1.5 inline-block h-2 w-2 rounded-full ${dot}`} />
                  {m.name}
                </Link>
                <div className="text-[12px] text-muted">
                  {m.roles.join(" · ")}
                  {isMayor(m) && <span className="text-muted-soft"> · votes only to break a tie</span>}
                </div>
              </td>
              <td className="px-3 py-3 text-right text-[15px] tabular-nums">{m.votes_cast}</td>
              <td className="hidden px-3 py-3 md:table-cell">
                <SplitBar m={m} />
              </td>
              <td className="px-3 py-3 text-right text-[15px] tabular-nums">
                {m.with_outcome_pct === null ? <span className="text-muted-soft">—</span> : `${m.with_outcome_pct}%`}
              </td>
              <td className="px-3 py-3">
                {m.last_no ? (
                  <Link href={`/meetings/${m.last_no.meeting_id}`} className="underline-offset-2 hover:underline">
                    <span className="tabular-nums text-muted">{formatDate(m.last_no.date)}</span>
                    {" · "}
                    {subjectOf(m.last_no.subject)}
                  </Link>
                ) : (
                  <span className="text-muted-soft">none on record</span>
                )}
              </td>
              <td className="hidden whitespace-nowrap py-3 pl-3 text-right text-[13px] tabular-nums text-muted md:table-cell">
                {m.last_vote ? formatDate(m.last_vote) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function MembersPage() {
  const members = await api.members();
  const current = members.filter((m) => m.is_current);
  const council = current.filter(isCouncil);
  const commission = current.filter((m) => !isCouncil(m));
  const former = members.filter((m) => !m.is_current);

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Members</h1>
      <p className="mb-7 max-w-[76ch] text-sm text-muted">
        Voting records and recorded positions, parsed from meeting minutes and rosters. &ldquo;With the outcome&rdquo; is the
        share of a member&apos;s yes and no votes cast on the side that won.
      </p>

      <section className="mb-10">
        <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="flex items-center gap-2 text-[22px] font-semibold tracking-[-0.3px]">
            <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-teal" /> City Council
          </h2>
          <Legend />
        </div>
        <RecordTable list={council} dot="bg-teal" />
      </section>

      <section className="mb-10">
        <h2 className="mb-2.5 flex items-center gap-2 text-[22px] font-semibold tracking-[-0.3px]">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-ochre" /> Planning Commission &amp; boards
        </h2>
        <RecordTable list={commission} dot="bg-ochre" />
      </section>

      {former.length > 0 && (
        <section>
          <h2 className="mb-0.5 text-lg font-semibold text-muted">Former members</h2>
          <p className="mb-2.5 text-[13px] text-muted">No longer on the roster; their voting history stays on the record.</p>
          <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            {former.map((m) => (
              <Link
                key={m.slug}
                href={`/members/${m.slug}`}
                className="flex items-baseline justify-between gap-2 border-b border-hairline py-1.5 text-sm hover:bg-soft"
              >
                <span>
                  <span className="font-semibold">{m.name}</span>{" "}
                  <span className="text-[12px] text-muted">{m.roles[0] ?? "Member"}</span>
                </span>
                <span className="whitespace-nowrap text-[12px] tabular-nums text-muted">
                  {m.votes_cast} votes{m.last_vote ? ` · to ${formatDate(m.last_vote)}` : ""}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
