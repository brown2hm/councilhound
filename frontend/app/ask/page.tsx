"use client";

import Image from "next/image";
import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import FollowTopic from "@/components/FollowTopic";
import Markdown from "@/components/Markdown";
import StatusBadge from "@/components/StatusBadge";
import { formatDate, type AskMember, type AskResponse, type AskStreamEvent, type Citation } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SUGGESTIONS = [
  "What has the council decided about affordable housing this year?",
  "What did the council decide about accessory dwelling units?",
  "What's happening with the Fairfax Circle Small Area Plan?",
];

function fmtTime(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** Turn [n] and [n, m] citation markers into links to the source rows.
 * Markers the record cited but did not return become plain, greyed text
 * (Markdown renders them as ordinary brackets). */
function linkifyCitations(answer: string, indexes: Set<number>, turn: number): string {
  return answer.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (marker, list: string) =>
    list
      .split(",")
      .map((n) => n.trim())
      .map((n) => (indexes.has(Number(n)) ? `[\\[${n}\\]](#source-${turn}-${n})` : `\\[${n}\\]`))
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

// what the link under each source opens, by kind of source
const LINK_LABEL: Record<string, string> = {
  transcript: "Watch this moment",
  agenda_item: "Open the meeting record",
  vote: "Open the roll call",
  timeline: "Open the meeting record",
  document: "Open the document",
  profile: "Full history",
  wiki: "Read the wiki page",
  project: "Official project page",
  impact: "Impact analysis",
  member: "Member record",
  comparison: "All members",
  commentary: "Topic history",
  term: "Official term schedule",
  roster: "Official roster",
  upcoming: "Open the agenda",
};

// sources that are records or summaries, not words someone said or wrote
const NOT_QUOTED = new Set(["member", "comparison", "term", "roster", "profile", "project", "impact", "vote", "timeline"]);

function SourceRow({ c, turn }: { c: Citation; turn: number }) {
  const where = [
    c.title || c.meeting_title,
    c.kind === "transcript" && c.start_seconds != null ? `at ${fmtTime(c.start_seconds)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const excerpt = c.excerpt.trim().replace(/[.,;]+$/, "");
  const label = LINK_LABEL[c.kind] ?? "Open the source";
  return (
    <li id={`source-${turn}-${c.index}`} className="grid scroll-mt-24 grid-cols-[26px_minmax(0,1fr)] gap-2 border-t border-hairline py-2.5 transition-colors duration-500 target:bg-callout">
      <span className="mt-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-md bg-card px-1.5 text-[11px] font-bold text-tint-ochre-text">
        {c.index}
      </span>
      <div className="min-w-0">
        <div className="text-[13px]">
          {c.date && <span className="font-semibold tabular-nums">{formatDate(c.date)} · </span>}
          <span className="text-muted">{where}</span>
        </div>
        <p className="mt-0.5 whitespace-pre-line text-[12px] leading-[1.45] text-muted">
          {NOT_QUOTED.has(c.kind) ? `${excerpt}…` : `“${excerpt}…”`}
        </p>
        {c.link &&
          (c.link.startsWith("/") ? (
            <Link href={c.link} className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
              {label}
            </Link>
          ) : (
            <a href={c.link} target="_blank" className="text-[12px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
              {label}
            </a>
          ))}
      </div>
    </li>
  );
}

/** "On the Nov 3, 2026 ballot" / "Appointed · term ends Dec 31, 2027". */
function seatLine(m: AskMember): string | null {
  const t = m.term;
  if (!t) return null;
  if (t.selection === "appointed") {
    return `Appointed${t.appointed_by ? ` by the ${t.appointed_by}` : ""}${t.term_ends ? ` · term ends ${formatDate(t.term_ends)}` : ""}`;
  }
  if (t.next_election) {
    const when = formatDate(t.next_election);
    if (t.on_ballot === true) return `On the ${when} ballot`;
    if (t.on_ballot === false) return `Not on the ${when} ballot`;
    return `Seat up ${when}`;
  }
  return t.term_ends ? `Term ends ${formatDate(t.term_ends)}` : null;
}

// how many earlier turns go with a follow-up (the API's cap)
const HISTORY_TURNS = 4;
// the API's per-answer cap on a history turn
const HISTORY_ANSWER_CHARS = 8000;

interface Turn {
  question: string;
  result: AskResponse;
}

/** One answer: the reasoning with its topic and member cards, and its
 * sources beside it. Each turn numbers its sources from 1, so anchors carry
 * the turn. */
function Answer({ result, turn }: { result: AskResponse; turn: number }) {
  const indexes = new Set(result.citations.map((c) => c.index));
  // dated sources in date order, then the undated records (rosters, member summaries)
  const sources = [...result.citations].sort(
    (a, b) => (a.date ? 0 : 1) - (b.date ? 0 : 1) || (a.date ?? "").localeCompare(b.date ?? "") || a.index - b.index,
  );
  const cited = Array.from(result.answer.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g), (m) => m[1]);
  const missing = new Set(cited.flatMap((list) => list.split(",").map((n: string) => Number(n.trim()))).filter((n) => !indexes.has(n))).size;
  const { lead, rest } = splitAnswer(result.answer);
  const topics = result.topics ?? [];
  const members = result.members ?? [];

  return (
    <div className="grid gap-x-14 gap-y-8 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div className="min-w-0">
        {lead && (
          <div className="mb-4 text-[26px] font-medium leading-[1.3] tracking-[-0.4px] text-ink [&_a]:no-underline [&_p]:mb-0">
            <Markdown>{linkifyCitations(lead, indexes, turn)}</Markdown>
          </div>
        )}
        <div className="text-[15px] leading-[1.6] text-body-strong [&_a]:rounded-md [&_a]:bg-card [&_a]:px-1.5 [&_a]:text-[11px] [&_a]:font-bold [&_a]:text-tint-ochre-text [&_a]:no-underline">
          <Markdown>{linkifyCitations(rest, indexes, turn)}</Markdown>
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

        {members.length > 0 && (
          <div className="mt-3 rounded-2xl bg-card px-[18px] py-3.5">
            <div className="text-[11px] font-semibold uppercase tracking-[1px] text-muted">
              About {members.length === 1 ? "this member" : "these members"}
            </div>
            <ul className="mt-1 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {members.map((m) => {
                const seat = seatLine(m);
                return (
                  <li key={m.slug} className="min-w-0">
                    <Link href={`/members/${m.slug}`} className="text-base font-semibold underline underline-offset-2 hover:text-ink">
                      {m.name}
                    </Link>
                    <span className="text-[13px] text-muted"> · {m.roles.join(", ")}</span>
                    {seat && <div className="text-[12px] text-body">{seat}</div>}
                  </li>
                );
              })}
            </ul>
            {members.some((m) => m.term) && (
              <div className="mt-1.5 text-[11px] text-muted">
                Term dates checked {formatDate(members.find((m) => m.term)!.term!.verified)} against official sources.
              </div>
            )}
          </div>
        )}
      </div>

      <aside className="min-w-0 lg:sticky lg:top-6 lg:self-start">
        <div className="mb-0.5 flex items-baseline justify-between gap-3">
          <h2 className="text-base font-semibold">Sources</h2>
          <span className="text-[12px] text-muted">{sources.length}, in date order</span>
        </div>
        <p className="mb-1 text-[12px] text-muted">
          Click a number in the answer to jump to it.
          {missing > 0 && ` ${missing} cited source${missing === 1 ? " was" : "s were"} not returned and stay unlinked.`}
        </p>
        <ul>
          {sources.map((c) => (
            <SourceRow key={c.index} c={c} turn={turn} />
          ))}
          {sources.length === 0 && <li className="border-t border-hairline py-3 text-sm text-muted">No sources were returned for this answer.</li>}
        </ul>
      </aside>
    </div>
  );
}

function AskInner() {
  const searchParams = useSearchParams();
  const [question, setQuestion] = useState(searchParams.get("q") ?? "");
  const [followUp, setFollowUp] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  // the question in flight, and whether it continues the conversation
  const [pending, setPending] = useState<{ question: string; followUp: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const autoSubmitted = useRef(false);
  const pendingRef = useRef<HTMLDivElement>(null);
  const loading = pending !== null;

  async function submit(q: string, asFollowUp = false) {
    if (!q.trim() || loading) return;
    const earlier = asFollowUp ? turns : [];
    setPending({ question: q, followUp: asFollowUp });
    setError(null);
    setSteps([]);
    if (!asFollowUp) setTurns([]);
    try {
      // newline-delimited JSON: a line per lookup the hound makes, then the answer
      const resp = await fetch(`${API}/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          history: earlier.slice(-HISTORY_TURNS).map((t) => ({
            question: t.question,
            answer: t.result.answer.slice(0, HISTORY_ANSWER_CHARS),
          })),
        }),
      });
      if (!resp.ok || !resp.body) {
        let detail = "";
        try {
          detail = (await resp.json()).detail ?? "";
        } catch {}
        throw new Error(detail || `The hound hit a snag (error ${resp.status}). Try again in a minute.`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffered = "";
      let answer: AskResponse | null = null;
      const handle = (line: string) => {
        if (!line.trim()) return;
        const event = JSON.parse(line) as AskStreamEvent;
        if (event.type === "step") setSteps((s) => (s.includes(event.label) ? s : [...s, event.label]));
        else if (event.type === "error") throw new Error(event.message);
        else answer = event;
      };
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        const lines = buffered.split("\n");
        buffered = lines.pop() ?? "";
        lines.forEach(handle);
      }
      handle(buffered);
      if (!answer) throw new Error("The answer was cut off. Try again in a minute.");
      const result: AskResponse = answer;
      setTurns([...earlier, { question: q, result }]);
      if (asFollowUp) setFollowUp("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setPending(null);
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

  // bring a follow-up's progress into view as it starts
  useEffect(() => {
    if (pending?.followUp) pendingRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [pending]);

  // one live region for both states so a screen reader is told the answer
  // is being fetched, and told when it fails
  const status = (
    <div role="status" aria-live="polite" ref={pendingRef} className="mt-4 scroll-mb-24">
      {loading && (
        <div className="text-sm text-muted">
          <div className="flex items-center gap-2.5">
            <Image src="/brand/hound.png" alt="" width={32} height={28} className="h-7 w-auto" />
            Sniffing through the record…
          </div>
          {steps.length > 0 && (
            <ol className="ml-[42px] mt-1.5 space-y-0.5 text-[13px]">
              {steps.map((s, i) => (
                <li key={s} className={i === steps.length - 1 ? "text-body" : "text-muted-soft"}>
                  {s}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
      {error && <p className="text-sm text-tint-coral-text">{error}</p>}
    </div>
  );
  const inThread = turns.length > 0 || pending?.followUp;

  const form = (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Image src="/brand/hound.png" alt="" width={34} height={30} className="h-[30px] w-auto" />
        <h1 className="text-lg font-semibold tracking-[-0.3px]">Ask the hound</h1>
        <span className="text-[13px] text-muted">Answers only from the public record, with sources you can check.</span>
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
          placeholder="What has the council decided about affordable housing this year?"
          aria-label="Your question"
          className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-soft"
        />
        <button
          disabled={loading}
          className="shrink-0 rounded-[9px] bg-ink px-[18px] py-2.5 text-sm font-semibold leading-none text-white hover:bg-ink-active disabled:opacity-60"
        >
          {loading && !pending?.followUp ? "Searching…" : inThread ? "Start over" : "Ask"}
        </button>
      </form>
      {!inThread && status}
    </>
  );

  if (!inThread) {
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
      {turns.map((t, i) => (
        <section key={i} aria-label={`Answer to: ${t.question}`} className={i === 0 ? "mt-7" : "mt-10 border-t border-hairline pt-8"}>
          {i > 0 && (
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[1px] text-muted">
              Follow-up
              <p className="mt-1 text-lg font-semibold normal-case tracking-[-0.2px] text-ink">{t.question}</p>
            </div>
          )}
          <Answer result={t.result} turn={i} />
        </section>
      ))}

      <div className="mt-10 max-w-[760px] border-t border-hairline pt-6">
        {pending?.followUp ? (
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[1px] text-muted">
            Follow-up
            <p className="mt-1 text-lg font-semibold normal-case tracking-[-0.2px] text-ink">{pending.question}</p>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(followUp, true);
            }}
            className="flex items-center gap-2 rounded-[14px] border border-hairline bg-white p-1.5 pl-4 focus-within:border-ink"
          >
            <input
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              placeholder="Ask a follow-up — “How did each member vote?”"
              aria-label="Your follow-up question"
              className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-soft"
            />
            <button
              disabled={loading || followUp.trim().length < 3}
              className="shrink-0 rounded-[9px] bg-ink px-[18px] py-2.5 text-sm font-semibold leading-none text-white hover:bg-ink-active disabled:opacity-60"
            >
              Follow up
            </button>
          </form>
        )}
        {status}
        <p className="mt-6 text-[12px] text-muted">
          Summaries are machine-generated from the meeting record. Check the source before relying on a detail.
          {turns.length > HISTORY_TURNS && ` Follow-ups draw on the last ${HISTORY_TURNS} answers.`}
        </p>
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
