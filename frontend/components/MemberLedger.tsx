"use client";

import Link from "next/link";
import { useState } from "react";
import BodyTag from "@/components/BodyTag";
import { formatDate, type MemberVote } from "@/lib/api";
import { resultLine } from "@/lib/subject";

// Glyph + tint per vote, as VotePills on the meeting page.
const PILL: Record<string, { cls: string; glyph: string }> = {
  yes: { cls: "bg-tint-mint text-tint-mint-text", glyph: "✓" },
  no: { cls: "bg-tint-coral text-tint-coral-text", glyph: "✕" },
  abstain: { cls: "bg-tint-ochre text-tint-ochre-text", glyph: "–" },
  absent: { cls: "bg-card text-muted-soft", glyph: "·" },
};

export function VotePill({ vote }: { vote: string }) {
  const p = PILL[vote] ?? { cls: "bg-card text-body", glyph: "" };
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold leading-none ${p.cls}`}>
      {p.glyph} {vote}
    </span>
  );
}

type FilterKey = "all" | "contested" | "no" | "hearing" | "consent";

const FILTERS: { key: FilterKey; label: (first: string) => string; test: (v: MemberVote) => boolean }[] = [
  { key: "all", label: () => "All", test: () => true },
  { key: "contested", label: () => "Contested", test: (v) => v.contested },
  { key: "no", label: (first) => `${first} no votes`, test: (v) => v.vote === "no" },
  { key: "hearing", label: () => "Public hearings", test: (v) => v.category === "hearing" },
  { key: "consent", label: () => "Consent agenda", test: (v) => v.category === "consent" },
];

/** Every vote, grouped by meeting, newest first, with filters. */
export default function MemberLedger({ votes, possessive }: { votes: MemberVote[]; possessive: string }) {
  const [filter, setFilter] = useState<FilterKey>("all");
  const counts = Object.fromEntries(FILTERS.map((f) => [f.key, votes.filter(f.test).length])) as Record<FilterKey, number>;
  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];
  const shown = votes.filter(active.test);

  const meetings: { key: number; date: string; title: string; body: string; rows: MemberVote[] }[] = [];
  for (const v of shown) {
    const last = meetings[meetings.length - 1];
    if (last && last.key === v.meeting_id) last.rows.push(v);
    else meetings.push({ key: v.meeting_id, date: v.date, title: v.meeting_title, body: v.body, rows: [v] });
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Filter the voting record">
        {FILTERS.filter((f) => f.key === "all" || counts[f.key] > 0).map((f) => {
          const on = f.key === filter;
          return (
            <button
              key={f.key}
              type="button"
              aria-pressed={on}
              onClick={() => setFilter(f.key)}
              className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${on ? "bg-ink text-canvas" : "border border-hairline text-muted hover:border-ink hover:text-ink"}`}
            >
              {f.label(possessive)} <span className={`ml-1 tabular-nums ${on ? "opacity-70" : "text-muted-soft"}`}>{counts[f.key]}</span>
            </button>
          );
        })}
      </div>
      {meetings.length === 0 && <p className="text-sm text-muted">No recorded votes yet.</p>}
      {meetings.map((m) => {
        const missed = m.rows.every((v) => v.vote === "absent");
        return (
          <section key={m.key} className="mt-2">
            <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 border-t-2 border-ink pb-1.5 pt-3">
              <span className="text-[15px] font-semibold tabular-nums">{formatDate(m.date)}</span>
              <Link href={`/meetings/${m.key}`} className="inline-flex items-center gap-1.5 text-[13px] text-muted underline-offset-2 hover:underline">
                <BodyTag body={m.body} />
                {m.title}
              </Link>
              {missed && (
                <span className="text-[13px] text-muted-soft">· recorded absent for {m.rows.length === 1 ? "the one vote" : `all ${m.rows.length} votes`}</span>
              )}
            </div>
            <ul>
              {m.rows.map((v, i) => (
                <li
                  key={i}
                  className="grid grid-cols-[76px_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 border-t border-hairline py-2.5 text-sm sm:grid-cols-[76px_36px_minmax(0,1fr)_128px_48px]"
                >
                  <span>
                    <VotePill vote={v.vote} />
                  </span>
                  <span className="hidden text-[12px] font-semibold tabular-nums text-muted sm:block">{v.item_label}</span>
                  <span className="leading-[1.5] text-body">{v.item_title ?? v.description}</span>
                  <span className="col-start-2 text-[13px] tabular-nums sm:col-start-4">
                    <span className={`font-semibold ${v.motion_result === "failed" ? "text-tint-coral-text" : v.motion_result === "passed" ? "text-tint-mint-text" : "text-tint-ochre-text"}`}>
                      {resultLine(v.tally, v.motion_result)}
                    </span>
                    {v.in_minority && <span className="block text-[11px] font-semibold text-hound">in the minority</span>}
                  </span>
                  <span className="col-start-2 text-[12px] font-semibold sm:col-start-5 sm:text-right">
                    {v.watch_url && (
                      <a href={v.watch_url} target="_blank" className="text-muted underline underline-offset-2 hover:text-ink">
                        Watch
                      </a>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
