"use client";

import { useState } from "react";
import { formatDate, type Forum, type ForumAnswer } from "@/lib/api";

// One race's candidate forums, question by question: each candidate's own
// words from the video, in ballot order, with a link to the moment they said
// them. Verbatim transcript, never summarized; nothing is ranked or scored.

function mmss(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function Answer({ a }: { a: ForumAnswer }) {
  return (
    <div className="grid gap-x-5 gap-y-0.5 border-b border-hairline-soft py-2.5 last:border-0 sm:grid-cols-[200px_1fr]">
      <dt className="text-[13px] font-semibold text-body-strong">{a.candidate}</dt>
      <dd className="flex flex-col gap-2">
        {a.turns.map((t) => (
          <p key={t.start} className="max-w-[80ch] text-[14px] leading-relaxed text-body">
            <a
              href={t.link}
              target="_blank"
              rel="noopener noreferrer"
              className="mr-1.5 whitespace-nowrap text-[12px] font-semibold tabular-nums text-muted underline underline-offset-2 hover:text-ink"
            >
              ▶ {mmss(t.start)}
            </a>
            &ldquo;{t.text}&rdquo;
          </p>
        ))}
      </dd>
    </div>
  );
}

export default function ForumCompare({ forums }: { forums: Forum[] }) {
  const [active, setActive] = useState(0);
  if (forums.length === 0) return null;
  const f = forums[Math.min(active, forums.length - 1)];
  const missing = [...f.absent.map((a) => a.note), ...(f.silent.length ? [`Did not speak: ${f.silent.join(", ")}.`] : [])];

  return (
    <div>
      {forums.length > 1 && (
        <div role="tablist" aria-label="Forum" className="mb-3 flex flex-wrap gap-2">
          {forums.map((x, i) => (
            <button
              key={x.key}
              role="tab"
              type="button"
              aria-selected={i === active}
              onClick={() => setActive(i)}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] font-medium ${
                i === active ? "border-ink bg-ink text-canvas" : "border-hairline text-muted hover:text-ink"
              }`}
            >
              {x.title}
              <span className={i === active ? "text-canvas/70" : "text-muted-soft"}> · {formatDate(x.held_on)}</span>
            </button>
          ))}
        </div>
      )}

      <p className="mb-3 max-w-[80ch] text-[13px] leading-relaxed text-muted">
        {f.title}, {formatDate(f.held_on)}, hosted by {f.hosts} at {f.venue}.{" "}
        <a href={f.video} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-ink">
          Watch the video ↗
        </a>{" "}
        (posted by {f.posted_by}). {f.format} {f.note}
      </p>
      {missing.length > 0 && <p className="mb-3 text-[13px] text-body">{missing.join(" ")}</p>}

      <ol className="flex flex-col gap-2">
        {f.questions.map((q) => (
          <li key={q.id}>
            <details className="group rounded-lg border border-hairline px-4 py-2.5" open={f.questions.length === 1}>
              <summary className="cursor-pointer text-[15px] font-semibold leading-snug text-ink">
                {q.topic}
              </summary>
              {q.asked && (
                <p className="mt-2 max-w-[80ch] text-[13px] italic leading-relaxed text-muted">
                  <a href={q.link} target="_blank" rel="noopener noreferrer" className="mr-1.5 not-italic font-semibold tabular-nums underline underline-offset-2 hover:text-ink">
                    ▶ {mmss(q.start)}
                  </a>
                  Moderator: &ldquo;{q.asked}&rdquo;
                </p>
              )}
              <dl className="mt-1 flex flex-col">
                {q.answers.map((a) => (
                  <Answer key={a.candidate} a={a} />
                ))}
              </dl>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}
