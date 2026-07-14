import Link from "next/link";
import BodyTag from "@/components/BodyTag";
import { api, formatDate, type SearchResult } from "@/lib/api";

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
        {r.watch_url && (
          <a
            href={r.watch_url}
            target="_blank"
            className="ml-auto whitespace-nowrap font-semibold text-muted hover:text-ink"
          >
            ▶ Watch
          </a>
        )}
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
  const q = (searchParams.q ?? "").trim();
  const data = q.length >= 2 ? await api.search(q, searchParams.body) : null;

  return (
    <div className="mx-auto max-w-[820px] px-8 pb-16 pt-12">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Search the record</h1>
      <p className="mb-6 text-sm text-muted">
        Every transcribed word and agenda item, with links to the moment on video.
      </p>

      <form method="get" className="mb-7 flex items-center gap-2 rounded-2xl border border-hairline bg-canvas p-2 pl-5">
        <input
          name="q"
          defaultValue={q}
          placeholder="e.g. bike lanes, tax rate, Chapter 86…"
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-soft"
        />
        <button className="shrink-0 rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active">
          Search
        </button>
      </form>

      {data && (
        <>
          <p className="mb-3 text-[13px] text-muted">
            {data.results.length} result{data.results.length === 1 ? "" : "s"} for “{data.query}”
          </p>
          <ul className="space-y-3">
            {data.results.map((r, i) => (
              <Result key={i} r={r} query={q} />
            ))}
            {data.results.length === 0 && (
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
