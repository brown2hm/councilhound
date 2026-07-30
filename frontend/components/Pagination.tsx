import Link from "next/link";

/** Prev/next paging that preserves the current filter params.
 * Callers fetch PAGE_SIZE + 1 rows and pass `hasMore` — cheaper than a
 * count endpoint and enough for a two-button control. */
export default function Pagination({
  page,
  hasMore,
  basePath,
  params,
}: {
  page: number;
  hasMore: boolean;
  basePath: string;
  params: Record<string, string | undefined>;
}) {
  if (page === 1 && !hasMore) return null;

  const href = (p: number) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
    if (p > 1) sp.set("page", String(p));
    const qs = sp.toString();
    return qs ? `${basePath}?${qs}` : basePath;
  };

  const linkClass =
    "rounded-full border border-hairline px-4 py-2 text-sm font-medium text-muted hover:text-ink";
  const disabledClass =
    "rounded-full border border-hairline px-4 py-2 text-sm font-medium text-muted-soft opacity-50";

  return (
    <nav className="mt-4 flex items-center justify-between gap-3" aria-label="Pagination">
      {page > 1 ? (
        <Link href={href(page - 1)} className={linkClass} rel="prev">
          ← Newer
        </Link>
      ) : (
        <span className={disabledClass} aria-disabled="true">
          ← Newer
        </span>
      )}
      <span className="text-[13px] text-muted">Page {page}</span>
      {hasMore ? (
        <Link href={href(page + 1)} className={linkClass} rel="next">
          Older →
        </Link>
      ) : (
        <span className={disabledClass} aria-disabled="true">
          Older →
        </span>
      )}
    </nav>
  );
}
