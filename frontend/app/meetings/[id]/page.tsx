import Link from "next/link";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import ChapterBar from "@/components/ChapterBar";
import Jargon from "@/components/Jargon";
import StatusBadge from "@/components/StatusBadge";
import VoteBlock from "@/components/VotePills";
import { api, formatDate, type MeetingDocument } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";

export const revalidate = 300;

const getMeeting = cache((id: string) => api.meeting(id));

export async function generateMetadata({ params }: { params: { id: string } }) {
  const meeting = await requireRecord(getMeeting(params.id));
  return {
    title: `${meeting.title} · ${formatDate(meeting.date)}`,
    description: `Agenda items, outcomes, and votes from the ${formatDate(meeting.date)} ${meeting.title}, with links to the moment in the meeting video.`,
  };
}

const DOC_LABELS: Record<string, string> = {
  agenda: "Agenda",
  minutes: "Minutes",
  actions_report: "Actions report",
  agenda_item_pdf: "Staff report",
  other: "Document",
};

function docLabel(d: MeetingDocument): string {
  return d.title?.trim() || DOC_LABELS[d.doc_type] || "Document";
}

function DocLinks({ docs }: { docs: MeetingDocument[] }) {
  if (docs.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-2">
      {docs.map((d, i) => (
        <li key={i}>
          <a
            href={d.source_url}
            target="_blank"
            className="inline-flex items-center gap-1 rounded-full bg-card px-3 py-1 text-[12px] font-semibold text-body hover:bg-strong"
          >
            📄 {docLabel(d)}
          </a>
        </li>
      ))}
    </ul>
  );
}

export default async function MeetingPage({ params }: { params: { id: string } }) {
  const meeting = await requireRecord(getMeeting(params.id));

  // agenda + minutes already have buttons above; the rest of the meeting-level
  // record (actions report, packets) gets its own section
  const meetingDocs = meeting.documents.filter(
    (d) => d.agenda_item_id === null && d.doc_type !== "agenda" && d.doc_type !== "minutes",
  );
  const topicCount = new Set(meeting.agenda_items.flatMap((i) => i.entities.map((e) => e.slug))).size;

  return (
    <div className="mx-auto max-w-[860px] px-4 pb-16 pt-8 sm:px-8">
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
        <Link
          href={`/meetings/${params.id}/transcript`}
          className="rounded-xl border border-hairline bg-canvas px-5 py-[11px] font-semibold leading-none hover:border-ink"
        >
          Read the transcript
        </Link>
        <span className="text-[13px] text-muted">
          {meeting.agenda_items.length > 0 ? `${meeting.agenda_items.length} agenda items` : ""}
          {topicCount > 0 ? ` · ${topicCount} tracked topic${topicCount === 1 ? "" : "s"}` : ""}
        </span>
      </div>

      <ChapterBar items={meeting.agenda_items} durationSeconds={meeting.duration_seconds} />

      <h2 className="mb-3 text-lg font-semibold">Agenda</h2>
      <ul className="space-y-3">
        {meeting.agenda_items.map((item) => (
          <li key={item.id} id={`item-${item.label}`} className="scroll-mt-24 rounded-2xl border border-hairline bg-canvas p-[18px] px-5">
            <div className="mb-1 flex flex-wrap items-baseline gap-2">
              <span className="rounded-md bg-card px-2 py-0.5 font-mono text-xs font-semibold text-muted">
                {item.label}
              </span>
              <span className="text-[15px] font-semibold">
                <Jargon>{item.title ?? ""}</Jargon>
              </span>
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
              <p className="mb-2 text-sm leading-[1.55] text-body">
                <Jargon>{item.description}</Jargon>
              </p>
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
            {item.entities.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[12px] font-semibold uppercase tracking-[1px] text-muted-soft">
                  Topics
                </span>
                {item.entities.map((e) => (
                  <Link
                    key={e.slug}
                    href={`/topics/${e.slug}`}
                    className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-medium text-body hover:border-ink"
                  >
                    {e.name}
                    <StatusBadge status={e.status_after ?? e.current_status} />
                  </Link>
                ))}
              </div>
            )}
            <DocLinks docs={item.documents} />
          </li>
        ))}
        {meeting.agenda_items.length === 0 && (
          <li className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
            Not yet processed — agenda items appear after the extraction pass.
          </li>
        )}
      </ul>

      {meetingDocs.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-1 text-lg font-semibold">Meeting documents</h2>
          <p className="mb-3 text-[13px] text-muted">
            Everything the city published for this meeting that isn&apos;t tied to one agenda item.
          </p>
          <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
            {meetingDocs.map((d, i) => (
              <li key={i}>
                <a
                  href={d.source_url}
                  target="_blank"
                  className="flex items-center justify-between gap-3 px-5 py-3 text-sm font-medium text-body hover:bg-soft"
                >
                  <span>📄 {docLabel(d)}</span>
                  <span className="text-[12px] text-muted-soft">{DOC_LABELS[d.doc_type] ?? d.doc_type}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
