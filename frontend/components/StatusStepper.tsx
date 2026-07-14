import type { TimelineEntry } from "@/lib/api";

/**
 * Lifecycle bar: Proposed → Under review → Decided. Stages derive from the
 * status vocabulary the extraction pass emits (proposed, in_progress,
 * deferred, approved, denied, withdrawn, completed); dates are the first
 * timeline entry that reached each stage.
 */
const STAGE_OF: Record<string, number> = {
  proposed: 0,
  in_progress: 1,
  deferred: 1,
  approved: 2,
  denied: 2,
  withdrawn: 2,
  completed: 2,
};

const DECIDED_TINT: Record<string, string> = {
  approved: "bg-tint-mint text-tint-mint-text",
  completed: "bg-tint-mint text-tint-mint-text",
  denied: "bg-tint-coral text-tint-coral-text",
  withdrawn: "bg-strong text-body",
};

function fmtShort(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function StatusStepper({
  timeline,
  currentStatus,
}: {
  timeline: TimelineEntry[];
  currentStatus: string | null;
}) {
  if (!currentStatus || !(currentStatus in STAGE_OF)) return null;
  const currentStage = STAGE_OF[currentStatus];

  // first date each stage was reached (timeline is chronological)
  const reached: (string | null)[] = [null, null, null];
  for (const t of timeline) {
    const stage = t.status_after ? STAGE_OF[t.status_after] : undefined;
    if (stage !== undefined && reached[stage] === null) reached[stage] = t.date;
  }

  const decidedLabel =
    currentStage === 2 ? currentStatus.replace("_", " ") : "Decided";
  const steps = [
    { label: "Proposed", date: reached[0] },
    { label: "Under review", date: reached[1] },
    { label: decidedLabel, date: reached[2] },
  ];

  return (
    <ol className="mb-8 flex max-w-[560px] items-start">
      {steps.map((step, i) => {
        const done = i <= currentStage;
        const isCurrent = i === currentStage;
        const dotCls = !done
          ? "border-2 border-hairline bg-canvas"
          : i === 2
            ? (DECIDED_TINT[currentStatus] ?? "bg-teal text-white") + " border-2 border-transparent"
            : "border-2 border-teal bg-teal";
        return (
          <li key={i} className="flex flex-1 flex-col items-center text-center">
            <div className="flex w-full items-center">
              <div
                className={`h-0.5 flex-1 ${i === 0 ? "invisible" : i <= currentStage ? "bg-teal" : "bg-hairline"}`}
              />
              <span className={`h-3.5 w-3.5 shrink-0 rounded-full ${dotCls}`} />
              <div
                className={`h-0.5 flex-1 ${i === steps.length - 1 ? "invisible" : i < currentStage ? "bg-teal" : "bg-hairline"}`}
              />
            </div>
            <div
              className={`mt-1.5 text-[13px] ${isCurrent ? "font-semibold text-ink" : done ? "font-medium text-body" : "text-muted-soft"}`}
            >
              {step.label}
            </div>
            {step.date && <div className="text-xs text-muted-soft">{fmtShort(step.date)}</div>}
          </li>
        );
      })}
    </ol>
  );
}
