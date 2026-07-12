"use client";

import { useState } from "react";
import type { AskResponse } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SUGGESTIONS = [
  "What's the status of the George Snyder Trail project?",
  "What did the council decide about urban agriculture zoning?",
  "What's happening with the Fairfax Circle Small Area Plan?",
];

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

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
      if (!resp.ok) throw new Error(`API error ${resp.status}`);
      setResult(await resp.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold">Ask the hound</h1>
      <p className="mb-5 text-sm text-slate-500">
        It fetches answers only from the meeting record, with citations you can verify.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="mb-4 flex gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What's the status of the George Snyder Trail?"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          disabled={loading}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Searching…" : "Ask"}
        </button>
      </form>

      {!result && !loading && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQuestion(s);
                submit(s);
              }}
              className="rounded-full bg-white px-3 py-1.5 text-sm text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {result && (
        <div>
          <div className="mb-6 whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-5 text-sm leading-relaxed">
            {result.answer}
          </div>
          {result.citations.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-semibold text-slate-500">Sources</h2>
              <ul className="space-y-2">
                {result.citations.map((c) => (
                  <li key={c.index} className="rounded-md border border-slate-200 bg-white p-3 text-sm">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="rounded bg-slate-100 px-1.5 font-mono text-xs">[{c.index}]</span>
                      <span className="font-medium">{c.meeting_title}</span>
                      <span className="text-xs text-slate-500">{c.date}</span>
                      {c.kind === "transcript" && c.start_seconds != null && (
                        <span className="text-xs text-slate-400">
                          @ {Math.floor(c.start_seconds / 60)}:{String(Math.floor(c.start_seconds % 60)).padStart(2, "0")}
                        </span>
                      )}
                    </div>
                    <p className="mb-1 text-xs text-slate-500">“{c.excerpt}…”</p>
                    {c.link && (
                      <a href={c.link} target="_blank" className="text-xs text-sky-600 hover:underline">
                        {c.kind === "transcript" ? "▶ watch this moment" : "open document"} ↗
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
