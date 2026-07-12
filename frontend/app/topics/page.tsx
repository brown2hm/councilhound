import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate } from "@/lib/api";

const TYPES = ["project", "ordinance", "resolution", "case_number", "topic", "location", "person"];

async function HotList() {
  const hot = await api.hotTopics();
  return (
    <div>
      <p className="mb-3 text-xs text-slate-500">
        Ranked by named discussion time across the {hot.meetings.length} most recent
        transcribed meetings (
        {hot.meetings.map((m) => formatDate(m.date)).join(", ")}).
      </p>
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {hot.topics.map((t, i) => (
          <li key={t.slug}>
            <Link
              href={`/topics/${t.slug}`}
              className="flex items-center gap-4 px-4 py-3 hover:bg-slate-50"
            >
              <span className="w-6 shrink-0 text-right font-mono text-sm text-slate-400">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{t.name}</div>
                <div className="text-xs text-slate-500">
                  {t.entity_type.replace("_", " ")} · {t.chunk_mentions} mentions
                </div>
              </div>
              <span className="shrink-0 text-sm font-semibold text-orange-600">
                {Math.round(t.seconds / 60)} min
              </span>
              <StatusBadge status={t.current_status} />
            </Link>
          </li>
        ))}
        {hot.topics.length === 0 && (
          <li className="px-4 py-6 text-sm text-slate-500">
            No transcribed meetings yet — hot topics appear once transcription lands.
          </li>
        )}
      </ul>
    </div>
  );
}

export default async function TopicsPage({
  searchParams,
}: {
  searchParams: { type?: string; q?: string };
}) {
  const type = searchParams.type ?? "project";
  const isHot = type === "hot";
  const params = new URLSearchParams({ entity_type: type, limit: "100" });
  if (searchParams.q) params.set("q", searchParams.q);
  const entities = isHot ? [] : await api.entities(params);

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Topic tracker</h1>
      <p className="mb-5 text-sm text-slate-500">
        Everything the council and planning commission have touched, with current status and
        full history.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Link
          href="/topics?type=hot"
          className={`rounded-full px-3 py-1 text-sm font-medium ${
            isHot
              ? "bg-orange-600 text-white"
              : "bg-white text-orange-600 ring-1 ring-orange-200 hover:bg-orange-50"
          }`}
        >
          🔥 Hot
        </Link>
        {TYPES.map((t) => (
          <Link
            key={t}
            href={`/topics?type=${t}`}
            className={`rounded-full px-3 py-1 text-sm ${
              t === type
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
            }`}
          >
            {t.replace("_", " ")}
          </Link>
        ))}
        {!isHot && (
          <form className="ml-auto" action="/topics">
            <input type="hidden" name="type" value={type} />
            <input
              name="q"
              defaultValue={searchParams.q ?? ""}
              placeholder="Search names…"
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </form>
        )}
      </div>

      {isHot ? (
        <HotList />
      ) : (
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {entities.map((e) => (
          <li key={e.slug}>
            <Link
              href={`/topics/${e.slug}`}
              className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
            >
              <div>
                <div className="font-medium">{e.name}</div>
                <div className="text-xs text-slate-500">
                  {e.update_count} update{e.update_count === 1 ? "" : "s"}
                  {e.last_seen ? ` · last ${formatDate(e.last_seen)}` : ""}
                </div>
              </div>
              <StatusBadge status={e.current_status} />
            </Link>
          </li>
        ))}
        {entities.length === 0 && (
          <li className="px-4 py-6 text-sm text-slate-500">Nothing here yet.</li>
        )}
      </ul>
      )}
    </div>
  );
}
