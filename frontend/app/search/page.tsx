import Link from "next/link";
import BodyTag, { bodyDot } from "@/components/BodyTag";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type SearchResult } from "@/lib/api";
import { bodyLabel, getJurisdiction } from "@/lib/jurisdiction";

export async function generateMetadata() {
  const j = await getJurisdiction();
  return {
    title: "Search the record",
    description:
      `Search every transcribed word and agenda item from ${j.identity.short_name} meetings, with links to the moment on video.`,
  };
}

export const dynamic = "force-dynamic";

/** Window the chunk text around the first match and mark occurrences. */
function Excerpt({ text, query }: { text: string; query: string }) {
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const at = lower.indexOf(q);
  let windowed = text;
  if (text.length > 340) {
    const start = at >= 0 ? Math.max(0, at - 120) : 0;
    windowed = (start > 0 ? "…" : "") + text.slice(start, start + 320) + "…";
  }
  const parts = windowed.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "i"));
  return (
    <p className="text-sm leading-[1.6] text-body">
      {parts.map((part, i) =>
        part.toLowerCase() === q ? (
          <mark key={i} className="rounded bg-tint-ochre px-0.5 text-tint-ochre-text">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </p>
  );
}

function Result({ r, query }: { r: SearchResult; query: string }) {
  return (
    <li className="rounded-2xl border border-hairline bg-canvas p-4 px-5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[13px]">
        <span
          className={`rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold ${
            r.kind === "transcript" ? "bg-card text-muted" : "bg-tint-lavender text-tint-lavender-text"
          }`}
        >
          {r.kind === "transcript" ? "said in meeting" : `agenda ${r.item_label ?? ""}`}
        </span>
        <Link
          href={`/meetings/${r.meeting_id}`}
          className="inline-flex items-center gap-1.5 font-semibold text-ink underline underline-offset-2"
        >
          <BodyTag body={r.body} />
          {r.meeting_title}
        </Link>
        <span className="text-muted">{formatDate(r.date)}</span>
        {r.match === "semantic" && (
          <span className="text-muted-soft" title="matched by meaning, not exact words">
            ~ related
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-3">
          {r.kind === "transcript" && (
            <Link
              href={`/meetings/${r.meeting_id}/transcript?q=${encodeURIComponent(query)}`}
              className="whitespace-nowrap font-semibold text-muted hover:text-ink"
            >
              Read in context
            </Link>
          )}
          {r.watch_url && (
            <a
              href={r.watch_url}
              target="_blank"
              className="whitespace-nowrap font-semibold text-muted hover:text-ink"
            >
              ▶ Watch
            </a>
          )}
        </span>
      </div>
      <Excerpt text={r.text} query={query} />
    </li>
  );
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: { q?: string; body?: string };
}) {
  const j = await getJurisdiction();
  const BODIES = [{ key: "", label: "All bodies" }, ...j.bodies.map((b) => ({ key: b.key, label: b.label }))];
  const q = (searchParams.q ?? "").trim();
  const body = searchParams.body ?? "";
  const data = q.length >= 2 ? await api.search(q, body || undefined) : null;
  const bodyHref = (key: string) => {
    const sp = new URLSearchParams();
    if (q) sp.set("q", q);
    if (key) sp.set("body", key);
    return `/search?${sp.toString()}`;
  };

  return (
    <div className="mx-auto max-w-[820px] px-4 pb-16 pt-12 sm:px-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Search the record</h1>
      <p className="mb-6 text-sm text-muted">
        Every transcribed word and agenda item, with links to the moment on video.
      </p>

      <form method="get" className="mb-3 flex items-center gap-2 rounded-2xl border border-hairline bg-canvas p-2 pl-5">
        {body && <input type="hidden" name="body" value={body} />}
        <input
          name="q"
          defaultValue={q}
          autoFocus={!q}
          placeholder="e.g. bike lanes, tax rate, Chapter 86…"
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-soft"
        />
        <button className="shrink-0 rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active">
          Search
        </button>
      </form>
      <div className="mb-7 flex flex-wrap gap-2">
        {BODIES.map((b) => (
          <Link
            key={b.key}
            href={bodyHref(b.key)}
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${
              b.key === body ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
            }`}
          >
            {b.key && <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${bodyDot(b.key)}`} />}
            {b.label}
          </Link>
        ))}
      </div>

      {data && data.entities.length > 0 && (
        <section className="mb-7">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
            Tracked topics
          </h2>
          <ul className="flex flex-wrap gap-2">
            {data.entities.map((e) => (
              <li key={e.slug}>
                <Link
                  href={`/topics/${e.slug}`}
                  className="inline-flex items-center gap-2 rounded-full border border-hairline bg-canvas px-4 py-2 text-sm font-semibold hover:border-ink"
                >
                  {e.name}
                  <StatusBadge status={e.current_status} />
                  <span className="text-[12px] font-medium text-muted">
                    {e.update_count} update{e.update_count === 1 ? "" : "s"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && (
        <>
          <p className="mb-3 text-[13px] text-muted">
            {data.results.length} passage{data.results.length === 1 ? "" : "s"} for “{data.query}”
            {body ? ` in ${bodyLabel(body)} meetings` : ""}
          </p>
          <ul className="space-y-3">
            {data.results.map((r, i) => (
              <Result key={i} r={r} query={q} />
            ))}
            {data.results.length === 0 && data.entities.length === 0 && (
              <li className="text-sm text-muted">
                Nothing matched. Try fewer or different words — or{" "}
                <Link href={`/ask?q=${encodeURIComponent(q)}`} className="font-semibold underline underline-offset-2">
                  ask the hound
                </Link>
                .
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}
