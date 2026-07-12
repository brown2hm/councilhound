import Link from "next/link";
import { api, BODY_LABELS, formatDate } from "@/lib/api";

const BODIES = [
  { key: "", label: "All bodies" },
  { key: "city_council", label: "City Council" },
  { key: "planning_commission", label: "Planning Commission" },
];

export default async function MeetingsPage({
  searchParams,
}: {
  searchParams: { body?: string };
}) {
  const body = searchParams.body ?? "";
  const params = new URLSearchParams({ limit: "100" });
  if (body) params.set("body", body);
  const meetings = await api.meetings(params);

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Meetings</h1>
      <p className="mb-5 text-sm text-slate-500">
        Every archived meeting, newest first, with what was decided.
      </p>

      <div className="mb-4 flex gap-2">
        {BODIES.map((b) => (
          <Link
            key={b.key}
            href={b.key ? `/meetings?body=${b.key}` : "/meetings"}
            className={`rounded-full px-3 py-1 text-sm ${
              b.key === body
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
            }`}
          >
            {b.label}
          </Link>
        ))}
      </div>

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {meetings.map((m) => (
          <li key={m.id}>
            <Link href={`/meetings/${m.id}`} className="block px-4 py-3 hover:bg-slate-50">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">{m.title}</span>
                <span className="shrink-0 text-sm text-slate-500">{formatDate(m.date)}</span>
              </div>
              <div className="text-xs text-slate-500">
                {BODY_LABELS[m.body] ?? m.body}
                {m.agenda_item_count > 0 ? ` · ${m.agenda_item_count} agenda items` : ""}
                {m.duration_seconds
                  ? ` · ${Math.round(m.duration_seconds / 60)} min`
                  : ""}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
