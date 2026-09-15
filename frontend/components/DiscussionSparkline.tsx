import { bodyDot } from "@/components/BodyTag";
import type { DiscussionPoint } from "@/lib/api";

/** Compact bar-per-meeting trend of named discussion time (see
 * hot_topics.py for what counts). Bars link to the meeting page. */
export default function DiscussionSparkline({ points, compact = false }: { points: DiscussionPoint[]; compact?: boolean }) {
  const shown = points.filter((p) => p.seconds > 0);
  if (shown.length < 2) return null;
  const max = Math.max(...shown.map((p) => p.seconds));
  // label a bar when the year changes or three months have passed, plus the ends
  const labelled = new Set<number>();
  let last: Date | null = null;
  shown.forEach((p, i) => {
    const d = new Date(p.date + "T00:00:00");
    if (!last || d.getFullYear() !== last.getFullYear() || (d.getMonth() - last.getMonth() + 12) % 12 >= 3 || i === shown.length - 1) {
      labelled.add(i);
      last = d;
    }
  });
  const fmt = (iso: string) =>
    new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const first = shown[0].date;
  return (
    <section className={compact ? "" : "mb-8"}>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        {compact ? (
          <span className="text-xs font-semibold uppercase tracking-[1.5px] text-muted">Discussion time</span>
        ) : (
          <h2 className="text-lg font-semibold">Discussion time</h2>
        )}
        <span className="text-[11px] text-muted">
          <span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full bg-teal" />council
          <span aria-hidden className="ml-2 mr-1 inline-block h-2 w-2 rounded-full bg-ochre" />commission
        </span>
      </div>
      {!compact && (
        <p className="mb-3 text-[13px] text-muted-soft">
          Minutes of named discussion per transcribed meeting, {fmt(first)} onward.
        </p>
      )}
      <div className={`flex ${compact ? "h-[64px]" : "h-[84px]"} items-end gap-1`}>
        {shown.map((p, i) => (
          <a
            key={p.meeting_id}
            href={`/meetings/${p.meeting_id}`}
            title={`${Math.round(p.seconds / 60)} min · ${p.title} · ${fmt(p.date)}`}
            className="group flex h-full min-w-0 flex-1 flex-col justify-end"
          >
            <div
              className={`w-full rounded-t ${bodyDot(p.body)} opacity-80 group-hover:opacity-100`}
              style={{ height: `${Math.max(6, (p.seconds / max) * 100)}%` }}
            />
            <div className={`mt-1 h-3 whitespace-nowrap text-[10px] leading-tight text-muted-soft ${i === shown.length - 1 ? "text-right" : ""}`}>
              {labelled.has(i)
                ? new Date(p.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "2-digit" }).replace(" ", " ’")
                : ""}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
