import Link from "next/link";
import { getJurisdiction } from "@/lib/jurisdiction";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import DiscussionSparkline from "@/components/DiscussionSparkline";
import FollowTopic from "@/components/FollowTopic";
import Jargon from "@/components/Jargon";
import StatusBadge from "@/components/StatusBadge";
import VoteBlock from "@/components/VotePills";
import { api, formatDate, type EntityDetail, type EntityThread, type TimelineEntry } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";

export const revalidate = 300;

const getEntity = cache((slug: string) => api.entity(slug));

const KIND_LABELS: Record<string, string> = {
  project: "Project",
  topic: "Plan or program",
  ordinance: "Ordinance",
  resolution: "Resolution",
  case_number: "Case",
  location: "Place",
  person: "Person",
};

export async function generateMetadata({ params }: { params: { slug: string } }) {
  const [entity, j] = await Promise.all([requireRecord(getEntity(params.slug)), getJurisdiction()]);
  const summary = entity.profile?.summary;
  return {
    title: entity.name,
    description: summary
      ? `${summary.slice(0, 180)}…`
      : `Every action, vote, and update on ${entity.name} in ${j.identity.short_name} public meetings.`,
  };
}

/** Inline citation markers like "[7a]" that the extractor leaves in update
 * text; the row already names its item. */
const stripMarkers = (t: string) => t.replace(/\s*\[\w+\]\s*/g, " ").trim();

/** A summary as a lede and paragraphs: the first sentence leads, the rest
 * breaks where the extractor changed subject ("Separately," …), or every
 * three sentences. */
function splitSummary(summary: string): { lede: string; paras: string[] } {
  const sentences = summary.split(/(?<=[.!?])\s+(?=[A-Z\d“(])/);
  const lede = sentences[0] ?? summary;
  const rest = sentences.slice(1);
  const paras: string[] = [];
  let current: string[] = [];
  for (const s of rest) {
    const breaks = /^(Separately|Meanwhile|In addition|Also|Elsewhere)\b/.test(s) || current.length >= 3;
    if (breaks && current.length) {
      paras.push(current.join(" "));
      current = [];
    }
    current.push(s);
  }
  if (current.length) paras.push(current.join(" "));
  return { lede, paras };
}

function HistoryRow({ t, mention = false, note }: { t: TimelineEntry; mention?: boolean; note?: string }) {
  return (
    <li id={`m-${t.meeting_id}`} className="grid scroll-mt-24 grid-cols-[18px_minmax(0,1fr)] gap-3 border-t border-hairline py-3.5">
      <span
        aria-hidden
        className={`mt-[5px] inline-block h-2.5 w-2.5 rounded-full ${mention ? "border-2 border-[#c9c3b2] bg-canvas" : "bg-teal"}`}
      />
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-[13px]">
          <span className="font-semibold tabular-nums">{formatDate(t.date)}</span>
          <Link href={`/meetings/${t.meeting_id}`} className="text-muted underline-offset-2 hover:underline">
            <BodyTag body={t.body} />
            {t.agenda_item_label ? ` · item ${t.agenda_item_label}` : ""}
          </Link>
          {t.status_after && <StatusBadge status={t.status_after} />}
        </div>
        {t.agenda_item_title && <div className="mt-0.5 text-sm font-semibold">{t.agenda_item_title}</div>}
        <p className="mt-0.5 max-w-[68ch] text-sm leading-[1.6] text-body">{stripMarkers(t.update_text)}</p>
        {mention ? (
          note && <p className="mt-1 text-[12px] text-muted">{note}</p>
        ) : (
          t.votes.map((vote, vi) => <VoteBlock key={vi} vote={vote} />)
        )}
        <div className="mt-1.5 flex gap-3 text-[12px] font-semibold text-muted">
          {t.watch_url && (
            <a href={t.watch_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
              Watch this moment
            </a>
          )}
          {t.minutes_url && (
            <a href={t.minutes_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
              minutes
            </a>
          )}
          {t.agenda_url && (
            <a href={t.agenda_url} target="_blank" className="underline underline-offset-2 hover:text-ink">
              agenda
            </a>
          )}
        </div>
      </div>
    </li>
  );
}

/** One matter that touches this record: the project's own status and lead,
 * then the history rows that belong to it. */
function Thread({ thread, entity }: { thread: EntityThread; entity: EntityDetail }) {
  const href = thread.official_slug ? `/development/${thread.official_slug}` : `/topics/${thread.slug}`;
  const rows = thread.rows.map((i) => entity.timeline[i]).filter(Boolean);
  const kicker = [thread.project_type ?? "Project", thread.official_status].filter(Boolean).join(" · ");
  return (
    <section className="border-t-2 border-ink pt-4 pb-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div>
          <div className="text-[12px] text-muted">{kicker}</div>
          <h2 className="text-[22px] font-semibold tracking-[-0.3px]">
            <Link href={href} className="underline-offset-2 hover:underline">
              {thread.name}
            </Link>
          </h2>
        </div>
        <StatusBadge status={thread.current_status} />
      </div>
      {thread.lead && (
        <p className="mt-2 max-w-[68ch] text-[15px] leading-[1.6] text-body">
          <Jargon>{thread.lead}</Jargon>
        </p>
      )}
      <ul className="mt-2">
        {rows.map((t) => (
          <HistoryRow key={`${t.meeting_id}-${t.agenda_item_label}`} t={t} mention={t.status_after === null && !t.votes.length} />
        ))}
      </ul>
    </section>
  );
}

export default async function TopicDetail({ params }: { params: { slug: string } }) {
  const j = await getJurisdiction();
  const entity = await requireRecord(getEntity(params.slug));
  const profile = entity.profile;
  const threads = entity.threads ?? [];
  const threaded = new Set(threads.flatMap((t) => t.rows));
  const rest = entity.timeline.filter((_, i) => !threaded.has(i));
  const summary = profile?.summary ? splitSummary(profile.summary) : null;
  const kind = KIND_LABELS[entity.entity_type] ?? entity.entity_type.replace("_", " ");
  const firstYear = entity.timeline[0] ? new Date(entity.timeline[0].date + "T00:00:00").getFullYear() : null;

  const statusLine = entity.status_source && (
    <p className="text-[13px] text-muted">
      Status set at the{" "}
      <Link href={`/meetings/${entity.status_source.meeting_id}`} className="font-semibold underline underline-offset-2 hover:text-ink">
        {entity.status_source.meeting_title} on {formatDate(entity.status_source.date)}
      </Link>
      {entity.status_source.watch_url && (
        <>
          {" · "}
          <a href={entity.status_source.watch_url} target="_blank" className="font-semibold underline underline-offset-2 hover:text-ink">
            watch the moment
          </a>
        </>
      )}
    </p>
  );

  const upcoming = entity.upcoming.length > 0 && (
    <div className="rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-sm text-tint-ochre-text">
      {entity.upcoming.map((u, i) => (
        <div key={i}>
          <span className="font-semibold">{u.in_progress ? "Being discussed right now" : "On the upcoming agenda"}:</span> {u.title}
          {u.starts_at && ` · ${new Date(u.starts_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}`}
          {" · "}
          <Link href={`/meetings/upcoming/${encodeURIComponent(u.event_id)}`} className="font-semibold underline underline-offset-2">
            meeting brief
          </Link>
        </div>
      ))}
    </div>
  );

  const official = entity.official && (
    <section className="rounded-2xl border border-hairline bg-canvas p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Official {j.identity.noun} record</h2>
          <p className="text-[13px] text-muted">{[entity.official.project_type, entity.official.division].filter(Boolean).join(" · ")}</p>
        </div>
        {entity.official.official_status && (
          <span className="rounded-full bg-strong px-3 py-1 text-xs font-semibold text-body">{entity.official.official_status}</span>
        )}
      </div>
      {entity.official.description && <p className="mb-3 text-sm leading-[1.6] text-body">{entity.official.description}</p>}
      <div className="grid gap-3 text-[13px] text-muted sm:grid-cols-2">
        {entity.official.address && <div><span className="font-semibold text-body">Location:</span> {entity.official.address}</div>}
        {entity.official.applicant && <div><span className="font-semibold text-body">Applicant:</span> {entity.official.applicant}</div>}
        {entity.official.planner_name && <div><span className="font-semibold text-body">Planner:</span> {entity.official.planner_name}</div>}
        {entity.official.planner_email && (
          <a href={`mailto:${entity.official.planner_email}`} className="font-semibold text-muted underline underline-offset-2 hover:text-ink">
            {entity.official.planner_email}
          </a>
        )}
      </div>
      {entity.official.documents.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-sm font-semibold">Submitted materials</div>
          <div className="flex flex-wrap gap-2">
            {entity.official.documents.slice(0, 6).map((doc, i) => (
              <a key={i} href={doc.url} target="_blank" className="rounded-full bg-card px-3 py-1.5 text-[13px] font-medium text-body hover:bg-strong">
                {doc.label}
              </a>
            ))}
          </div>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <Link href={`/development/${entity.official.slug}`} className="rounded-full border border-ink px-3.5 py-1.5 text-sm font-semibold text-ink hover:bg-ink hover:text-canvas">
          Project page →
        </Link>
        {entity.official.has_evaluation && (
          <Link href={`/development/${entity.official.slug}/analysis`} className="text-sm font-semibold text-muted underline underline-offset-2 hover:text-ink">
            Impact analysis
          </Link>
        )}
        <a href={entity.official.detail_url} target="_blank" className="text-sm font-semibold text-muted underline underline-offset-2 hover:text-ink">
          View {j.identity.noun} project page
        </a>
      </div>
    </section>
  );

  const openQuestions = profile && profile.open_questions.length > 0 && (
    <section>
      <h2 className="mb-2 text-[20px] font-semibold tracking-[-0.3px]">Still open</h2>
      <ul className="flex flex-col gap-2">
        {profile.open_questions.map((q, i) => (
          <li key={i} className="grid grid-cols-[14px_minmax(0,1fr)] gap-2.5 text-[15px] leading-[1.5] text-body">
            <span aria-hidden className="mt-2 inline-block h-2 w-2 rounded-full bg-ochre" />
            <span>
              <Jargon>{q}</Jargon>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );

  const members = profile && profile.member_commentary.length > 0 && (
    <section>
      <h2 className="mb-2 text-[20px] font-semibold tracking-[-0.3px]">What members have said</h2>
      <ul className="border-t border-hairline">
        {profile.member_commentary.map((m, i) => (
          <li key={i} className="grid gap-x-4 gap-y-1 border-b border-hairline py-3 sm:grid-cols-[120px_minmax(0,1fr)]">
            <div className="text-sm font-semibold">
              {m.slug ? (
                <Link href={`/members/${m.slug}`} className="underline-offset-2 hover:underline">
                  {m.member}
                </Link>
              ) : (
                m.member
              )}
            </div>
            <p className="text-sm leading-[1.6] text-body">{m.summary}</p>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-muted">Positions as recorded in meeting minutes; votes without recorded comment aren’t summarized.</p>
    </section>
  );

  const related = entity.related.length > 0 && (
    <section>
      <h2 className="mb-0.5 text-[20px] font-semibold tracking-[-0.3px]">Discussed alongside</h2>
      <p className="mb-2.5 text-[13px] text-muted">Topics that come up in the same meetings.</p>
      <div className="flex flex-wrap gap-2">
        {entity.related.map((r) => (
          <Link key={r.slug} href={`/topics/${r.slug}`} className="rounded-xl bg-card px-3.5 py-2 text-sm font-semibold text-body hover:bg-strong">
            {r.name}
            <span className="ml-1.5 text-xs font-medium text-muted">{r.shared_meetings} meetings</span>
          </Link>
        ))}
      </div>
    </section>
  );

  const followRow = (
    <div className="flex flex-wrap items-center gap-4">
      <FollowTopic entitySlug={entity.slug} />
      {entity.location && (
        <span className="flex gap-3 text-sm font-semibold text-muted">
          <Link href={`/map?focus=${entity.slug}`} className="underline underline-offset-2 hover:text-ink">
            On the map
          </Link>
          <Link
            href={`/nearby?lat=${entity.location.lat}&lng=${entity.location.lng}&r=800&q=${encodeURIComponent(entity.name)}`}
            className="underline underline-offset-2 hover:text-ink"
          >
            What else is nearby
          </Link>
        </span>
      )}
      {entity.has_wiki && (
        <Link href={`/topics/${params.slug}/wiki`} className="text-sm font-semibold text-muted underline underline-offset-2 hover:text-ink">
          Project wiki
        </Link>
      )}
    </div>
  );

  const header = (
    <>
      <Link href="/topics" className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
        ← Projects &amp; topics
      </Link>
      <div className="mb-1.5 mt-5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        {kind}
        {firstYear && ` · on the record since ${firstYear}`}
        {entity.discussion.length > 1 && ` · discussed in ${entity.discussion.length} transcribed meetings`}
      </div>
    </>
  );

  // Threads: a record touched by several projects gets each one on its own
  // terms, with the topic-level facts in a rail. Otherwise a one-column brief.
  if (threads.length > 0) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
        {header}
        <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0">
            <h1 className="mb-2.5 text-[36px] font-medium leading-[1.1] tracking-[-0.7px]">{entity.name}</h1>
            {summary && (
              <p className="mb-7 max-w-[70ch] text-[19px] leading-[1.45] tracking-[-0.2px] text-body-strong">
                <Jargon>{summary.lede}</Jargon>
                {threads.length > 1 && ` ${threads.length} separate matters touch this ${kind.toLowerCase()}; each has its own status.`}
              </p>
            )}
            {upcoming && <div className="mb-6">{upcoming}</div>}
            {official && <div className="mb-6">{official}</div>}
            {threads.map((t) => (
              <Thread key={t.slug} thread={t} entity={entity} />
            ))}
            {rest.length > 0 && (
              <section className="border-t border-hairline pt-4">
                <div className="text-[12px] text-muted">Other mentions</div>
                <ul>
                  {rest.map((t) => (
                    <HistoryRow key={`${t.meeting_id}-${t.agenda_item_label}`} t={t} mention={!t.status_after && !t.votes.length} />
                  ))}
                </ul>
              </section>
            )}
            {summary && summary.paras.length > 0 && (
              <section className="mt-8 border-t border-hairline pt-5">
                <h2 className="mb-2 text-[20px] font-semibold tracking-[-0.3px]">In full</h2>
                {summary.paras.map((p, i) => (
                  <p key={i} className="mb-3 max-w-[68ch] text-[15px] leading-[1.6] text-body">
                    <Jargon>{p}</Jargon>
                  </p>
                ))}
              </section>
            )}
          </div>

          <aside className="flex flex-col gap-6 lg:sticky lg:top-6 lg:self-start">
            <div className="rounded-2xl bg-card px-5 py-4">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">Status</div>
              <StatusBadge status={entity.current_status} />
              <div className="mt-1.5">{statusLine}</div>
              <div className="mt-3">{followRow}</div>
            </div>
            {openQuestions && <div className="text-sm">{openQuestions}</div>}
            {members}
            <DiscussionSparkline points={entity.discussion} compact />
            {related}
          </aside>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[860px] px-4 pb-16 pt-8 sm:px-8">
      {header}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.7px]">
          {entity.name}
          <span className="ml-2 inline-block align-middle">
            <StatusBadge status={entity.current_status} />
          </span>
        </h1>
      </div>
      <div className="mt-2">{statusLine}</div>
      <div className="mt-4">{followRow}</div>
      {upcoming && <div className="mt-6">{upcoming}</div>}

      {summary && (
        <>
          <p className="mb-3.5 mt-7 text-[19px] leading-[1.45] tracking-[-0.2px] text-body-strong">
            <Jargon>{summary.lede}</Jargon>
          </p>
          {summary.paras.map((p, i) => (
            <p key={i} className="mb-3 max-w-[68ch] text-[15px] leading-[1.6] text-body">
              <Jargon>{p}</Jargon>
            </p>
          ))}
        </>
      )}
      {official && <div className="mt-8">{official}</div>}
      {openQuestions && <div className="mt-8">{openQuestions}</div>}
      {members && <div className="mt-8">{members}</div>}
      <div className="mt-8">
        <DiscussionSparkline points={entity.discussion} />
      </div>

      <section className="mt-8">
        <h2 className="mb-0.5 text-[20px] font-semibold tracking-[-0.3px]">History</h2>
        <p className="mb-1.5 text-[13px] text-muted">Filled dots are actions on this topic; open dots are mentions.</p>
        <ul>
          {entity.timeline.map((t) => (
            <HistoryRow key={`${t.meeting_id}-${t.agenda_item_label}`} t={t} mention={!t.status_after && !t.votes.length} />
          ))}
          {entity.timeline.length === 0 && <li className="border-t border-hairline py-4 text-sm text-muted">No tracked updates yet.</li>}
        </ul>
      </section>

      {related && <div className="mt-8">{related}</div>}
    </div>
  );
}
