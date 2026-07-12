const STATUS_STYLES: Record<string, string> = {
  proposed: "bg-sky-100 text-sky-800",
  in_progress: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  completed: "bg-emerald-200 text-emerald-900",
  denied: "bg-rose-100 text-rose-800",
  deferred: "bg-slate-200 text-slate-700",
  withdrawn: "bg-slate-200 text-slate-500",
};

export default function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const style = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {status.replace("_", " ")}
    </span>
  );
}
