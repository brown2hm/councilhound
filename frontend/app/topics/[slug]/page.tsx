import Link from "next/link";
import { notFound } from "next/navigation";
import StatusBadge from "@/components/StatusBadge";
import { api, BODY_LABELS, formatDate } from "@/lib/api";

export default async function TopicDetail({ params }: { params: { slug: string } }) {
  let entity;
  try {
    entity = await api.entity(params.slug);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
        {entity.entity_type.replace("_", " ")}
      </div>
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-semibold">{entity.name}</h1>
        <StatusBadge status={entity.current_status} />
      </div>

      <ol className="relative border-l border-slate-200 pl-6">
        {entity.timeline.map((t, i) => (
          <li key={i} className="relative mb-8">
            <span className="absolute -left-[1.85rem] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-sky-500" />
            <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{formatDate(t.date)}</span>
              <Link
                href={`/meetings/${t.meeting_id}`}
                className="text-sky-600 hover:underline"
              >
                {BODY_LABELS[t.body] ?? t.body}
                {t.agenda_item_label ? ` · item ${t.agenda_item_label}` : ""}
              </Link>
              <StatusBadge status={t.status_after} />
            </div>
            <p className="text-sm leading-relaxed text-slate-700">{t.update_text}</p>
            <div className="mt-1 flex gap-3 text-xs text-slate-400">
              {t.minutes_url && (
                <a href={t.minutes_url} target="_blank" className="hover:text-sky-600">
                  minutes ↗
                </a>
              )}
              {t.agenda_url && (
                <a href={t.agenda_url} target="_blank" className="hover:text-sky-600">
                  agenda ↗
                </a>
              )}
            </div>
          </li>
        ))}
        {entity.timeline.length === 0 && (
          <li className="text-sm text-slate-500">No tracked updates yet.</li>
        )}
      </ol>
    </div>
  );
}
