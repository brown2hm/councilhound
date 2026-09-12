import Link from "next/link";
import BodyTag, { BODY_DOTS } from "@/components/BodyTag";
import FollowButton from "@/components/FollowButton";
import Pagination from "@/components/Pagination";
import { api, formatDate } from "@/lib/api";

export const metadata = {
  title: "Meetings",
  description:
    "Every archived City of Fairfax council and commission meeting, with agenda items, outcomes, votes, and links to the moment on video.",
};

const BODIES = [
  { key: "", label: "All bodies" },
  { key: "city_council", label: "City Council" },
  { key: "planning_commission", label: "Planning Commission" },
];

const PAGE_SIZE = 50;

export default async function MeetingsPage({
  searchParams,
}: {
  searchParams: { body?: string; page?: string };
}) {
  const body = searchParams.body ?? "";
  const page = Math.max(1, Number(searchParams.page) || 1);
  // fetch one extra row to learn whether another page exists
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE + 1),
    offset: String((page - 1) * PAGE_SIZE),
  });
  if (body) params.set("body", body);
  const fetched = await api.meetings(params);
  const hasMore = fetched.length > PAGE_SIZE;
  const meetings = fetched.slice(0, PAGE_SIZE);

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">Meetings</h1>
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/meetings/upcoming.ics`}
          className="rounded-full border border-hairline px-4 py-2 text-sm font-semibold text-muted hover:text-ink"
        >
          📅 Subscribe to the meeting calendar
        </a>
      </div>
      <p className="mb-5 text-sm text-muted">
        Every archived meeting, newest first, with what was decided.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {BODIES.map((b) => (
          <Link
            key={b.key}
            href={b.key ? `/meetings?body=${b.key}` : "/meetings"}
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${
              b.key === body
                ? "bg-ink text-canvas"
                : "border border-hairline bg-canvas text-muted hover:text-ink"
            }`}
          >
            {b.key && (
              <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${BODY_DOTS[b.key]}`} />
            )}
            {b.label}
          </Link>
        ))}
        <span className="flex flex-wrap gap-2 sm:ml-auto">
          {BODIES.filter((b) => b.key && (!body || b.key === body)).map((b) => (
            <FollowButton
              key={b.key}
              target={{ kind: "body", body: b.key }}
              label={`Follow ${b.label} meetings`}
              size="sm"
            />
          ))}
        </span>
      </div>

      <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {meetings.map((m) => (
          <li key={m.id}>
            <Link href={`/meetings/${m.id}`} className="block px-5 py-3 hover:bg-soft">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-semibold">{m.title}</span>
                <span className="shrink-0 text-[13px] font-medium text-muted">
                  {formatDate(m.date)}
                </span>
              </div>
              <div className="flex items-center gap-1 text-[13px] text-muted">
                <BodyTag body={m.body} />
                {m.agenda_item_count > 0 ? <span>· {m.agenda_item_count} agenda items</span> : null}
                {m.duration_seconds ? <span>· {Math.round(m.duration_seconds / 60)} min</span> : null}
              </div>
            </Link>
          </li>
        ))}
        {meetings.length === 0 && (
          <li className="px-5 py-6 text-sm text-muted">
            No meetings on this page. Back to the{" "}
            <Link href="/meetings" className="font-semibold underline underline-offset-2 hover:text-ink">
              most recent
            </Link>
            .
          </li>
        )}
      </ul>

      <Pagination
        page={page}
        hasMore={hasMore}
        basePath="/meetings"
        params={{ body: body || undefined }}
      />
    </div>
  );
}
