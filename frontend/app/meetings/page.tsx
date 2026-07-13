import Link from "next/link";
import BodyTag, { BODY_DOTS } from "@/components/BodyTag";
import { api, formatDate } from "@/lib/api";

const BODIES = [
  { key: "", label: "All bodies" },
  { key: "city_council", label: "City Council" },
  { key: "planning_commission", label: "Planning Commission" },
];

export default async function MeetingsPage({
  searchParams,
}: {
  searchParams: { body?: string };
}) {
  const body = searchParams.body ?? "";
  const params = new URLSearchParams({ limit: "100" });
  if (body) params.set("body", body);
  const meetings = await api.meetings(params);

  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Meetings</h1>
      <p className="mb-5 text-sm text-muted">
        Every archived meeting, newest first, with what was decided.
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
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
      </ul>
    </div>
  );
}
