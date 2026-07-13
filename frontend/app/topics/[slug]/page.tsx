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

  const profile = entity.profile;

  return (
    <div className="mx-auto max-w-[860px] px-8 pb-16 pt-8">
      <Link href="/topics" className="text-sm font-semibold text-muted hover:text-ink">
        ← Topic tracker
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        {entity.entity_type.replace("_", " ")}
      </div>
      <div className="mb-8 flex flex-wrap items-center gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">{entity.name}</h1>
        <StatusBadge status={entity.current_status} />
      </div>

      {profile?.summary && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Summary</h2>
          <p className="rounded-2xl border border-hairline bg-canvas p-[18px] px-5 text-sm leading-[1.6] text-body">
            {profile.summary}
          </p>
        </section>
      )}

      {profile && profile.open_questions.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Open questions & options on the table</h2>
          <ul className="space-y-2">
            {profile.open_questions.map((q, i) => (
              <li
                key={i}
                className="rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-sm leading-[1.6] text-tint-ochre-text"
              >
                {q}
              </li>
            ))}
          </ul>
        </section>
      )}

      {profile && profile.member_commentary.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">What members have said</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {profile.member_commentary.map((m, i) => (
              <div key={i} className="rounded-2xl border border-hairline bg-canvas p-4">
                <div className="mb-1 text-sm font-semibold">{m.member}</div>
                <p className="text-sm leading-[1.6] text-body">{m.summary}</p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[13px] text-muted-soft">
            Positions as recorded in meeting minutes; votes without recorded comment aren’t
            summarized.
          </p>
        </section>
      )}

      <section>
        <h2 className="mb-4 text-lg font-semibold">Full history</h2>
        <ol className="relative flex flex-col gap-7 border-l-2 border-strong pl-6">
          {entity.timeline.map((t, i) => (
            <li key={i} className="relative">
              <span className="absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 border-canvas bg-teal" />
              <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">{formatDate(t.date)}</span>
                <Link href={`/meetings/${t.meeting_id}`} className="text-ink underline underline-offset-2">
                  {BODY_LABELS[t.body] ?? t.body}
                  {t.agenda_item_label ? ` · item ${t.agenda_item_label}` : ""}
                </Link>
                <StatusBadge status={t.status_after} />
              </div>
              <p className="text-sm leading-[1.6] text-body">{t.update_text}</p>
              <div className="mt-1 flex gap-3 text-[13px] text-muted-soft">
                {t.watch_url && (
                  <a href={t.watch_url} target="_blank" className="font-semibold text-muted hover:text-ink">
                    ▶ Watch this moment
                  </a>
                )}
                {t.minutes_url && (
                  <a href={t.minutes_url} target="_blank" className="hover:text-ink">
                    minutes ↗
                  </a>
                )}
                {t.agenda_url && (
                  <a href={t.agenda_url} target="_blank" className="hover:text-ink">
                    agenda ↗
                  </a>
                )}
              </div>
            </li>
          ))}
          {entity.timeline.length === 0 && (
            <li className="text-sm text-muted">No tracked updates yet.</li>
          )}
        </ol>
      </section>
    </div>
  );
}
