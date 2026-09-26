"use client";

import Image from "next/image";
import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import FollowTopic from "@/components/FollowTopic";
import Markdown from "@/components/Markdown";
import StatusBadge from "@/components/StatusBadge";
import { useJurisdiction } from "@/components/JurisdictionProvider";
import { formatDate, type AskResponse, type Citation } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FALLBACK_SUGGESTIONS = [
  "What has the council decided about affordable housing this year?",
  "What did the council decide about accessory dwelling units?",
];

function fmtTime(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** Turn [n] and [n, m] citation markers into links to the source rows.
 * Markers the record cited but did not return become plain, greyed text
 * (Markdown renders them as ordinary brackets). */
function linkifyCitations(answer: string, indexes: Set<number>): string {
  return answer.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (marker, list: string) =>
    list
      .split(",")
      .map((n) => n.trim())
      .map((n) => (indexes.has(Number(n)) ? `[\\[${n}\\]](#source-${n})` : `\\[${n}\\]`))
      .join(" "),
  );
}

/** The answer's first line is its statement; the rest is the reasoning. */
function splitAnswer(answer: string): { lead: string; rest: string } {
  const lines = answer.trim().split("\n");
  const first = lines[0] ?? "";
  // only promote a short prose line, not a heading or a bullet
  if (first.length > 220 || /^[-*#]/.test(first)) return { lead: "", rest: answer };
  return { lead: first, rest: lines.slice(1).join("\n").trim() };
}

function SourceRow({ c }: { c: Citation }) {
  const where = [
    c.meeting_title,
    c.agenda_item_label ? `item ${c.agenda_item_label}` : null,
    c.kind === "transcript" && c.start_seconds != null ? `at ${fmtTime(c.start_seconds)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li id={`source-${c.index}`} className="grid scroll-mt-24 grid-cols-[26px_minmax(0,1fr)] gap-2 border-t border-hairline py-2.5 transition-colors duration-500 target:bg-callout">
      <span className="mt-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-md bg-card px-1.5 text-[11px] font-bold text-tint-ochre-text">
        {c.index}
      </span>
      <div className="min-w-0">
        <div className="text-[13px]">
          <span className="font-semibold tabular-nums">{formatDate(c.date)}</span>
          <span className="text-muted"> · {where}</span>
        </div>
        <p className="mt-0.5 text-[12px] leading-[1.45] text-muted">“{c.excerpt.trim().replace(/[.,;]+$/, "")}…”</p>
        {c.link && (
          <a href={c.link} target="_blank" className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
            {c.kind === "transcript" ? "Watch this moment" : "Open the document"}
          </a>
        )}
      </div>
    </li>
  );
}

function AskInner() {
  const { display } = useJurisdiction();
  const SUGGESTIONS = display.ask_suggestions.length ? display.ask_suggestions : FALLBACK_SUGGESTIONS;
  const searchParams = useSearchParams();
  const [question, setQuestion] = useState(searchParams.get("q") ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const autoSubmitted = useRef(false);

  async function submit(q: string) {
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch(`${API}/ask/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!resp.ok) throw new Error(`The hound hit a snag (error ${resp.status}). Try again in a minute.`);
      setResult(await resp.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && !autoSubmitted.current) {
      autoSubmitted.current = true;
      submit(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const indexes = new Set(result?.citations.map((c) => c.index) ?? []);
  const sources = [...(result?.citations ?? [])].sort((a, b) => a.date.localeCompare(b.date) || a.index - b.index);
  const cited = result ? Array.from(result.answer.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g), (m) => m[1]) : [];
  const missing = new Set(cited.flatMap((list) => list.split(",").map((n: string) => Number(n.trim()))).filter((n) => !indexes.has(n))).size;
  const { lead, rest } = result ? splitAnswer(result.answer) : { lead: "", rest: "" };
  const topics = result?.topics ?? [];

  const form = (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Image src="/brand/hound.png" alt="" width={34} height={30} className="h-[30px] w-auto" />
        <h1 className="text-lg font-semibold tracking-[-0.3px]">Ask the hound</h1>
        <span className="text-[13px] text-muted">Answers only from the meeting record, with sources you can check.</span>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="flex items-center gap-2 rounded-[14px] border border-ink bg-white p-1.5 pl-4"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={display.ask_placeholder || "What has the council decided about affordable housing this year?"}
          aria-label="Your question"
          className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-soft"
        />
        <button
          disabled={loading}
          className="shrink-0 rounded-[9px] bg-ink px-[18px] py-2.5 text-sm font-semibold leading-none text-white hover:bg-ink-active disabled:opacity-60"
        >
          {loading ? "Searching…" : "Ask"}
        </button>
      </form>
      {/* one live region for both states so a screen reader is told the
          answer is being fetched, and told when it fails */}
      <div role="status" aria-live="polite" className="mt-4">
        {loading && (
          <div className="flex items-center gap-2.5 text-sm text-muted">
            <Image src="/brand/hound.png" alt="" width={32} height={28} className="h-7 w-auto" />
            Sniffing through the record…
          </div>
        )}
        {error && <p className="text-sm text-tint-coral-text">{error}</p>}
      </div>
    </>
  );

  if (!result) {
    return (
      <div className="mx-auto max-w-[760px] px-4 pb-16 pt-12 sm:px-8">
        {form}
        {!loading && !error && (
          <div className="mt-5 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setQuestion(s);
                  submit(s);
                }}
                className="rounded-full bg-card px-4 py-2 text-sm font-medium text-body hover:bg-strong"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-10 sm:px-8">
      {form}
      <div className="mt-7 grid gap-x-14 gap-y-8 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0">
          {lead && (
            <div className="mb-4 text-[26px] font-medium leading-[1.3] tracking-[-0.4px] text-ink [&_a]:no-underline [&_p]:mb-0">
              <Markdown>{linkifyCitations(lead, indexes)}</Markdown>
            </div>
          )}
          <div className="text-[15px] leading-[1.6] text-body-strong [&_a]:rounded-md [&_a]:bg-card [&_a]:px-1.5 [&_a]:text-[11px] [&_a]:font-bold [&_a]:text-tint-ochre-text [&_a]:no-underline">
            <Markdown>{linkifyCitations(rest, indexes)}</Markdown>
          </div>

          {topics.length > 0 && (
            <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 rounded-2xl bg-card px-[18px] py-3.5">
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-[1px] text-muted">
                  About {topics.length === 1 ? "this topic" : "these topics"}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  {topics.map((t) => (
                    <span key={t.slug} className="inline-flex items-center gap-1.5 text-base font-semibold">
                      <Link
                        href={t.official_slug ? `/development/${t.official_slug}` : `/topics/${t.slug}`}
                        className="underline underline-offset-2 hover:text-ink"
                      >
                        {t.name}
                      </Link>
                      <StatusBadge status={t.current_status} />
                    </span>
                  ))}
                </div>
                {topics.length === 1 && (
                  <div className="text-[12px] text-muted">
                    {topics[0].update_count} update{topics[0].update_count === 1 ? "" : "s"} on the record
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <FollowTopic entitySlug={topics[0].slug} />
                <Link
                  href={`/topics/${topics[0].slug}`}
                  className="rounded-xl border border-hairline bg-canvas px-4 py-2 text-sm font-semibold hover:border-ink"
                >
                  Full history
                </Link>
              </div>
            </div>
          )}

          <p className="mt-6 text-[12px] text-muted">
            Summaries are machine-generated from the meeting record. Check the source before relying on a detail.
          </p>
        </div>

        <aside className="min-w-0 lg:sticky lg:top-6 lg:self-start">
          <div className="mb-0.5 flex items-baseline justify-between gap-3">
            <h2 className="text-base font-semibold">Sources</h2>
            <span className="text-[12px] text-muted">
              {sources.length}, in date order
            </span>
          </div>
          <p className="mb-1 text-[12px] text-muted">
            Click a number in the answer to jump to it.
            {missing > 0 && ` ${missing} cited source${missing === 1 ? " was" : "s were"} not returned and stay unlinked.`}
          </p>
          <ul>
            {sources.map((c) => (
              <SourceRow key={c.index} c={c} />
            ))}
            {sources.length === 0 && <li className="border-t border-hairline py-3 text-sm text-muted">No sources were returned for this answer.</li>}
          </ul>
        </aside>
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense>
      <AskInner />
    </Suspense>
  );
}
