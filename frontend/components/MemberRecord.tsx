import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { formatDate, type MemberCategory, type MemberColleague, type MemberMatter, type MemberMeeting, type MemberSplit } from "@/lib/api";

// The member page's small figures. Every one is a plain flex/grid of divs
// so it inherits the page's tokens; colors follow the roster table (yes =
// teal, no = hound, away = sand) and body dots elsewhere.

const AWAY = "bg-[#d9d3c2]";

const fmtShort = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" }).replace(", ", " ’");

/** Yes / no / away split as one bar, with its legend. */
export function SplitBar({ stats, className = "" }: { stats: Record<string, number>; className?: string }) {
  const yes = stats.yes ?? 0;
  const no = stats.no ?? 0;
  const away = (stats.absent ?? 0) + (stats.abstain ?? 0);
  const total = Math.max(1, yes + no + away);
  const pct = (n: number) => `${(100 * n) / total}%`;
  return (
    <div className={className}>
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-strong" role="img" aria-label={`${yes} yes, ${no} no, ${away} absent or abstained`}>
        {yes > 0 && <span className="bg-teal" style={{ width: pct(yes) }} />}
        {no > 0 && <span className="bg-hound" style={{ width: pct(no) }} />}
        {away > 0 && <span className={AWAY} style={{ width: pct(away) }} />}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3.5 gap-y-1 text-[12px] tabular-nums text-muted">
        <Legend cls="bg-teal" label={`${yes} yes`} />
        <Legend cls="bg-hound" label={`${no} no`} />
        <Legend cls={AWAY} label={`${away} absent or abstained`} />
      </div>
    </div>
  );
}

function Legend({ cls, label, faded = false }: { cls: string; label: string; faded?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-[3px] ${cls} ${faded ? "opacity-30" : ""}`} />
      {label}
    </span>
  );
}

/** Votes by kind of item, with this member's no votes overlaid. */
export function CategoryBars({ categories }: { categories: MemberCategory[] }) {
  const shown = categories.filter((c) => c.votes > 0);
  if (shown.length < 2) return null;
  const max = Math.max(...shown.map((c) => c.votes));
  return (
    <div>
      {shown.map((c) => (
        <div key={c.key} className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-3 py-1 text-[13px] sm:grid-cols-[220px_minmax(0,1fr)_150px]">
          <span className="font-semibold">{c.label}</span>
          <span className="relative hidden h-2.5 sm:block" aria-hidden>
            <span className="absolute left-0 top-0 h-2.5 rounded-r bg-teal opacity-20" style={{ width: `${(100 * c.votes) / max}%` }} />
            {c.no > 0 && <span className="absolute left-0 top-0 h-2.5 rounded-r bg-hound" style={{ width: `${(100 * c.no) / max}%` }} />}
          </span>
          <span className="tabular-nums text-muted">
            <span className="font-semibold text-ink">{c.votes}</span> {c.votes === 1 ? "vote" : "votes"}
            {c.no > 0 && (
              <>
                {" · "}
                <span className="font-semibold text-hound">{c.no} no</span>
              </>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

/** The matters voted on most, each with its own yes/no split. */
export function MattersList({ matters }: { matters: MemberMatter[] }) {
  return (
    <div>
      {matters.map((m) => {
        const v = m.votes;
        const total = Math.max(1, m.n);
        const parts = (["yes", "no", "abstain", "absent"] as const).filter((k) => v[k]).map((k) => `${v[k]} ${k}`);
        return (
          <div key={m.slug} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-1 border-t border-hairline py-2.5 text-sm sm:grid-cols-[minmax(0,1fr)_120px_150px]">
            <span className="flex flex-wrap items-center gap-2">
              <Link href={`/topics/${m.slug}`} className="font-semibold underline-offset-2 hover:underline">
                {m.name}
              </Link>
              <StatusBadge status={m.current_status} />
            </span>
            <span className="flex h-2 w-[120px] gap-[2px] overflow-hidden rounded-full bg-strong" role="img" aria-label={parts.join(", ")}>
              {v.yes ? <span className="bg-teal" style={{ width: `${(100 * v.yes) / total}%` }} /> : null}
              {v.no ? <span className="bg-hound" style={{ width: `${(100 * v.no) / total}%` }} /> : null}
              {v.abstain ? <span className="bg-ochre" style={{ width: `${(100 * v.abstain) / total}%` }} /> : null}
              {v.absent ? <span className={AWAY} style={{ width: `${(100 * v.absent) / total}%` }} /> : null}
            </span>
            <span className="col-span-2 text-[12px] tabular-nums text-muted sm:col-span-1">
              <span className="font-semibold text-ink">{m.n}</span> {m.n === 1 ? "vote" : "votes"} · {parts.join(" · ")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Share of contested votes where each colleague voted the same way. */
export function AlignmentList({ colleagues }: { colleagues: MemberColleague[] }) {
  const shown = colleagues.filter((c) => c.agree_pct !== null && c.agree_n >= 5);
  if (shown.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {shown.map((c) => (
        <div key={c.slug} className="grid grid-cols-[118px_minmax(0,1fr)_40px] items-center gap-2.5 text-[13px]">
          <Link href={`/members/${c.slug}`} className="truncate font-semibold underline-offset-2 hover:underline" title={`${c.name}: same side on ${c.agree_n} contested votes`}>
            {c.name}
          </Link>
          <span className="block h-1.5 overflow-hidden rounded-full bg-strong" aria-hidden>
            <span className="block h-1.5 rounded-full bg-teal" style={{ width: `${c.agree_pct}%` }} />
          </span>
          <span className="text-right font-semibold tabular-nums text-tint-mint-text">{c.agree_pct}%</span>
        </div>
      ))}
    </div>
  );
}

/** No votes across the body's current members, this member highlighted. */
export function NoVotesByMember({ colleagues, self }: { colleagues: MemberColleague[]; self: { slug: string; name: string; no_votes: number } }) {
  const rows = [self, ...colleagues.filter((c) => c.votes_cast > 0).map((c) => ({ slug: c.slug, name: c.name, no_votes: c.no_votes }))].sort(
    (a, b) => b.no_votes - a.no_votes || a.name.localeCompare(b.name),
  );
  if (rows.length < 2) return null;
  const max = Math.max(1, ...rows.map((r) => r.no_votes));
  return (
    <div className="flex flex-col gap-[7px]">
      {rows.map((r) => {
        const me = r.slug === self.slug;
        return (
          <div key={r.slug} className="grid grid-cols-[118px_minmax(0,1fr)_28px] items-center gap-2.5 text-[13px]">
            <span className={`truncate ${me ? "font-semibold text-ink" : "font-medium text-muted"}`}>
              {me ? r.name : <Link href={`/members/${r.slug}`} className="underline-offset-2 hover:underline">{r.name}</Link>}
            </span>
            <span className="block h-1.5 overflow-hidden rounded-full bg-strong" aria-hidden>
              <span className={`block h-1.5 rounded-full ${me ? "bg-hound" : AWAY}`} style={{ width: `${(100 * r.no_votes) / max}%` }} />
            </span>
            <span className={`text-right font-semibold tabular-nums ${me ? "text-ink" : "text-muted"}`}>{r.no_votes}</span>
          </div>
        );
      })}
    </div>
  );
}

/** The most common line-ups on this member's contested votes: one dot per
 * member in `order`, filled for a no vote; this member ringed. */
export function SplitPatterns({ splits, order, names, self }: { splits: MemberSplit[]; order: string[]; names: Record<string, string>; self: string }) {
  if (splits.length === 0 || order.length < 3) return null;
  return (
    <div>
      {splits.map((s, i) => {
        const nos = new Set(s.no);
        return (
          <div key={i} className="grid grid-cols-[36px_auto_minmax(0,1fr)] items-center gap-2.5 py-1 text-[12px]">
            <span className="text-[15px] font-semibold tabular-nums">{s.count}×</span>
            <span className="flex gap-1" role="img" aria-label={`no: ${s.no.map((m) => names[m] ?? m).join(", ")}`}>
              {order.map((slug) => (
                <span
                  key={slug}
                  title={`${names[slug] ?? slug}: ${nos.has(slug) ? "no" : "yes"}`}
                  className={`inline-block h-3 w-3 rounded-full ${nos.has(slug) ? "bg-hound" : "bg-teal"} ${slug === self ? "ring-[1.5px] ring-ink ring-offset-2 ring-offset-canvas" : ""}`}
                />
              ))}
            </span>
            <span className="leading-[1.35] text-muted">no: {s.no.map((m) => lastName(names[m] ?? m)).join(", ")}</span>
          </div>
        );
      })}
    </div>
  );
}

const lastName = (name: string) => name.split(" ").filter((t) => !/^(jr|sr|ii|iii)\.?$/i.test(t)).slice(-1)[0] ?? name;

/** Votes per meeting: contested votes dark, unanimous faint, a tick over
 * meetings where this member voted no, a dashed outline for ones missed. */
export function MeetingStrip({ meetings }: { meetings: MemberMeeting[] }) {
  if (meetings.length < 2) return null;
  const max = Math.max(...meetings.map((m) => m.votes));
  const H = 56;
  const labelled = new Set<number>();
  let lastYear = "";
  meetings.forEach((m, i) => {
    const y = m.date.slice(0, 4);
    if (y !== lastYear || i === meetings.length - 1) {
      labelled.add(i);
      lastYear = y;
    }
  });
  return (
    <div>
      <div className="flex items-end gap-[2px]" style={{ height: H + 8 }}>
        {meetings.map((m) => {
          const h1 = Math.max(3, Math.round((m.votes / max) * H));
          const h2 = Math.round((m.contested / max) * H);
          const missed = m.votes > 0 && m.absent === m.votes;
          return (
            <Link
              key={m.meeting_id}
              href={`/meetings/${m.meeting_id}`}
              title={`${formatDate(m.date)}: ${m.votes} ${m.votes === 1 ? "vote" : "votes"}${m.no ? `, ${m.no} no` : ""}${missed ? ", absent" : ""}`}
              className="flex h-full min-w-0 flex-1 flex-col justify-end"
            >
              {m.no > 0 ? <span className="mb-[2px] block h-1 w-full rounded-[1px] bg-hound" /> : <span className="block h-1.5" />}
              {missed ? (
                <span className="block rounded-t border border-b-0 border-dashed border-muted-soft" style={{ height: h1 - 2 }} />
              ) : (
                <>
                  <span className={`block bg-teal opacity-30 ${h2 === 0 ? "rounded-t" : "rounded-t"}`} style={{ height: h1 - h2 }} />
                  <span className={`block bg-teal ${h1 - h2 === 0 ? "rounded-t" : ""}`} style={{ height: h2 }} />
                </>
              )}
            </Link>
          );
        })}
      </div>
      <div className="mt-1 flex gap-[2px]">
        {meetings.map((m, i) => (
          <span key={m.meeting_id} className={`min-w-0 flex-1 whitespace-nowrap text-[10px] leading-none text-muted-soft ${i === meetings.length - 1 ? "text-right" : ""}`}>
            {labelled.has(i) ? fmtShort(m.date) : ""}
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
        <Legend cls="bg-teal" label="contested" />
        <Legend cls="bg-teal" label="unanimous" faded />
        <Legend cls="bg-hound" label="voted no" />
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-[3px] border border-dashed border-muted-soft" />
          absent
        </span>
      </div>
    </div>
  );
}
