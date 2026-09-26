"use client";

import { useMemo, useState } from "react";
import type { MeetingTranscript, TranscriptSegment } from "@/lib/api";

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

/** Case-insensitive highlight. Split rather than innerHTML so transcript
 * text is never interpreted as markup. */
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  const low = text.toLowerCase();
  const q = query.toLowerCase();
  let i = 0;
  let n = 0;
  while (true) {
    const hit = low.indexOf(q, i);
    if (hit < 0) break;
    if (hit > i) parts.push(text.slice(i, hit));
    parts.push(
      <mark key={n++} className="rounded bg-tint-ochre px-0.5 text-tint-ochre-text">
        {text.slice(hit, hit + q.length)}
      </mark>,
    );
    i = hit + q.length;
  }
  parts.push(text.slice(i));
  return <>{parts}</>;
}

type Section = {
  key: string;
  heading: string | null;
  label: string | null;
  startSeconds: number | null;
  segments: TranscriptSegment[];
};

/** Slice the segment stream at each agenda item's official index point, so
 * the transcript reads as a table of contents rather than one long wall. */
function buildSections(
  segments: TranscriptSegment[],
  items: MeetingTranscript["agenda_items"],
): Section[] {
  if (items.length === 0) {
    return [{ key: "all", heading: null, label: null, startSeconds: null, segments }];
  }
  const sections: Section[] = [];
  const before = segments.filter(
    (s) => s.start_seconds !== null && s.start_seconds < items[0].start_seconds,
  );
  if (before.length > 0) {
    sections.push({
      key: "opening",
      heading: "Before the first agenda item",
      label: null,
      startSeconds: null,
      segments: before,
    });
  }
  items.forEach((item, idx) => {
    const next = items[idx + 1];
    sections.push({
      key: `item-${item.id}`,
      heading: item.title ?? `Item ${item.label}`,
      label: item.label,
      startSeconds: item.start_seconds,
      segments: segments.filter(
        (s) =>
          s.start_seconds !== null &&
          s.start_seconds >= item.start_seconds &&
          (!next || s.start_seconds < next.start_seconds),
      ),
    });
  });
  // segments with no timestamp can't be placed; keep them rather than drop them
  const untimed = segments.filter((s) => s.start_seconds === null);
  if (untimed.length > 0) {
    sections.push({
      key: "untimed",
      heading: "Unplaced segments",
      label: null,
      startSeconds: null,
      segments: untimed,
    });
  }
  return sections;
}

export default function TranscriptReader({
  transcript,
  initialQuery = "",
}: {
  transcript: MeetingTranscript;
  initialQuery?: string;
}) {
  const [query, setQuery] = useState(initialQuery);
  const q = query.trim();

  const sections = useMemo(
    () => buildSections(transcript.segments, transcript.agenda_items),
    [transcript],
  );

  const filtered = useMemo(() => {
    if (!q) return sections;
    const low = q.toLowerCase();
    return sections
      .map((s) => ({ ...s, segments: s.segments.filter((seg) => seg.text.toLowerCase().includes(low)) }))
      .filter((s) => s.segments.length > 0);
  }, [sections, q]);

  const matchCount = filtered.reduce((n, s) => n + s.segments.length, 0);

  return (
    <div>
      <div className="sticky top-16 z-[5] -mx-4 mb-6 border-b border-hairline-soft bg-canvas px-4 py-3 sm:-mx-8 sm:px-8">
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find in this transcript…"
            aria-label="Find in this transcript"
            className="w-full rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-sm outline-none placeholder:text-muted-soft focus:border-ink sm:w-[320px]"
          />
          <p className="text-[13px] text-muted" role="status" aria-live="polite">
            {q
              ? `${matchCount} matching segment${matchCount === 1 ? "" : "s"}`
              : `${transcript.segments.length} segments`}
          </p>
          {q && (
            <button
              onClick={() => setQuery("")}
              className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
            >
              clear
            </button>
          )}
        </div>
      </div>

      {transcript.agenda_items.length > 0 && !q && (
        <nav aria-label="Jump to agenda item" className="mb-8">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
            Jump to
          </h2>
          <ul className="flex flex-wrap gap-2">
            {transcript.agenda_items.map((item) => (
              <li key={item.id}>
                <a
                  href={`#item-${item.id}`}
                  className="inline-block rounded-full border border-hairline px-3 py-1.5 text-[13px] font-medium text-muted hover:text-ink"
                >
                  {item.label}
                  <span className="ml-1.5 text-muted-soft">{fmtTime(item.start_seconds)}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {filtered.map((section) => (
        <section key={section.key} id={section.key} className="mb-9 scroll-mt-32">
          {section.heading && (
            <div className="mb-3 border-b border-hairline pb-2">
              <div className="flex flex-wrap items-baseline gap-2">
                {section.label && (
                  <span className="rounded-md bg-card px-2 py-0.5 font-mono text-xs font-semibold text-muted">
                    {section.label}
                  </span>
                )}
                <h2 className="text-[17px] font-semibold leading-snug">{section.heading}</h2>
                {section.startSeconds !== null && (
                  <span className="text-[13px] text-muted-soft">
                    {fmtTime(section.startSeconds)}
                  </span>
                )}
              </div>
            </div>
          )}
          <div className="space-y-3">
            {section.segments.map((seg) => (
              <div key={seg.id} className="flex gap-3 sm:gap-4">
                <div className="w-[52px] shrink-0 pt-0.5 text-right sm:w-[64px]">
                  {seg.watch_url && seg.start_seconds !== null ? (
                    <a
                      href={seg.watch_url}
                      target="_blank"
                      title="Watch this moment on the official player"
                      className="font-mono text-[12px] text-muted underline-offset-2 hover:text-ink hover:underline"
                    >
                      {fmtTime(seg.start_seconds)}
                    </a>
                  ) : (
                    <span className="font-mono text-[12px] text-muted-soft">
                      {seg.start_seconds !== null ? fmtTime(seg.start_seconds) : "—"}
                    </span>
                  )}
                </div>
                <p className="min-w-0 flex-1 text-[15px] leading-[1.65] text-body">
                  {seg.speaker_label && (
                    <span className="mr-2 font-semibold text-ink">{seg.speaker_label}</span>
                  )}
                  <Highlight text={seg.text} query={q} />
                </p>
              </div>
            ))}
          </div>
        </section>
      ))}

      {filtered.length === 0 && (
        <p className="rounded-2xl border border-dashed border-hairline p-6 text-sm text-muted">
          {q ? (
            <>
              Nothing in this meeting matches “{q}”. Try{" "}
              <a href={`/search?q=${encodeURIComponent(q)}`} className="font-semibold underline underline-offset-2 hover:text-ink">
                searching every meeting
              </a>
              .
            </>
          ) : (
            <>This meeting hasn&apos;t been transcribed yet.</>
          )}
        </p>
      )}
    </div>
  );
}
