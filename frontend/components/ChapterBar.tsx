import type { AgendaItemInfo } from "@/lib/api";

/**
 * Visual table of contents for a meeting: one segment per agenda item with a
 * Granicus index-point timestamp, width proportional to how long the item
 * ran (until the next timestamp, or end of meeting). Segments deep-link to
 * the video moment. Needs the meeting duration and >= 2 timestamped items.
 */
const SEGMENT_TINTS = ["bg-teal", "bg-ochre", "bg-mint"];

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function ChapterBar({
  items,
  durationSeconds,
}: {
  items: AgendaItemInfo[];
  durationSeconds: number | null;
}) {
  if (!durationSeconds) return null;
  const timed = items
    .filter((it) => it.start_seconds !== null && it.start_seconds < durationSeconds)
    .sort((a, b) => (a.start_seconds ?? 0) - (b.start_seconds ?? 0));
  if (timed.length < 2) return null;

  const segments = timed.map((it, i) => {
    const start = it.start_seconds ?? 0;
    const end = i + 1 < timed.length ? (timed[i + 1].start_seconds ?? start) : durationSeconds;
    return { item: it, start, seconds: Math.max(0, end - start) };
  });
  const lead = segments[0].start; // call-to-order etc. before the first marker

  return (
    <div className="mb-9">
      <div className="mb-1.5 flex h-4 w-full gap-px overflow-hidden rounded-full">
        {lead > 0 && <div className="h-4 bg-strong" style={{ flexGrow: lead }} />}
        {segments.map(({ item, start, seconds }, i) =>
          item.watch_url ? (
            <a
              key={item.id}
              href={item.watch_url}
              target="_blank"
              title={`${item.label} · ${item.title ?? ""} · ${fmtTime(seconds)} — watch from ${fmtTime(start)}`}
              className={`h-4 ${SEGMENT_TINTS[i % SEGMENT_TINTS.length]} opacity-70 transition-opacity hover:opacity-100`}
              style={{ flexGrow: Math.max(seconds, durationSeconds / 100) }}
            />
          ) : (
            <div
              key={item.id}
              title={`${item.label} · ${item.title ?? ""} · ${fmtTime(seconds)}`}
              className={`h-4 ${SEGMENT_TINTS[i % SEGMENT_TINTS.length]} opacity-70`}
              style={{ flexGrow: Math.max(seconds, durationSeconds / 100) }}
            />
          ),
        )}
      </div>
      <p className="text-[13px] text-muted-soft">
        {fmtTime(durationSeconds)} total — hover for items, click a segment to watch that part.
      </p>
    </div>
  );
}
