import { notFound } from "next/navigation";
import { api, BODY_LABELS, formatDate } from "@/lib/api";

function VoteBreakdown({ breakdown }: { breakdown: Record<string, string> }) {
  const entries = Object.entries(breakdown);
  if (entries.length === 0) return null;
  const color: Record<string, string> = {
    yes: "text-emerald-700",
    no: "text-rose-700",
    abstain: "text-amber-700",
    absent: "text-slate-400",
  };
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([member, vote]) => (
        <span key={member} className={color[vote] ?? "text-slate-600"}>
          {member}: {vote}
        </span>
      ))}
    </div>
  );
}

export default async function MeetingPage({ params }: { params: { id: string } }) {
  let meeting;
  try {
    meeting = await api.meeting(params.id);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
        {BODY_LABELS[meeting.body] ?? meeting.body} · {formatDate(meeting.date)}
      </div>
      <h1 className="mb-3 text-2xl font-semibold">{meeting.title}</h1>
      <div className="mb-8 flex flex-wrap gap-3 text-sm">
        {meeting.video_url && (
          <a href={meeting.video_url} target="_blank"
             className="rounded-md bg-slate-900 px-3 py-1.5 text-white hover:bg-slate-700">
            ▶ Watch recording
          </a>
        )}
        {meeting.agenda_url && (
          <a href={meeting.agenda_url} target="_blank"
             className="rounded-md bg-white px-3 py-1.5 ring-1 ring-slate-200 hover:bg-slate-100">
            Agenda ↗
          </a>
        )}
        {meeting.minutes_url && (
          <a href={meeting.minutes_url} target="_blank"
             className="rounded-md bg-white px-3 py-1.5 ring-1 ring-slate-200 hover:bg-slate-100">
            Minutes ↗
          </a>
        )}
      </div>

      <h2 className="mb-3 text-base font-semibold">Agenda</h2>
      <ul className="space-y-4">
        {meeting.agenda_items.map((item) => (
          <li key={item.id} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-1 flex items-baseline gap-2">
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-500">
                {item.label}
              </span>
              <span className="font-medium">{item.title}</span>
            </div>
            {item.description && (
              <p className="mb-2 text-sm text-slate-600">{item.description}</p>
            )}
            {item.outcome && (
              <p className="text-sm">
                <span className="font-medium text-slate-500">Outcome: </span>
                {item.outcome}
              </p>
            )}
            {item.votes.map((vote, i) => (
              <div key={i} className="mt-2 rounded-md bg-slate-50 p-2 text-sm">
                <span
                  className={`mr-2 font-medium ${
                    vote.motion_result === "passed"
                      ? "text-emerald-700"
                      : vote.motion_result === "failed"
                        ? "text-rose-700"
                        : "text-amber-700"
                  }`}
                >
                  {vote.motion_result}
                </span>
                {vote.description}
                <VoteBreakdown breakdown={vote.vote_breakdown} />
              </div>
            ))}
          </li>
        ))}
        {meeting.agenda_items.length === 0 && (
          <li className="text-sm text-slate-500">
            Not yet processed — agenda items appear after the extraction pass.
          </li>
        )}
      </ul>
    </div>
  );
}
