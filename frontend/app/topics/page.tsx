import Link from "next/link";
import { Suspense } from "react";
import DirectoryFilters from "@/components/DirectoryFilters";
import MapClient from "@/components/MapClient";
import Pagination from "@/components/Pagination";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type EntitySummary, type HotTopicsResponse, type MapLocation } from "@/lib/api";

const NO_HOT: HotTopicsResponse = { meetings: [], topics: [] };

export const metadata = {
  title: "Projects & topics",
  description:
    "Every project, ordinance, plan, and development the City of Fairfax council and planning commission have touched — official city records and meeting-derived topics in one directory, with status, activity, and a map.",
};

export const dynamic = "force-dynamic";

const TYPES = [
  { key: "project", label: "Projects" },
  { key: "topic", label: "Plans & programs" },
  { key: "ordinance", label: "Ordinances" },
  { key: "resolution", label: "Resolutions" },
  { key: "case_number", label: "Cases" },
  { key: "location", label: "Places" },
];

const PAGE_SIZE = 40;

interface Query {
  view?: string;
  type?: string;
  official?: string;
  status?: string;
  body?: string;
  days?: string;
  active?: string;
  sort?: string;
  q?: string;
  page?: string;
}

function href(base: Query, patch: Partial<Query>): string {
  const sp = new URLSearchParams();
  const merged: Query = { ...base, ...patch, page: undefined };
  for (const [k, v] of Object.entries(merged)) if (v) sp.set(k, v);
  const qs = sp.toString();
  return qs ? `/topics?${qs}` : "/topics";
}

function Pill({ active, to, children }: { active: boolean; to: string; children: React.ReactNode }) {
  return (
    <Link
      href={to}
      className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${
        active ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}

function HotSection({ hot, title, dot, barColor }: { hot: HotTopicsResponse; title: string; dot: string; barColor: string }) {
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
            <Link href={`/topics/${t.slug}`} className="flex items-center gap-4 px-5 py-3 hover:bg-soft">
              <span className="w-6 shrink-0 text-right text-[15px] font-semibold text-muted-soft">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{t.name}</div>
                <div className="text-[13px] text-muted">
                  {t.entity_type.replace("_", " ")} · {t.chunk_mentions} mentions
                </div>
              </div>
              <div className="hidden w-[220px] shrink-0 items-center gap-2.5 sm:flex">
                <div className="h-1.5 flex-1 rounded-full bg-strong">
                  <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${Math.max(4, (t.seconds / max) * 100)}%` }} />
                </div>
                <span className="w-14 shrink-0 text-[13px] font-semibold text-body">{Math.round(t.seconds / 60)} min</span>
              </div>
              <StatusBadge status={t.current_status} />
            </Link>
          </li>
        ))}
        {hot.topics.length === 0 && (
          <li className="px-5 py-6 text-sm text-muted">No transcribed meetings in the window yet.</li>
        )}
      </ul>
    </section>
  );
}

async function HotList() {
  // one body failing shouldn't blank the other's ranking
  const [council, pc] = await Promise.all([
    api.hotTopics("city_council").catch(() => NO_HOT),
    api.hotTopics("planning_commission").catch(() => NO_HOT),
  ]);
  return (
    <div>
      <HotSection hot={council} title="City Council" dot="bg-teal" barColor="bg-teal" />
      <HotSection hot={pc} title="Planning Commission" dot="bg-ochre" barColor="bg-ochre" />
    </div>
  );
}

function BodyDots({ bodies }: { bodies: string[] }) {
  return (
    <span className="inline-flex items-center gap-1" title={bodies.map((b) => (b === "city_council" ? "City Council" : "Planning Commission")).join(" · ")}>
      {bodies.map((b) => (
        <span key={b} aria-hidden className={`inline-block h-2 w-2 rounded-full ${b === "planning_commission" ? "bg-ochre" : "bg-teal"}`} />
      ))}
    </span>
  );
}

function Card({ e }: { e: EntitySummary }) {
  const official = e.official;
  const primary = official ? `/development/${official.slug}` : `/topics/${e.slug}`;
  const blurb = official?.description ?? null;
  return (
    <li className="flex gap-4 px-5 py-4">
      {official?.image_url && (
        // the city's own project image; plain <img> since the host is external
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={official.image_url}
          alt=""
          loading="lazy"
          className="hidden h-[72px] w-[104px] shrink-0 rounded-xl border border-hairline object-cover sm:block"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <Link href={primary} className="text-[15px] font-semibold text-ink underline-offset-2 hover:underline">
            {e.name}
          </Link>
          <StatusBadge status={e.current_status} />
          {official?.official_status && (
            <span className="rounded-full bg-strong px-2.5 py-[3px] text-xs font-semibold text-body">
              {official.official_status}
            </span>
          )}
        </div>
        <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-muted">
          <BodyDots bodies={e.bodies} />
          <span>{official ? "official city record" : e.entity_type.replace("_", " ")}</span>
          {official?.project_type && <span>· {official.project_type}</span>}
          {official?.address && <span>· {official.address}</span>}
          <span>
            · {e.update_count} update{e.update_count === 1 ? "" : "s"}
            {e.last_seen ? ` · last ${formatDate(e.last_seen)}` : ""}
          </span>
        </div>
        {blurb && <p className="max-w-[760px] text-sm leading-[1.55] text-body">{blurb.length > 220 ? `${blurb.slice(0, 217)}…` : blurb}</p>}
        <div className="mt-2 flex flex-wrap gap-3 text-[13px] font-semibold">
          {official && (
            <Link href={`/topics/${e.slug}`} className="text-muted underline underline-offset-2 hover:text-ink">
              meeting history
            </Link>
          )}
          {e.has_wiki && (
            <Link href={official ? `/development/${official.slug}` : `/topics/${e.slug}/wiki`} className="text-muted underline underline-offset-2 hover:text-ink">
              wiki
            </Link>
          )}
          {official?.has_evaluation && (
            <Link href={`/development/${official.slug}/analysis`} className="text-muted underline underline-offset-2 hover:text-ink">
              impact analysis
            </Link>
          )}
          {e.lat !== null && e.lng !== null && (
            <Link href={`/map?focus=${e.slug}`} className="text-muted underline underline-offset-2 hover:text-ink">
              on the map
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}

function toMapLocation(e: EntitySummary): MapLocation {
  return {
    slug: e.slug,
    name: e.name,
    entity_type: e.entity_type,
    is_official_project: e.official !== null,
    lat: e.lat as number,
    lng: e.lng as number,
    matched_address: null,
    address: e.official?.address ?? null,
    current_status: e.current_status,
    official_status: e.official?.official_status ?? null,
    summary: e.official?.description ?? null,
    status_hint: e.current_status,
    related: [],
  };
}

export default async function TopicsPage({ searchParams }: { searchParams: Query }) {
  const view = searchParams.view === "map" || searchParams.view === "hot" ? searchParams.view : "list";
  const page = Math.max(1, Number(searchParams.page) || 1);
  const isMap = view === "map";
  const isHot = view === "hot";

  const params = new URLSearchParams();
  if (searchParams.type) params.set("entity_type", searchParams.type);
  if (searchParams.status) params.set("status", searchParams.status);
  if (searchParams.body) params.set("body", searchParams.body);
  if (searchParams.days) params.set("days", searchParams.days);
  if (searchParams.official === "true" || searchParams.official === "false") params.set("official", searchParams.official);
  if (searchParams.active === "1") params.set("min_updates", "2");
  if (searchParams.sort) params.set("sort", searchParams.sort);
  if (searchParams.q) params.set("q", searchParams.q);
  // the map wants every pin at once; the list pages
  params.set("limit", String(isMap ? 200 : PAGE_SIZE + 1));
  params.set("offset", String(isMap ? 0 : (page - 1) * PAGE_SIZE));

  const fetched = isHot ? [] : await api.entities(params);
  const hasMore = !isMap && fetched.length > PAGE_SIZE;
  const entities = isMap ? fetched : fetched.slice(0, PAGE_SIZE);
  const pins = entities.filter((e) => e.lat !== null && e.lng !== null).map(toMapLocation);

  const base: Query = { ...searchParams, view: isHot ? "hot" : searchParams.view };
  const noPrimary = !searchParams.type && !searchParams.official;

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">Projects &amp; topics</h1>
        <div className="flex gap-1 rounded-full border border-hairline p-1 text-sm font-medium">
          {[
            { key: "list", label: "List" },
            { key: "map", label: "Map" },
            { key: "hot", label: "🔥 Hot" },
          ].map((v) => (
            <Link
              key={v.key}
              href={href(base, { view: v.key === "list" ? undefined : v.key })}
              className={`rounded-full px-3.5 py-1.5 ${view === v.key ? "bg-ink text-canvas" : "text-muted hover:text-ink"}`}
            >
              {v.label}
            </Link>
          ))}
        </div>
      </div>
      <p className="mb-5 text-sm text-muted">
        Everything the council and planning commission have touched: the city&apos;s official
        project records and every topic surfaced from meetings, with current status and full history.
      </p>

      {!isHot && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Pill active={noPrimary} to={href(base, { type: undefined, official: undefined })}>All</Pill>
            <Pill active={searchParams.official === "true"} to={href(base, { official: searchParams.official === "true" ? undefined : "true", type: undefined })}>
              Official city projects
            </Pill>
            <Pill active={searchParams.official === "false"} to={href(base, { official: searchParams.official === "false" ? undefined : "false", type: undefined })}>
              From meetings only
            </Pill>
            <span className="mx-1 hidden h-5 w-px bg-hairline sm:block" />
            {TYPES.map((t) => (
              <Pill key={t.key} active={searchParams.type === t.key} to={href(base, { type: searchParams.type === t.key ? undefined : t.key, official: undefined })}>
                {t.label}
              </Pill>
            ))}
          </div>
          <div className="mb-5">
            <Suspense fallback={null}>
              <DirectoryFilters />
            </Suspense>
          </div>
        </>
      )}

      {isHot ? (
        <HotList />
      ) : isMap ? (
        <>
          <p className="mb-3 text-[13px] text-muted">
            {pins.length} of {entities.length} matching topics have a location. Pin color follows status.
          </p>
          {pins.length > 0 ? (
            <MapClient locations={pins} />
          ) : (
            <p className="rounded-2xl border border-dashed border-hairline p-6 text-sm text-muted">
              Nothing matching these filters has a mapped location.
            </p>
          )}
        </>
      ) : (
        <>
          <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
            {entities.map((e) => (
              <Card key={e.slug} e={e} />
            ))}
            {entities.length === 0 && (
              <li className="px-5 py-6 text-sm text-muted">
                Nothing matches those filters.{" "}
                <Link href="/topics" className="font-semibold underline underline-offset-2">
                  Clear them
                </Link>
                .
              </li>
            )}
          </ul>
          <Pagination
            page={page}
            hasMore={hasMore}
            basePath="/topics"
            params={{
              type: searchParams.type,
              official: searchParams.official,
              status: searchParams.status,
              body: searchParams.body,
              days: searchParams.days,
              active: searchParams.active,
              sort: searchParams.sort,
              q: searchParams.q,
            }}
          />
        </>
      )}
    </div>
  );
}
