import Link from "next/link";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import ChapterBar from "@/components/ChapterBar";
import Jargon from "@/components/Jargon";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type AgendaItemInfo, type MeetingDocument, type VoteInfo } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";

export const revalidate = 300;

const getMeeting = cache((id: string) => api.meeting(id));

export async function generateMetadata({ params }: { params: { id: string } }) {
  const meeting = await requireRecord(getMeeting(params.id));
  return {
    title: `${meeting.title} · ${formatDate(meeting.date)}`,
    description: `What the ${formatDate(meeting.date)} ${meeting.title} decided, with the recording, agenda, transcript and documents.`,
  };
}

const DOC_LABELS: Record<string, string> = {
  agenda: "Agenda",
  minutes: "Minutes",
  actions_report: "Actions report",
  agenda_item_pdf: "Staff report",
  other: "Document",
};

function docKind(d: MeetingDocument): string {
  return d.title?.trim() || DOC_LABELS[d.doc_type] || "Document";
}

function duration(seconds: number | null): string | null {
  if (!seconds) return null;
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

function timestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The result line for a vote: "Passed, unanimous", "Failed 3–4", … derived
 * from the breakdown when the minutes recorded one, else from the outcome. */
function resultLine(vote: VoteInfo, outcome: string | null): string {
  const casts = Object.values(vote.vote_breakdown ?? {});
  const yes = casts.filter((c) => c === "yes").length;
  const no = casts.filter((c) => c === "no").length;
  const result = vote.motion_result === "passed" ? "Passed" : vote.motion_result === "failed" ? "Failed" : vote.motion_result ? vote.motion_result.charAt(0).toUpperCase() + vote.motion_result.slice(1) : "Vote recorded";
  if (yes + no > 0) return no === 0 ? `${result}, unanimous` : `${result} ${yes}–${no}`;
  if (/\bunanimous/i.test(outcome ?? "")) return `${result}, unanimous`;
  return result;
}

/** Outcome text as filed opens with the result ("Approved unanimously.")
 * that the result line already states. */
const outcomeText = (o: string | null) => (o ?? "").replace(/^(Approved|Adopted|Denied|Passed|Failed)( unanimously| \d+[–-]\d+)?\.\s*/i, "");

const isProclamation = (it: AgendaItemInfo) => /^proclamation/i.test(it.title ?? "");
const proclamationDates = (o: string | null) => (o ?? "").replace(/^Proclamation presented acknowledging (.*?) as .*$/i, "$1").replace(/\.$/, "");

function Topics({ item }: { item: AgendaItemInfo }) {
  if (item.entities.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {item.entities.map((e) => (
        <Link
          key={e.slug}
          href={`/topics/${e.slug}`}
          className="inline-flex items-center gap-1.5 rounded-full bg-card px-2.5 py-1 text-[12px] font-semibold text-body hover:bg-strong"
        >
          {e.name}
          <StatusBadge status={e.status_after ?? e.current_status} />
        </Link>
      ))}
    </div>
  );
}

function Mark({ result }: { result: string | null }) {
  const passed = result === "passed";
  const failed = result === "failed";
  return (
    <span
      aria-hidden
      className={`inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${
        passed ? "bg-tint-mint text-tint-mint-text" : failed ? "bg-tint-coral text-tint-coral-text" : "bg-strong text-muted"
      }`}
    >
      {passed ? "✓" : failed ? "✕" : "·"}
    </span>
  );
}

function DecisionRow({ item }: { item: AgendaItemInfo }) {
  const vote = item.votes[0];
  return (
    <li id={`item-${item.label}`} className="grid scroll-mt-24 grid-cols-[18px_36px_minmax(0,1fr)] items-baseline gap-2.5 border-t border-hairline py-3 sm:grid-cols-[18px_36px_minmax(0,1fr)_auto]">
      <Mark result={vote.motion_result} />
      <span className="text-[12px] tabular-nums text-muted">{item.label}</span>
      <div className="min-w-0">
        <div className="text-base font-semibold leading-[1.3]">
          <Jargon>{item.title ?? ""}</Jargon>
        </div>
        {outcomeText(item.outcome) && (
          <p className="mt-1 max-w-[62ch] text-sm leading-[1.5] text-body">{outcomeText(item.outcome)}</p>
        )}
        {!item.outcome && item.description && (
          <p className="mt-1 max-w-[62ch] text-sm leading-[1.5] text-body">
            <Jargon>{item.description}</Jargon>
          </p>
        )}
        <div className="mt-1 text-[12px] text-muted">
          {resultLine(vote, item.outcome)}
          {item.votes.length > 1 && ` · ${item.votes.length} motions on this item`}
        </div>
        <Topics item={item} />
      </div>
      <span className="hidden whitespace-nowrap text-[12px] sm:block">
        {item.watch_url && item.start_seconds !== null ? (
          <a href={item.watch_url} target="_blank" className="font-semibold text-muted underline underline-offset-2 hover:text-ink">
            watch {timestamp(item.start_seconds)}
          </a>
        ) : (
          <span className="text-muted-soft">not chaptered</span>
        )}
      </span>
    </li>
  );
}

function PresentedRow({ item }: { item: AgendaItemInfo }) {
  const proclamation = isProclamation(item);
  const title = proclamation ? (item.title ?? "").replace(/^proclamation:\s*/i, "") : item.title ?? "";
  const note = proclamation ? `proclamation, ${proclamationDates(item.outcome)}` : outcomeText(item.outcome) || item.description || "";
  return (
    <li id={`item-${item.label}`} className="grid scroll-mt-24 grid-cols-[18px_36px_minmax(0,1fr)] items-baseline gap-2.5 border-t border-hairline py-2.5 text-sm sm:grid-cols-[18px_36px_minmax(0,1fr)_auto]">
      <span aria-hidden className="mx-[5px] inline-block h-2 w-2 rounded-full bg-strong" />
      <span className="text-[12px] tabular-nums text-muted">{item.label}</span>
      <div className="min-w-0">
        <span className="font-semibold">
          <Jargon>{title}</Jargon>
        </span>
        {note && <span className="text-muted"> · {note}</span>}
        <Topics item={item} />
      </div>
      <span className="hidden whitespace-nowrap text-[12px] sm:block">
        {item.watch_url && item.start_seconds !== null && (
          <a href={item.watch_url} target="_blank" className="font-semibold text-muted underline underline-offset-2 hover:text-ink">
            watch {timestamp(item.start_seconds)}
          </a>
        )}
      </span>
    </li>
  );
}

export default async function MeetingPage({ params }: { params: { id: string } }) {
  const meeting = await requireRecord(getMeeting(params.id));
  const items = meeting.agenda_items;
  const decided = items.filter((it) => it.votes.length > 0);
  const presented = items.filter((it) => it.votes.length === 0);
  const unanimous = decided.length > 0 && decided.every((it) => /unanimous/i.test(resultLine(it.votes[0], it.outcome)));
  const chapters = items
    .filter((it) => it.start_seconds !== null && it.watch_url)
    .sort((a, b) => (a.start_seconds ?? 0) - (b.start_seconds ?? 0));

  // every topic the meeting touched, once, with the status it set if any
  const topics = new Map<string, { name: string; status: string | null }>();
  for (const it of items)
    for (const e of it.entities) {
      const prev = topics.get(e.slug);
      if (!prev) topics.set(e.slug, { name: e.name, status: e.status_after ?? e.current_status });
      else if (!prev.status && e.status_after) prev.status = e.status_after;
    }

  // documents by kind (the agenda itself has a button already)
  const files = meeting.documents.filter((d) => d.doc_type !== "agenda");
  const kinds = new Map<string, MeetingDocument[]>();
  for (const d of files) kinds.set(docKind(d), [...(kinds.get(docKind(d)) ?? []), d]);

  const facts = [
    duration(meeting.duration_seconds),
    items.length ? `${items.length} agenda items` : null,
    decided.length ? `${decided.length} vote${decided.length === 1 ? "" : "s"}${unanimous ? ", all unanimous" : ""}` : null,
    topics.size ? `${topics.size} tracked topic${topics.size === 1 ? "" : "s"}` : null,
  ].filter(Boolean);

  const linkClass = "rounded-xl border border-hairline bg-canvas px-4 py-[9px] text-[13px] font-semibold leading-none hover:border-ink";

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <Link href="/meetings" className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
        ← All meetings
      </Link>
      <div className="mb-1 mt-4 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        <BodyTag body={meeting.body} /> <span>· {formatDate(meeting.date)}</span>
      </div>
      <h1 className="mb-3.5 text-[36px] font-medium leading-[1.1] tracking-[-0.7px]">{meeting.title}</h1>
      <div className="mb-3 flex flex-wrap items-center gap-x-2.5 gap-y-2">
        {meeting.video_url && (
          <a href={meeting.video_url} target="_blank" className="rounded-xl bg-ink px-4 py-[9px] text-[13px] font-semibold leading-none text-white hover:bg-ink-active">
            ▶ Watch recording
          </a>
        )}
        {meeting.agenda_url && (
          <a href={meeting.agenda_url} target="_blank" className={linkClass}>
            Agenda
          </a>
        )}
        {meeting.minutes_url && (
          <a href={meeting.minutes_url} target="_blank" className={linkClass}>
            Minutes
          </a>
        )}
        <Link href={`/meetings/${params.id}/transcript`} className={linkClass}>
          Read the transcript
        </Link>
        {facts.length > 0 && <span className="ml-1 text-[13px] tabular-nums text-muted">{facts.join(" · ")}</span>}
      </div>

      <ChapterBar items={items} durationSeconds={meeting.duration_seconds} />

      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          {decided.length > 0 && (
            <section>
              <h2 className="mb-1.5 text-[20px] font-semibold tracking-[-0.3px]">What was decided</h2>
              <ul>
                {decided.map((it) => (
                  <DecisionRow key={it.id} item={it} />
                ))}
              </ul>
            </section>
          )}
          {presented.length > 0 && (
            <section className={decided.length ? "mt-7" : ""}>
              <h2 className="mb-1.5 text-[20px] font-semibold tracking-[-0.3px]">{decided.length ? "Presented" : "Discussed"}</h2>
              <ul>
                {presented.map((it) => (
                  <PresentedRow key={it.id} item={it} />
                ))}
              </ul>
            </section>
          )}
          {items.length === 0 && (
            <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
              Not yet processed. Agenda items appear after the extraction pass.
            </p>
          )}
        </div>

        <aside className="flex min-w-0 flex-col gap-5 lg:sticky lg:top-6 lg:self-start">
          {meeting.video_url && (
            <div className="rounded-2xl bg-teal px-5 py-4 text-white">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-mint">
                Recording{duration(meeting.duration_seconds) ? ` · ${duration(meeting.duration_seconds)}` : ""}
              </div>
              <a href={meeting.video_url} target="_blank" className="block rounded-xl bg-canvas px-4 py-2.5 text-center text-[13px] font-semibold text-ink">
                ▶ Watch from the start
              </a>
              {chapters.length > 0 && (
                <ul className="mt-3 flex flex-col gap-1.5 text-[13px]">
                  {chapters.map((it) => (
                    <li key={it.id} className="flex gap-2.5">
                      <a href={it.watch_url!} target="_blank" className="w-11 shrink-0 font-semibold tabular-nums text-mint hover:underline">
                        {timestamp(it.start_seconds!)}
                      </a>
                      <span className="min-w-0">
                        <span className="text-white/60">{it.label}</span> · {it.title}
                      </span>
                    </li>
                  ))}
                  {chapters.length < items.length && (
                    <li className="text-[12px] text-white/55">Other items are not chaptered in the recording.</li>
                  )}
                </ul>
              )}
            </div>
          )}

          {kinds.size > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Documents · {files.length}</div>
              <ul className="text-[13px]">
                {Array.from(kinds.entries()).map(([kind, docs]) => (
                  <li key={kind} className="border-b border-hairline-soft">
                    {docs.length === 1 ? (
                      <a href={docs[0].source_url} target="_blank" className="flex items-center justify-between gap-2 py-1.5 font-medium underline-offset-2 hover:underline">
                        {kind}
                        <span className="tabular-nums text-muted">1</span>
                      </a>
                    ) : (
                      <details className="group">
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-1.5 font-medium">
                          {kind}
                          <span className="tabular-nums text-muted">{docs.length}</span>
                        </summary>
                        <ul className="mb-2 flex flex-wrap gap-x-3 gap-y-1 pl-3 text-[12px]">
                          {docs.map((d, i) => (
                            <li key={i}>
                              <a href={d.source_url} target="_blank" className="text-muted underline underline-offset-2 hover:text-ink">
                                {kind} {i + 1}
                              </a>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-[12px] text-muted-soft">Filed in agenda order; the agenda names the item each belongs to.</p>
            </div>
          )}

          {topics.size > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Topics touched · {topics.size}</div>
              <ul className="text-[13px]">
                {Array.from(topics.entries()).map(([slug, t]) => (
                  <li key={slug} className="flex items-center justify-between gap-2 border-b border-hairline-soft py-1.5">
                    <Link href={`/topics/${slug}`} className="min-w-0 truncate font-medium underline-offset-2 hover:underline">
                      {t.name}
                    </Link>
                    <StatusBadge status={t.status} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
