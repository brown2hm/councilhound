import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { api, BODY_LABELS, formatDate } from "@/lib/api";

// data comes from the API at request time; never prerender at build
export const dynamic = "force-dynamic";

export default async function Home() {
  const [projects, meetings] = await Promise.all([
    api.entities(new URLSearchParams({ entity_type: "project", limit: "8" })),
    api.meetings(new URLSearchParams({ limit: "8" })),
  ]);

  return (
    <div className="grid gap-10 md:grid-cols-2">
      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Active projects</h2>
          <Link href="/topics" className="text-sm text-sky-600 hover:underline">
            All topics →
          </Link>
        </div>
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {projects.map((p) => (
            <li key={p.slug}>
              <Link
                href={`/topics/${p.slug}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
              >
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-slate-500">
                    {p.update_count} update{p.update_count === 1 ? "" : "s"}
                    {p.last_seen ? ` · last ${formatDate(p.last_seen)}` : ""}
                  </div>
                </div>
                <StatusBadge status={p.current_status} />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Recent meetings</h2>
          <Link href="/meetings" className="text-sm text-sky-600 hover:underline">
            All meetings →
          </Link>
        </div>
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {meetings.map((m) => (
            <li key={m.id}>
              <Link
                href={`/meetings/${m.id}`}
                className="block px-4 py-3 hover:bg-slate-50"
              >
                <div className="font-medium">{m.title}</div>
                <div className="text-xs text-slate-500">
                  {formatDate(m.date)} · {BODY_LABELS[m.body] ?? m.body}
                  {m.agenda_item_count > 0 ? ` · ${m.agenda_item_count} items` : ""}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
