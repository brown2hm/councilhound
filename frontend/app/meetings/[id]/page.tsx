import Link from "next/link";
import { notFound } from "next/navigation";
import BodyTag from "@/components/BodyTag";
import ChapterBar from "@/components/ChapterBar";
import VoteBlock from "@/components/VotePills";
import { api, formatDate } from "@/lib/api";

export default async function MeetingPage({ params }: { params: { id: string } }) {
  let meeting;
  try {
    meeting = await api.meeting(params.id);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-[860px] px-8 pb-16 pt-8">
      <Link href="/meetings" className="text-sm font-semibold text-muted hover:text-ink">
        ← All meetings
      </Link>
      <div className="mb-1 mt-4 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        <BodyTag body={meeting.body} /> <span>· {formatDate(meeting.date)}</span>
      </div>
      <h1 className="mb-4 text-[32px] font-medium tracking-[-0.5px]">{meeting.title}</h1>
      <div className="mb-9 flex flex-wrap items-center gap-3 text-sm">
        {meeting.video_url && (
          <a
            href={meeting.video_url}
            target="_blank"
            className="rounded-xl bg-ink px-5 py-3 font-semibold leading-none text-white hover:bg-ink-active"
          >
            ▶ Watch recording
          </a>
        )}
        {meeting.agenda_url && (
          <a
            href={meeting.agenda_url}
            target="_blank"
            className="rounded-xl border border-hairline bg-canvas px-5 py-[11px] font-semibold leading-none hover:border-ink"
          >
            Agenda ↗
          </a>
        )}
        {meeting.minutes_url && (
          <a
            href={meeting.minutes_url}
            target="_blank"
            className="rounded-xl border border-hairline bg-canvas px-5 py-[11px] font-semibold leading-none hover:border-ink"
          >
            Minutes ↗
          </a>
        )}
        <span className="text-[13px] text-muted">
          {meeting.agenda_items.length > 0 ? `${meeting.agenda_items.length} agenda items` : ""}
        </span>
      </div>

      <ChapterBar items={meeting.agenda_items} durationSeconds={meeting.duration_seconds} />

      <h2 className="mb-3 text-lg font-semibold">Agenda</h2>
      <ul className="space-y-3">
        {meeting.agenda_items.map((item) => (
          <li key={item.id} className="rounded-2xl border border-hairline bg-canvas p-[18px] px-5">
            <div className="mb-1 flex flex-wrap items-baseline gap-2">
              <span className="rounded-md bg-card px-2 py-0.5 font-mono text-xs font-semibold text-muted">
                {item.label}
              </span>
              <span className="text-[15px] font-semibold">{item.title}</span>
              {item.watch_url && (
                <a
                  href={item.watch_url}
                  target="_blank"
                  className="ml-auto whitespace-nowrap text-[13px] font-semibold text-muted hover:text-ink"
                >
                  ▶ Watch this item
                </a>
              )}
            </div>
            {item.description && (
              <p className="mb-2 text-sm leading-[1.55] text-body">{item.description}</p>
            )}
            {item.outcome && (
              <p className="text-sm leading-[1.55] text-body">
                <span className="font-semibold text-muted">Outcome: </span>
                {item.outcome}
              </p>
            )}
            {item.votes.map((vote, i) => (
              <VoteBlock key={i} vote={vote} />
            ))}
          </li>
        ))}
        {meeting.agenda_items.length === 0 && (
          <li className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
            Not yet processed — agenda items appear after the extraction pass.
          </li>
        )}
      </ul>
    </div>
  );
}
