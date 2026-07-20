import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate } from "@/lib/api";

export const dynamic = "force-dynamic";

const getUpcoming = cache((eventId: string) => api.upcomingDetail(eventId));

export async function generateMetadata({ params }: { params: { eventId: string } }) {
  try {
    const event = await getUpcoming(params.eventId);
    return {
      title: `${event.title} — pre-meeting brief`,
      description: `What's on the agenda for the upcoming ${event.title}, with the history of every tracked topic it touches.`,
    };
  } catch {
    return {};
  }
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default async function UpcomingMeetingPage({
  params,
}: {
  params: { eventId: string };
}) {
  let event;
  try {
    event = await getUpcoming(params.eventId);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-[860px] px-4 pb-16 pt-8 sm:px-8">
      <Link href="/meetings" className="text-sm font-semibold text-muted hover:text-ink">
        ← All meetings
      </Link>
      <div className="mb-1 mt-4 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        {event.body && <BodyTag body={event.body} />}
        <span>· Pre-meeting brief</span>
      </div>
      <h1 className="mb-1 text-[28px] font-medium tracking-[-0.5px]">{event.title}</h1>
      <p className="mb-5 text-sm text-muted">
        {event.in_progress ? (
          <span className="font-semibold text-tint-coral-text">● Happening now</span>
        ) : event.starts_at ? (
          fmtWhen(event.starts_at)
        ) : (
          "Time to be announced"
        )}
        {event.agenda_url && (
          <>
            {" · "}
            <a href={event.agenda_url} target="_blank" className="font-semibold underline underline-offset-2 hover:text-ink">
              official agenda ↗
            </a>
          </>
        )}
      </p>

      {event.topics.length > 0 ? (
        <>
          <h2 className="mb-1 text-lg font-semibold">Tracked topics on this agenda</h2>
          <p className="mb-4 text-[13px] text-muted">
            Matched from the posted agenda — each with its history in the meeting record,
            so you can see where a matter stands before it&apos;s discussed.
          </p>
          <ul className="space-y-3">
            {event.topics.map((t) => (
              <li key={t.slug} className="rounded-2xl border border-hairline bg-canvas p-4 px-5">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Link
                    href={`/topics/${t.slug}`}
                    className="text-[15px] font-semibold underline underline-offset-2 hover:text-muted"
                  >
                    {t.name}
                  </Link>
                  <StatusBadge status={t.current_status} />
                  <span className="text-[12px] text-muted">
                    {t.update_count} update{t.update_count === 1 ? "" : "s"} on record
                    {t.last_seen && ` · last ${formatDate(t.last_seen)}`}
                  </span>
                </div>
                {t.agenda_context && (
                  <p className="mb-1.5 border-l-2 border-hairline pl-3 text-[13px] italic text-muted">
                    “{t.agenda_context}”
                  </p>
                )}
                {t.latest_update && (
                  <p className="text-sm leading-[1.55] text-body">
                    <span className="font-semibold">Previously ({formatDate(t.latest_update.date)}):</span>{" "}
                    {t.latest_update.text}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-3 text-[13px] font-semibold">
                  <Link href={`/topics/${t.slug}`} className="underline underline-offset-2 hover:text-muted">
                    full history
                  </Link>
                  {t.evaluation_slug && (
                    <Link
                      href={`/development/${t.evaluation_slug}`}
                      className="underline underline-offset-2 hover:text-muted"
                    >
                      impact analysis
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="rounded-2xl border border-hairline bg-soft p-5 text-sm text-muted">
          {event.has_agenda_text
            ? "No tracked topics matched this agenda — it may be procedural, or cover matters the tracker hasn't seen before."
            : "The agenda hasn't been posted (or fetched) yet — check back after the city publishes it."}
          {event.agenda_url && (
            <>
              {" "}
              <a href={event.agenda_url} target="_blank" className="font-semibold underline underline-offset-2">
                Read the official agenda ↗
              </a>
            </>
          )}
        </p>
      )}
    </div>
  );
}
