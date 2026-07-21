import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type HotTopicsResponse } from "@/lib/api";

export const metadata = {
  title: "Topic tracker",
  description:
    "Every project, ordinance, and development the City of Fairfax council and planning commission have touched, with current status and full history.",
};

const TYPES = ["project", "ordinance", "resolution", "case_number", "topic", "location", "person"];

function HotSection({
  hot,
  title,
  dot,
  barColor,
}: {
  hot: HotTopicsResponse;
  title: string;
  dot: string;
  barColor: string;
}) {
  const max = Math.max(1, ...hot.topics.map((t) => t.seconds));
  return (
    <section className="mb-8">
      <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
        <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} />
        {title}
      </h2>
      <p className="mb-3 text-[13px] text-muted">
        Named discussion time across {hot.meetings.length} transcribed meeting
        {hot.meetings.length === 1 ? "" : "s"} in the last 60 days.
      </p>
      <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {hot.topics.slice(0, 15).map((t, i) => (
          <li key={t.slug}>
            <Link
              href={`/topics/${t.slug}`}
              className="flex items-center gap-4 px-5 py-3 hover:bg-soft"
            >
              <span className="w-6 shrink-0 text-right text-[15px] font-semibold text-muted-soft">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{t.name}</div>
                <div className="text-[13px] text-muted">
                  {t.entity_type.replace("_", " ")} · {t.chunk_mentions} mentions
                </div>
              </div>
              <div className="hidden w-[220px] shrink-0 items-center gap-2.5 sm:flex">
                <div className="h-1.5 flex-1 rounded-full bg-strong">
                  <div
                    className={`h-1.5 rounded-full ${barColor}`}
                    style={{ width: `${Math.max(4, (t.seconds / max) * 100)}%` }}
                  />
                </div>
                <span className="w-14 shrink-0 text-[13px] font-semibold text-body">
                  {Math.round(t.seconds / 60)} min
                </span>
              </div>
              <StatusBadge status={t.current_status} />
            </Link>
          </li>
        ))}
        {hot.topics.length === 0 && (
          <li className="px-5 py-6 text-sm text-muted">
            No transcribed meetings in the window yet.
          </li>
        )}
      </ul>
    </section>
  );
}

async function HotList() {
  const [council, pc] = await Promise.all([
    api.hotTopics("city_council"),
    api.hotTopics("planning_commission"),
  ]);
  return (
    <div>
      <HotSection hot={council} title="City Council" dot="bg-teal" barColor="bg-teal" />
      <HotSection hot={pc} title="Planning Commission" dot="bg-ochre" barColor="bg-ochre" />
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
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Topic tracker</h1>
      <p className="mb-5 text-sm text-muted">
        Everything the council and planning commission have touched, with current status and full
        history.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Link
          href="/topics?type=hot"
          className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${
            isHot ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
          }`}
        >
          🔥 Hot
        </Link>
        {TYPES.map((t) => (
          <Link
            key={t}
            href={`/topics?type=${t}`}
            className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${
              t === type
                ? "bg-ink text-canvas"
                : "border border-hairline bg-canvas text-muted hover:text-ink"
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
              className="w-[220px] rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-sm outline-none placeholder:text-muted-soft focus:border-ink"
            />
          </form>
        )}
      </div>

      {isHot ? (
        <HotList />
      ) : (
        <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
          {entities.map((e) => (
            <li key={e.slug}>
              <Link
                href={`/topics/${e.slug}`}
                className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-soft"
              >
                <div>
                  <div className="text-sm font-semibold">{e.name}</div>
                  <div className="text-[13px] text-muted">
                    {e.update_count} update{e.update_count === 1 ? "" : "s"}
                    {e.last_seen ? ` · last ${formatDate(e.last_seen)}` : ""}
                  </div>
                </div>
                <StatusBadge status={e.current_status} />
              </Link>
            </li>
          ))}
          {entities.length === 0 && (
            <li className="px-5 py-6 text-sm text-muted">Nothing here yet.</li>
          )}
        </ul>
      )}
    </div>
  );
}
