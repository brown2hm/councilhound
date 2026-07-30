import { api, BODY_LABELS, formatDate } from "@/lib/api";

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** The record's own state, in the footer of every page. A civic archive that
 * can't say when it last looked can't be told apart from one that's broken. */
export default async function RecordFreshness() {
  const status = await api.status().catch(() => null);
  if (!status) return null;

  const { last_run: run, latest_meeting: latest, counts } = status;
  const checkedAt = run?.finished_at ?? run?.started_at ?? null;
  // the daily job runs every 24h; past two cycles something is wrong
  const stale =
    checkedAt !== null && Date.now() - new Date(checkedAt).getTime() > 48 * 3600 * 1000;
  const degraded = stale || (run !== null && !run.ok);

  return (
    <p className={`text-[12px] ${degraded ? "text-tint-coral-text" : "text-muted"}`}>
      {latest ? (
        <>
          Record current through the {formatDate(latest.date)}{" "}
          {BODY_LABELS[latest.body] ?? latest.body} meeting
        </>
      ) : (
        <>No meetings ingested yet</>
      )}
      {checkedAt && <> · last checked {ago(checkedAt)}</>}
      {degraded && <> · the last ingest didn&apos;t finish cleanly</>}
      {counts.meetings > 0 && (
        <>
          {" "}
          · {counts.meetings} meeting{counts.meetings === 1 ? "" : "s"},{" "}
          {counts.meetings_transcribed} transcribed
        </>
      )}
    </p>
  );
}
