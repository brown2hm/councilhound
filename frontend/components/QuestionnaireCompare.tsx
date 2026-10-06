"use client";

import { useState } from "react";
import { formatDate, type Questionnaire } from "@/lib/api";

// One race's questionnaires, question by question: every respondent's answer
// to the same question together, in ballot order. Readers can narrow to the
// candidates they are weighing; nothing is ranked or scored.

function responded(q: Questionnaire) {
  return q.responses.filter((r) => r.responded);
}

export default function QuestionnaireCompare({ questionnaires }: { questionnaires: Questionnaire[] }) {
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  if (questionnaires.length === 0) return null;
  const q = questionnaires[Math.min(active, questionnaires.length - 1)];
  const answered = responded(q);
  const silent = q.responses.filter((r) => !r.responded);
  const shown = picked.size ? answered.filter((r) => picked.has(r.candidate)) : answered;

  const toggle = (name: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <div>
      {questionnaires.length > 1 && (
        <div role="tablist" aria-label="Questionnaire" className="mb-3 flex flex-wrap gap-2">
          {questionnaires.map((x, i) => (
            <button
              key={x.key}
              role="tab"
              type="button"
              aria-selected={i === active}
              onClick={() => {
                setActive(i);
                setPicked(new Set());
              }}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] font-medium ${
                i === active ? "border-ink bg-ink text-canvas" : "border-hairline text-muted hover:text-ink"
              }`}
            >
              {x.publisher}
              <span className={i === active ? "text-canvas/70" : "text-muted-soft"}>
                {" "}
                · {responded(x).length} of {x.responses.length} answered
              </span>
            </button>
          ))}
        </div>
      )}

      <p className="mb-3 max-w-[80ch] text-[13px] leading-relaxed text-muted">
        {q.title}. Each answer is a short paraphrase of what the candidate wrote; follow &ldquo;full answer&rdquo; for their own
        words. Answers read {formatDate(q.checked)}.{q.note ? ` ${q.note}` : ""}
      </p>

      {silent.length > 0 && (
        <p className="mb-3 text-[13px] text-body">
          <span className="font-semibold">No answers found from:</span> {silent.map((r) => r.candidate).join(", ")}.
        </p>
      )}

      {answered.length > 1 && (
        <fieldset className="mb-5">
          <legend className="mb-1.5 text-[11px] font-semibold uppercase tracking-[1px] text-muted">
            Compare {picked.size ? `${picked.size} selected` : "everyone who answered"}
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {answered.map((r) => {
              const on = picked.has(r.candidate);
              return (
                <button
                  key={r.candidate}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(r.candidate)}
                  className={`rounded-full border px-3 py-1 text-[12px] ${
                    on ? "border-teal bg-tint-mint text-tint-mint-text" : "border-hairline text-body hover:border-muted"
                  }`}
                >
                  {r.candidate}
                </button>
              );
            })}
            {picked.size > 0 && (
              <button type="button" onClick={() => setPicked(new Set())} className="px-2 text-[12px] text-muted underline">
                Show all
              </button>
            )}
          </div>
        </fieldset>
      )}

      {answered.length === 0 ? (
        <p className="text-sm text-muted">No candidate in this race has answered yet.</p>
      ) : (
        <ol className="flex flex-col gap-6">
          {q.questions.map((question, i) => (
            <li key={question.key}>
              <h4 className="mb-2 border-b border-hairline pb-1.5 text-[15px] font-semibold leading-snug text-ink">
                <span className="mr-1.5 tabular-nums text-muted-soft">{i + 1}.</span>
                {question.asked}
              </h4>
              <dl className="flex flex-col">
                {shown.map((r) => {
                  const a = r.answers[question.key];
                  return (
                    <div
                      key={r.candidate}
                      className="grid gap-x-5 gap-y-0.5 border-b border-hairline-soft py-2 last:border-0 sm:grid-cols-[200px_1fr]"
                    >
                      <dt className="text-[13px] font-semibold text-body-strong">{r.candidate}</dt>
                      <dd className="text-[14px] leading-relaxed text-body">
                        {a ? a : <span className="italic text-muted">Left this question blank.</span>}{" "}
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="whitespace-nowrap text-[12px] text-muted underline underline-offset-2 hover:text-ink"
                        >
                          full answer ↗
                        </a>
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
