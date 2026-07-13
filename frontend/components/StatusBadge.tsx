const STATUS_STYLES: Record<string, string> = {
  in_progress: "bg-tint-ochre text-tint-ochre-text",
  proposed: "bg-tint-lavender text-tint-lavender-text",
  approved: "bg-tint-mint text-tint-mint-text",
  completed: "bg-tint-mint text-tint-mint-text",
  denied: "bg-tint-coral text-tint-coral-text",
  failed: "bg-tint-coral text-tint-coral-text",
  deferred: "bg-strong text-body",
  continued: "bg-strong text-body",
  withdrawn: "bg-strong text-body",
};

export default function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const style = STATUS_STYLES[status] ?? "bg-strong text-body";
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-[3px] text-xs font-medium ${style}`}>
      {status.replace("_", " ")}
    </span>
  );
}
