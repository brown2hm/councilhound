import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate } from "@/lib/api";

export const dynamic = "force-dynamic";

const getMember = cache((slug: string) => api.member(slug));

export async function generateMetadata({ params }: { params: { slug: string } }) {
  try {
    const member = await getMember(params.slug);
    return {
      title: member.name,
      description: `${member.name}'s voting record and positions recorded in City of Fairfax meeting minutes.`,
    };
  } catch {
    return {};
  }
}

const VOTE_TINTS: Record<string, string> = {
  yes: "bg-tint-mint text-tint-mint-text",
  no: "bg-tint-coral text-tint-coral-text",
  abstain: "bg-tint-ochre text-tint-ochre-text",
  absent: "bg-card text-muted-soft",
};

export default async function MemberPage({ params }: { params: { slug: string } }) {
  let member;
  try {
    member = await getMember(params.slug);
  } catch {
    notFound();
  }
  const stats = member.vote_stats;
  const statOrder = ["yes", "no", "abstain", "absent"];

  return (
    <div className="mx-auto max-w-[860px] px-8 pb-16 pt-8">
      <Link href="/members" className="text-sm font-semibold text-muted hover:text-ink">
        ← All members
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        {member.is_current ? "" : "Former · "}
        {member.roles.join(" · ") || "Member"}
      </div>
      <h1 className="mb-4 text-[32px] font-medium tracking-[-0.5px]">{member.name}</h1>
      <div className="mb-9 flex flex-wrap gap-2">
        {statOrder.filter((k) => stats[k]).map((k) => (
          <span key={k} className={`rounded-full px-3 py-1.5 text-sm font-semibold ${VOTE_TINTS[k]}`}>
            {stats[k]} × {k}
          </span>
        ))}
      </div>

      {member.commentary.length > 0 && (
        <section className="mb-9">
          <h2 className="mb-1 text-lg font-semibold">On the record</h2>
          <p className="mb-3 text-[13px] text-muted-soft">
            Positions recorded in minutes, by topic.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {member.commentary.map((c, i) => (
              <Link
                key={i}
                href={`/topics/${c.topic_slug}`}
                className="rounded-2xl border border-hairline bg-canvas p-4 hover:border-ink"
              >
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{c.topic_name}</span>
                  <StatusBadge status={c.topic_status} />
                </div>
                <p className="text-sm leading-[1.6] text-body">{c.summary}</p>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Voting record</h2>
        <ul className="space-y-2.5">
          {member.votes.map((v, i) => (
            <li key={i} className="rounded-2xl border border-hairline bg-canvas p-3.5 px-[18px] text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2.5 py-[3px] text-xs font-semibold ${VOTE_TINTS[v.vote] ?? "bg-card text-body"}`}>
                  {v.vote}
                </span>
                <span className="text-[13px] text-muted">
                  motion {v.motion_result ?? "recorded"}
                </span>
                <Link
                  href={`/meetings/${v.meeting_id}`}
                  className="inline-flex items-center gap-1.5 text-[13px] text-ink underline underline-offset-2"
                >
                  <BodyTag body={v.body} />
                  {formatDate(v.date)}
                  {v.item_label ? ` · item ${v.item_label}` : ""}
                </Link>
                {v.watch_url && (
                  <a
                    href={v.watch_url}
                    target="_blank"
                    className="ml-auto whitespace-nowrap text-[13px] font-semibold text-muted hover:text-ink"
                  >
                    ▶ Watch
                  </a>
                )}
              </div>
              <p className="leading-[1.55] text-body">{v.item_title ?? v.description}</p>
            </li>
          ))}
          {member.votes.length === 0 && (
            <li className="text-sm text-muted">No recorded votes yet.</li>
          )}
        </ul>
      </section>
    </div>
  );
}
