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

/** Status pill. `outline` is the quiet form: same words, no tint — for a
 * "from" status beside a coloured "to", or inside a panel that already has
 * one accent colour and should not gain a second. */
export default function StatusBadge({
  status,
  variant = "tint",
}: {
  status: string | null;
  variant?: "tint" | "outline";
}) {
  if (!status) return null;
  const style =
    variant === "outline"
      ? "border border-ink/20 text-body"
      : STATUS_STYLES[status] ?? "bg-strong text-body";
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-[3px] text-xs font-medium ${style}`}>
      {status.replace("_", " ")}
    </span>
  );
}
