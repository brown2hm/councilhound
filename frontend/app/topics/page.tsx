import Link from "next/link";
import { Suspense } from "react";
import DirectoryFilters from "@/components/DirectoryFilters";
import MapClient from "@/components/MapClient";
import Pagination from "@/components/Pagination";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type EntityCounts,
  type EntitySummary,
  type HotTopicsResponse,
  type MapLocation,
} from "@/lib/api";

const NO_HOT: HotTopicsResponse = { meetings: [], topics: [] };

export const metadata = {
  title: "Projects & topics",
  description:
    "Every project, ordinance, plan, and development the City of Fairfax council and planning commission have touched — official city records and meeting-derived topics in one directory, with status, activity, and a map.",
};

export const dynamic = "force-dynamic";

const KIND_LABELS: Record<string, string> = {
  project: "Project",
  topic: "Plan or program",
  ordinance: "Ordinance",
  resolution: "Resolution",
  case_number: "Case",
  location: "Place",
  person: "Person",
};

const PAGE_SIZE = 40;
const OFFICIAL_CARDS = 8;

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

/** Any facet beyond the defaults. The unfiltered directory has a showcase
 * shape (official cards, then the meeting-derived table, then a people
 * row); a filtered one is a single table of matches. */
function isFiltered(q: Query): boolean {
  return Boolean(q.type || q.official || q.status || q.body || q.days || q.q);
}

/** The list query for the API. People are hidden unless asked for, and the
 * one-mention tail is hidden unless the switch is off (`active=0`). */
function listParams(q: Query, extra: Record<string, string>): URLSearchParams {
  const params = new URLSearchParams();
  if (q.type) params.set("entity_type", q.type);
  else params.set("exclude_type", "person");
  if (q.status) params.set("status", q.status);
  if (q.body) params.set("body", q.body);
  if (q.days) params.set("days", q.days);
  if (q.official === "true" || q.official === "false") params.set("official", q.official);
  if (q.active !== "0") params.set("min_updates", "2");
  params.set("sort", q.sort || "active");
  if (q.q) params.set("q", q.q);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  return params;
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

function primaryHref(e: EntitySummary): string {
  return e.official ? `/development/${e.official.slug}` : `/topics/${e.slug}`;
}

/** An official city project: the only records with a photo, an address, and
 * the city's own status, so they get the card treatment. */
function OfficialCard({ e }: { e: EntitySummary }) {
  const o = e.official!;
  return (
    <Link href={primaryHref(e)} className="group flex flex-col gap-2">
      {o.image_url ? (
        // the city's own project image; plain <img> since the host is external
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={o.image_url}
          alt=""
          loading="lazy"
          className="h-32 w-full rounded-xl border border-hairline object-cover"
        />
      ) : (
        <div className="flex h-32 w-full items-center justify-center rounded-xl bg-card text-[11px] font-semibold uppercase tracking-[1px] text-muted-soft">
          {o.project_type ?? "City project"}
        </div>
      )}
      <div className="min-h-[39px] text-[15px] font-semibold leading-[1.3] group-hover:underline group-hover:underline-offset-2">
        {e.name}
      </div>
      <div className="-mt-1 text-[12px] text-muted">
        {o.project_type}
        {o.official_status && (
          <>
            {" · "}
            <span className="text-tint-ochre-text">{o.official_status}</span>
          </>
        )}
        {o.address && (
          <>
            <br />
            {o.address}
          </>
        )}
      </div>
      <div className="text-[12px] tabular-nums text-muted">
        {e.update_count} update{e.update_count === 1 ? "" : "s"}
        {e.last_seen ? ` · last ${formatDate(e.last_seen)}` : ""}
      </div>
    </Link>
  );
}

function Row({ e }: { e: EntitySummary }) {
  return (
    <tr className="border-b border-hairline hover:bg-soft">
      <td className="py-2.5 pr-3">
        <Link href={primaryHref(e)} className="text-[15px] font-semibold underline-offset-2 hover:underline">
          {e.name}
        </Link>
        {e.official && (
          <span className="ml-2 rounded-full bg-strong px-2 py-[2px] text-[11px] font-semibold text-body">official record</span>
        )}
      </td>
      <td className="hidden px-3 py-2.5 text-[13px] text-muted md:table-cell">{KIND_LABELS[e.entity_type] ?? e.entity_type}</td>
      <td className="px-3 py-2.5">
        {e.current_status ? <StatusBadge status={e.current_status} /> : <span className="text-muted-soft">—</span>}
      </td>
      <td className="hidden px-3 py-2.5 md:table-cell">
        <BodyDots bodies={e.bodies} />
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">{e.update_count}</td>
      <td className="whitespace-nowrap py-2.5 pl-3 text-right text-[13px] tabular-nums text-muted">
        {e.last_seen ? formatDate(e.last_seen) : ""}
      </td>
    </tr>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`whitespace-nowrap border-b border-ink pb-2 text-left text-[11px] font-semibold uppercase tracking-[1px] text-muted ${className}`}>
      {children}
    </th>
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
  const filtered = isFiltered(searchParams);
  // the showcase shape: official cards up top, people demoted to a row
  const showcase = !isHot && !isMap && !filtered;

  const params = listParams(searchParams, {
    limit: String(isMap ? 200 : PAGE_SIZE + 1),
    offset: String(isMap ? 0 : (page - 1) * PAGE_SIZE),
  });
  // in the showcase the table is "from meetings": the official records have
  // their own section, and "All N" links to the official-only facet
  if (showcase) params.set("official", "false");

  const [fetched, officialRows, counts] = await Promise.all([
    isHot ? Promise.resolve([] as EntitySummary[]) : api.entities(params),
    showcase && page === 1
      ? api
          .entities(new URLSearchParams({ official: "true", sort: "active", limit: String(OFFICIAL_CARDS) }))
          .catch(() => [] as EntitySummary[])
      : Promise.resolve([] as EntitySummary[]),
    showcase ? api.entityCounts().catch(() => null as EntityCounts | null) : Promise.resolve(null as EntityCounts | null),
  ]);
  const hasMore = !isMap && fetched.length > PAGE_SIZE;
  const entities = isMap ? fetched : fetched.slice(0, PAGE_SIZE);
  const pins = entities.filter((e) => e.lat !== null && e.lng !== null).map(toMapLocation);

  const base: Query = { ...searchParams, view: isHot ? "hot" : searchParams.view };
  const fromMeetings = counts ? counts.records - counts.official : null;

  const tableTitle = showcase
    ? "Plans, ordinances and places from meetings"
    : searchParams.type === "person"
      ? "People named in the record"
      : searchParams.official === "true"
        ? "Official city projects"
        : "Matching records";

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
      <p className="mb-5 max-w-[860px] text-sm text-muted">
        {counts ? `${counts.records.toLocaleString("en-US")} projects` : "Projects"}, plans, ordinances and places the
        council and commission have touched, with status and history. People named in the record are listed
        separately.
      </p>

      {!isHot && (
        <div className="mb-8">
          <Suspense fallback={null}>
            <DirectoryFilters />
          </Suspense>
        </div>
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
          {officialRows.length > 0 && (
            <section className="mb-11">
              <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <h2 className="text-[22px] font-semibold tracking-[-0.3px]">Official city projects</h2>
                  <p className="text-[13px] text-muted">
                    {counts ? `${counts.official} records` : "Records"} from the city&apos;s own project pages, with
                    their photos, addresses and staff status.
                  </p>
                </div>
                <Link
                  href="/topics?official=true"
                  className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                >
                  All {counts?.official ?? ""}
                </Link>
              </div>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {officialRows.map((e) => (
                  <OfficialCard key={e.slug} e={e} />
                ))}
              </div>
            </section>
          )}

          <section className="mb-9">
            <div className="mb-2.5">
              <h2 className="text-[22px] font-semibold tracking-[-0.3px]">{tableTitle}</h2>
              {showcase && (
                <p className="text-[13px] text-muted">
                  {fromMeetings ? `${fromMeetings.toLocaleString("en-US")} topics` : "Topics"} the record has named,
                  most active first. Names, votes and status are set by what was said in a meeting.
                </p>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <Th className="w-[44%]">Name</Th>
                    <Th className="hidden px-3 md:table-cell">Kind</Th>
                    <Th className="px-3">Status</Th>
                    <Th className="hidden px-3 md:table-cell">
                      Body{" "}
                      <span className="font-medium normal-case tracking-normal">
                        (<span aria-hidden className="inline-block h-2 w-2 rounded-full bg-teal" /> council ·{" "}
                        <span aria-hidden className="inline-block h-2 w-2 rounded-full bg-ochre" /> commission)
                      </span>
                    </Th>
                    <Th className="px-3 text-right">Updates</Th>
                    <Th className="pl-3 text-right">Last seen</Th>
                  </tr>
                </thead>
                <tbody>
                  {entities.map((e) => (
                    <Row key={e.slug} e={e} />
                  ))}
                  {entities.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-1 py-6 text-sm text-muted">
                        Nothing matches those filters.{" "}
                        <Link href="/topics" className="font-semibold underline underline-offset-2">
                          Clear them
                        </Link>
                        .
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
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
          </section>

          {showcase && (
            <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-hairline px-5 py-4">
              <div>
                <div className="text-[15px] font-semibold">People named in the record</div>
                <div className="text-[13px] text-muted">
                  {counts ? `${counts.people} applicants` : "Applicants"}, staff and speakers. Kept out of the list
                  above so they don&apos;t crowd the topics.
                </div>
              </div>
              <Link
                href="/topics?type=person"
                className="whitespace-nowrap text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
              >
                Show people
              </Link>
            </section>
          )}
        </>
      )}
    </div>
  );
}
