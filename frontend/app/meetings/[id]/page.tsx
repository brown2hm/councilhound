import Link from "next/link";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import ChapterBar from "@/components/ChapterBar";
import Jargon from "@/components/Jargon";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type AgendaItemEntity,
  type AgendaItemInfo,
  type MeetingDocument,
  type MeetingTopic,
  type NamedInDiscussion,
  type VoteInfo,
} from "@/lib/api";
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

/** Where a topic's wiki lives: under the city's project record when it
 * keeps one, else on the topic route. */
const wikiHref = (t: { slug: string; official_slug: string | null }) =>
  t.official_slug ? `/development/${t.official_slug}` : `/topics/${t.slug}/wiki`;

/** A rail-sized cut of a long open question; the topic page has it whole. */
function clip(text: string, max = 200): string {
  if (text.length <= max) return text;
  return text.slice(0, max).replace(/\s+\S*$/, "").replace(/[\s,;:(–-]+$/, "") + "…";
}

/** Inline citation markers like "[7a]" that the extractor leaves in update
 * text; the row already names its item. */
const stripMarkers = (t: string) => t.replace(/\s*\[[\w/-]+\]\s*/g, " ").replace(/\s{2,}/g, " ").trim();

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

const linkMuted = "font-semibold text-muted underline underline-offset-2 hover:text-ink";

function TopicChip({ e }: { e: AgendaItemEntity }) {
  return (
    <Link
      href={`/topics/${e.slug}`}
      className="inline-flex items-center gap-1.5 rounded-full bg-card px-2.5 py-1 text-[12px] font-semibold text-body hover:bg-strong"
    >
      {e.name}
      <StatusBadge status={e.status_after ?? e.current_status} />
    </Link>
  );
}

/** The topics an item touches. A topic the record filed a sentence for gets
 * that sentence — what happened to it here — and a wiki link when it has
 * one; a bare mention stays a chip. */
function Topics({ item }: { item: AgendaItemInfo }) {
  if (item.entities.length === 0) return null;
  const told = item.entities.filter((e) => e.update_text);
  const bare = item.entities.filter((e) => !e.update_text);
  return (
    <>
      {told.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {told.map((e) => (
            <li key={e.slug} className="grid grid-cols-[8px_minmax(0,1fr)] gap-2 text-[13px] leading-[1.5]">
              <span aria-hidden className="mt-[7px] inline-block h-1.5 w-1.5 rounded-full bg-teal" />
              <div className="min-w-0 max-w-[62ch]">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Link href={`/topics/${e.slug}`} className="font-semibold underline-offset-2 hover:underline">
                    {e.name}
                  </Link>
                  <StatusBadge status={e.status_after ?? e.current_status} />
                  {e.has_wiki && (
                    <Link href={wikiHref(e)} className={`text-[12px] ${linkMuted}`}>
                      wiki
                    </Link>
                  )}
                </span>
                <span className="text-body">
                  <Jargon>{stripMarkers(e.update_text!)}</Jargon>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {bare.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {bare.map((e) => (
            <TopicChip key={e.slug} e={e} />
          ))}
        </div>
      )}
    </>
  );
}

/** The transcript's account of a chaptered item: how long it ran and which
 * tracked topics came up that the item is not filed under. A window with
 * unchaptered items inside it gets no duration, and its names are labelled
 * as running to the next chapter rather than belonging to this item. */
function Discussion({ item, meetingId }: { item: AgendaItemInfo; meetingId: string }) {
  const d = item.discussion;
  if (!d) return null;
  const timed = d.exact && d.seconds >= 60;
  if (!timed && d.named.length === 0) return null;
  return (
    <p className="mt-1 text-[12px] leading-[1.6] text-muted">
      {timed && <>Discussed for {duration(d.seconds)}</>}
      {d.named.length > 0 && (
        <>
          {timed ? " · also names " : d.exact ? "Names " : "Until the next chapter, names "}
          {d.named.map((n, i) => (
            <span key={n.slug}>
              {i > 0 && ", "}
              <Link href={`/topics/${n.slug}`} className="font-semibold text-body underline-offset-2 hover:underline">
                {n.name}
              </Link>
              {n.count > 1 && <span className="tabular-nums"> ×{n.count}</span>}
            </span>
          ))}
        </>
      )}
      {" · "}
      <Link href={`/meetings/${meetingId}/transcript#item-${item.id}`} className={linkMuted}>
        read the transcript
      </Link>
    </p>
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

function DecisionRow({ item, meetingId }: { item: AgendaItemInfo; meetingId: string }) {
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
        <Discussion item={item} meetingId={meetingId} />
        <Topics item={item} />
      </div>
      <span className="hidden whitespace-nowrap text-[12px] sm:block">
        {item.watch_url && item.start_seconds !== null ? (
          <a href={item.watch_url} target="_blank" className={linkMuted}>
            watch {timestamp(item.start_seconds)}
          </a>
        ) : (
          <span className="text-muted-soft">not chaptered</span>
        )}
      </span>
    </li>
  );
}

function PresentedRow({ item, meetingId }: { item: AgendaItemInfo; meetingId: string }) {
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
        <Discussion item={item} meetingId={meetingId} />
        <Topics item={item} />
      </div>
      <span className="hidden whitespace-nowrap text-[12px] sm:block">
        {item.watch_url && item.start_seconds !== null && (
          <a href={item.watch_url} target="_blank" className={linkMuted}>
            watch {timestamp(item.start_seconds)}
          </a>
        )}
      </span>
    </li>
  );
}

/** A tracked topic the transcript names that nothing on the agenda links:
 * the count, the first passage, and where to hear or read it. */
function NamedRow({ t, meetingId }: { t: NamedInDiscussion; meetingId: string }) {
  return (
    <li className="grid grid-cols-[8px_minmax(0,1fr)] gap-2.5 border-t border-hairline py-3">
      <span aria-hidden className="mt-[7px] inline-block h-1.5 w-1.5 rounded-full border-2 border-[#c9c3b2] bg-canvas" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
          <Link href={`/topics/${t.slug}`} className="font-semibold underline-offset-2 hover:underline">
            {t.name}
          </Link>
          <StatusBadge status={t.current_status} />
          <span className="tabular-nums text-muted">
            {t.count === 1 ? "once" : `${t.count} passages`}
            {t.seconds >= 60 && `, ${duration(t.seconds)}`}
          </span>
        </div>
        <p className="mt-1 max-w-[62ch] text-sm leading-[1.55] text-body">“{t.first.excerpt}”</p>
        <div className="mt-1.5 flex flex-wrap gap-3 text-[12px]">
          {t.first.watch_url && (
            <a href={t.first.watch_url} target="_blank" className={linkMuted}>
              watch {timestamp(t.first.start_seconds)}
            </a>
          )}
          <Link href={`/meetings/${meetingId}/transcript?q=${encodeURIComponent(t.name)}`} className={linkMuted}>
            every passage
          </Link>
          {t.has_wiki && (
            <Link href={wikiHref(t)} className={linkMuted}>
              wiki
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}

/** One topic in the rail: status, what the wiki already says, what is still
 * open, and the way into the wiki — at this meeting's own entry when the
 * history records it. */
function TopicCard({ t }: { t: MeetingTopic }) {
  const wiki = t.has_wiki ? wikiHref(t) : null;
  return (
    <li className="border-b border-hairline-soft py-2.5">
      <div className="flex items-start justify-between gap-2">
        <Link href={`/topics/${t.slug}`} className="min-w-0 font-semibold leading-snug underline-offset-2 hover:underline">
          {t.name}
        </Link>
        <StatusBadge status={t.status_after ?? t.current_status} />
      </div>
      {t.lede && (
        <p className="mt-1 text-[12px] leading-[1.5] text-muted">
          <Jargon>{t.lede}</Jargon>
        </p>
      )}
      {t.open_questions.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1">
          {t.open_questions.slice(0, 2).map((q, i) => (
            <li key={i} className="grid grid-cols-[6px_minmax(0,1fr)] gap-1.5 text-[12px] leading-[1.45] text-body">
              <span aria-hidden className="mt-[6px] inline-block h-1.5 w-1.5 rounded-full bg-ochre" />
              <span>
                <Jargon>{clip(q)}</Jargon>
              </span>
            </li>
          ))}
        </ul>
      )}
      {wiki && (
        <div className="mt-1.5 flex flex-wrap gap-3 text-[12px]">
          <Link href={t.history_anchor ? `${wiki}#${t.history_anchor}` : wiki} className={linkMuted}>
            {t.history_anchor ? "This meeting in the wiki" : "Wiki"}
          </Link>
          {t.history_anchor && (
            <Link href={wiki} className={linkMuted}>
              Overview
            </Link>
          )}
        </div>
      )}
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
  const topics = meeting.topics;
  const named = meeting.named_in_discussion;
  const inWiki = topics.filter((t) => t.has_wiki).length;

  // documents by kind (the agenda itself has a button already)
  const files = meeting.documents.filter((d) => d.doc_type !== "agenda");
  const kinds = new Map<string, MeetingDocument[]>();
  for (const d of files) kinds.set(docKind(d), [...(kinds.get(docKind(d)) ?? []), d]);

  const facts = [
    duration(meeting.duration_seconds),
    items.length ? `${items.length} agenda items` : null,
    decided.length ? `${decided.length} vote${decided.length === 1 ? "" : "s"}${unanimous ? ", all unanimous" : ""}` : null,
    topics.length ? `${topics.length} tracked topic${topics.length === 1 ? "" : "s"}${inWiki ? `, ${inWiki} in the wiki` : ""}` : null,
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
                  <DecisionRow key={it.id} item={it} meetingId={params.id} />
                ))}
              </ul>
            </section>
          )}
          {presented.length > 0 && (
            <section className={decided.length ? "mt-7" : ""}>
              <h2 className="mb-1.5 text-[20px] font-semibold tracking-[-0.3px]">{decided.length ? "Presented" : "Discussed"}</h2>
              <ul>
                {presented.map((it) => (
                  <PresentedRow key={it.id} item={it} meetingId={params.id} />
                ))}
              </ul>
            </section>
          )}
          {items.length === 0 && (
            <p className="rounded-2xl border border-dashed border-hairline p-5 text-sm text-muted">
              Not yet processed. Agenda items appear after the extraction pass.
            </p>
          )}
          {meeting.other_discussion.length > 0 && (
            <section className="mt-7">
              <h2 className="mb-0.5 text-[20px] font-semibold tracking-[-0.3px]">Also raised</h2>
              <p className="mb-2 text-[13px] text-muted">
                Brought up outside the numbered agenda, in member comments, reports or public comment.
              </p>
              <ul className="flex flex-col gap-1.5">
                {meeting.other_discussion.map((e) => (
                  <li key={e.slug} className="grid grid-cols-[8px_minmax(0,1fr)] gap-2 text-[13px] leading-[1.5]">
                    <span aria-hidden className="mt-[7px] inline-block h-1.5 w-1.5 rounded-full bg-teal" />
                    <div className="min-w-0 max-w-[62ch]">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <Link href={`/topics/${e.slug}`} className="font-semibold underline-offset-2 hover:underline">
                          {e.name}
                        </Link>
                        <StatusBadge status={e.status_after ?? e.current_status} />
                        {e.has_wiki && (
                          <Link href={wikiHref(e)} className={`text-[12px] ${linkMuted}`}>
                            wiki
                          </Link>
                        )}
                      </span>
                      {e.update_text && (
                        <span className="text-body">
                          <Jargon>{stripMarkers(e.update_text)}</Jargon>
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {named.length > 0 && (
            <section className="mt-7">
              <h2 className="mb-0.5 text-[20px] font-semibold tracking-[-0.3px]">Named in discussion</h2>
              <p className="mb-1 max-w-[62ch] text-[13px] text-muted">
                Tracked topics the transcript names that no agenda item is filed under. Their own pages and wikis do not
                yet record this meeting; the passages below are the only trace.
              </p>
              <ul>
                {named.map((t) => (
                  <NamedRow key={t.slug} t={t} meetingId={params.id} />
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className={`flex min-w-0 flex-col gap-5 lg:self-start ${topics.length <= 3 ? "lg:sticky lg:top-6" : ""}`}>
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
                        {it.discussion && it.discussion.exact && it.discussion.seconds >= 60 && (
                          <span className="text-white/60"> · {duration(it.discussion.seconds)}</span>
                        )}
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

          {topics.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Topics touched · {topics.length}</div>
              <ul className="text-[13px]">
                {topics.map((t) => (
                  <TopicCard key={t.slug} t={t} />
                ))}
              </ul>
              {inWiki > 0 && (
                <p className="mt-1.5 text-[12px] text-muted-soft">
                  “This meeting in the wiki” opens the topic’s history at this date.
                </p>
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
        </aside>
      </div>
    </div>
  );
}
