import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import DiscussionSparkline from "@/components/DiscussionSparkline";
import FollowTopic from "@/components/FollowTopic";
import StatusBadge from "@/components/StatusBadge";
import StatusStepper from "@/components/StatusStepper";
import VoteBlock from "@/components/VotePills";
import { api, formatDate } from "@/lib/api";

const getEntity = cache((slug: string) => api.entity(slug));

export async function generateMetadata({ params }: { params: { slug: string } }) {
  try {
    const entity = await getEntity(params.slug);
    const summary = entity.profile?.summary;
    return {
      title: entity.name,
      description: summary
        ? `${summary.slice(0, 180)}…`
        : `Every action, vote, and update on ${entity.name} in City of Fairfax council and commission meetings.`,
    };
  } catch {
    return {};
  }
}

export default async function TopicDetail({ params }: { params: { slug: string } }) {
  let entity;
  try {
    entity = await getEntity(params.slug);
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
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">{entity.name}</h1>
        <StatusBadge status={entity.current_status} />
      </div>
      {entity.status_source ? (
        <p className="mb-5 text-[13px] text-muted">
          Status set at{" "}
          <Link
            href={`/meetings/${entity.status_source.meeting_id}`}
            className="font-semibold text-muted underline underline-offset-2 hover:text-ink"
          >
            {entity.status_source.meeting_title}
          </Link>{" "}
          on {formatDate(entity.status_source.date)}
          {entity.status_source.watch_url && (
            <>
              {" · "}
              <a
                href={entity.status_source.watch_url}
                target="_blank"
                className="font-semibold text-muted hover:text-ink"
              >
                ▶ watch the moment
              </a>
            </>
          )}
        </p>
      ) : (
        <div className="mb-5" />
      )}

      <div className="mb-6">
        <FollowTopic entitySlug={entity.slug} />
      </div>

      <StatusStepper timeline={entity.timeline} currentStatus={entity.current_status} />

      {entity.upcoming.length > 0 && (
        <div className="mb-8 rounded-2xl border border-ochre bg-callout p-3.5 px-[18px] text-sm text-tint-ochre-text">
          {entity.upcoming.map((u, i) => (
            <div key={i}>
              <span className="font-semibold">
                {u.in_progress ? "Being discussed right now" : "On the upcoming agenda"}:
              </span>{" "}
              {u.title}
              {u.starts_at &&
                ` · ${new Date(u.starts_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}`}
              {u.agenda_url && (
                <>
                  {" · "}
                  <a href={u.agenda_url} target="_blank" className="font-semibold underline underline-offset-2">
                    agenda ↗
                  </a>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {profile?.summary && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Summary</h2>
          <p className="rounded-2xl border border-hairline bg-canvas p-[18px] px-5 text-sm leading-[1.6] text-body">
            {profile.summary}
          </p>
        </section>
      )}

      {entity.official && (
        <section className="mb-8 rounded-2xl border border-hairline bg-canvas p-5">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Official city record</h2>
              <p className="text-[13px] text-muted">
                {[entity.official.project_type, entity.official.division].filter(Boolean).join(" · ")}
              </p>
            </div>
            {entity.official.official_status && (
              <span className="rounded-full bg-strong px-3 py-1 text-xs font-semibold text-body">
                {entity.official.official_status}
              </span>
            )}
          </div>
          {entity.official.description && (
            <p className="mb-3 text-sm leading-[1.6] text-body">{entity.official.description}</p>
          )}
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
            {entity.official.has_evaluation && (
              <Link
                href={`/development/${entity.official.slug}`}
                className="rounded-full border border-ink px-3.5 py-1.5 text-sm font-semibold text-ink hover:bg-ink hover:text-canvas"
              >
                Impact analysis →
              </Link>
            )}
            <a href={entity.official.detail_url} target="_blank" className="inline-block text-sm font-semibold text-muted underline underline-offset-2 hover:text-ink">
              View city project page
            </a>
          </div>
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

      <DiscussionSparkline points={entity.discussion} />

      <section>
        <h2 className="mb-4 text-lg font-semibold">Full history</h2>
        <ol className="relative flex flex-col gap-7 border-l-2 border-strong pl-6">
          {entity.timeline.map((t, i) => (
            <li key={i} id={`m-${t.meeting_id}`} className="group relative scroll-mt-24">
              <span className="absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 border-canvas bg-teal" />
              <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">{formatDate(t.date)}</span>
                <Link
                  href={`/meetings/${t.meeting_id}`}
                  className="inline-flex items-center gap-1.5 text-ink underline underline-offset-2"
                >
                  <BodyTag body={t.body} />
                  {t.agenda_item_label ? <span>· item {t.agenda_item_label}</span> : null}
                </Link>
                <StatusBadge status={t.status_after} />
                <a
                  href={`#m-${t.meeting_id}`}
                  aria-label="Link to this update"
                  className="text-muted-soft opacity-0 transition-opacity hover:text-ink group-hover:opacity-100"
                >
                  #
                </a>
              </div>
              <p className="text-sm leading-[1.6] text-body">{t.update_text}</p>
              {t.votes.map((vote, vi) => (
                <VoteBlock key={vi} vote={vote} />
              ))}
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

      {entity.related.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-1 text-lg font-semibold">Discussed alongside</h2>
          <p className="mb-3 text-[13px] text-muted-soft">
            Topics that come up in the same meetings.
          </p>
          <div className="flex flex-wrap gap-2">
            {entity.related.map((r) => (
              <Link
                key={r.slug}
                href={`/topics/${r.slug}`}
                className="rounded-full bg-card px-4 py-2 text-sm font-medium text-body hover:bg-strong"
              >
                {r.name}
                <span className="ml-1.5 text-xs text-muted-soft">
                  {r.shared_meetings} meetings
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
