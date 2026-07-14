import type { DiscussionPoint } from "@/lib/api";

/** Compact bar-per-meeting trend of named discussion time (see
 * hot_topics.py for what counts). Bars link to the meeting page. */
export default function DiscussionSparkline({ points }: { points: DiscussionPoint[] }) {
  const shown = points.filter((p) => p.seconds > 0);
  if (shown.length < 2) return null;
  const max = Math.max(...shown.map((p) => p.seconds));
  const fmt = (iso: string) =>
    new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return (
    <section className="mb-8">
      <h2 className="mb-1 text-lg font-semibold">Discussion time</h2>
      <p className="mb-3 text-[13px] text-muted-soft">
        Minutes of named discussion per transcribed meeting.
      </p>
      <div className="flex h-[72px] items-end gap-1.5">
        {shown.map((p) => (
          <a
            key={p.meeting_id}
            href={`/meetings/${p.meeting_id}`}
            title={`${Math.round(p.seconds / 60)} min · ${p.title} · ${fmt(p.date)}`}
            className="group flex h-full w-7 flex-col justify-end"
          >
            <div
              className={`w-full rounded-t ${p.body === "planning_commission" ? "bg-ochre" : "bg-teal"} opacity-80 group-hover:opacity-100`}
              style={{ height: `${Math.max(6, (p.seconds / max) * 100)}%` }}
            />
            <div className="mt-1 truncate text-center text-[10px] leading-tight text-muted-soft">
              {new Date(p.date + "T00:00:00").toLocaleDateString("en-US", { month: "short" })}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
