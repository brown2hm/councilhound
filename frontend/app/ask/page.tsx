"use client";

import Image from "next/image";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { AskResponse } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SUGGESTIONS = [
  "What's the status of the George Snyder Trail project?",
  "What did the council decide about accessory dwelling units?",
  "What's happening with the Fairfax Circle Small Area Plan?",
];

function fmtTime(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function AskInner() {
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

  return (
    <div className="mx-auto max-w-[760px] px-8 pb-16 pt-12">
      <div className="mb-1 flex items-center gap-3">
        <Image src="/brand/hound.png" alt="" width={50} height={44} className="h-11 w-auto" />
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">Ask the hound</h1>
      </div>
      <p className="mb-6 text-sm text-muted">
        It fetches answers only from the meeting record, with citations you can verify.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="mb-5 flex items-center gap-2 rounded-2xl border border-hairline bg-canvas p-2 pl-5"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What's the status of the George Snyder Trail?"
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-soft"
        />
        <button
          disabled={loading}
          className="shrink-0 rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active disabled:opacity-60"
        >
          {loading ? "Searching…" : "Ask"}
        </button>
      </form>

      {!result && !loading && !error && (
        <div className="flex flex-wrap gap-2">
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

      {loading && (
        <div className="flex items-center gap-2.5 text-sm text-muted">
          <Image src="/brand/hound.png" alt="" width={32} height={28} className="h-7 w-auto" />
          Sniffing through the record…
        </div>
      )}

      {error && <p className="text-sm text-tint-coral-text">{error}</p>}

      {result && (
        <div>
          <div className="mb-6 whitespace-pre-wrap rounded-2xl border border-hairline bg-canvas p-[22px] px-6 text-[15px] leading-[1.6] text-body-strong">
            {result.answer}
          </div>
          {result.citations.length > 0 && (
            <div>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
                Sources
              </h2>
              <ul className="space-y-2">
                {result.citations.map((c) => (
                  <li key={c.index} className="rounded-2xl border border-hairline bg-canvas p-3.5 text-sm">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-card px-1.5 font-mono text-xs">[{c.index}]</span>
                      <span className="font-semibold">{c.meeting_title}</span>
                      <span className="text-[13px] text-muted">{c.date}</span>
                      {c.kind === "transcript" && c.start_seconds != null && (
                        <span className="text-[13px] text-muted-soft">@ {fmtTime(c.start_seconds)}</span>
                      )}
                    </div>
                    <p className="mb-1 text-[13px] text-muted">“{c.excerpt}…”</p>
                    {c.link && (
                      <a
                        href={c.link}
                        target="_blank"
                        className="text-[13px] font-semibold text-ink underline underline-offset-2"
                      >
                        {c.kind === "transcript" ? "▶ Watch this moment" : "Open document"}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
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
