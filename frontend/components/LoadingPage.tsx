/** Shared skeleton for route-level loading.tsx. Every page here is
 * force-dynamic and fans out to several API calls, so the browser otherwise
 * sits on the previous route with no feedback. */
export default function LoadingPage({
  label,
  rows = 5,
  wide = true,
}: {
  label: string;
  rows?: number;
  wide?: boolean;
}) {
  return (
    <div
      className={`mx-auto ${wide ? "max-w-[1280px]" : "max-w-[860px]"} px-4 pb-16 pt-8 sm:px-8`}
      aria-busy="true"
    >
      <p className="sr-only" role="status">
        {label}
      </p>
      <div className="animate-pulse">
        <div className="mb-3 h-8 w-[280px] rounded-lg bg-strong" />
        <div className="mb-7 h-4 w-[420px] max-w-full rounded bg-strong opacity-70" />
        <div className="flex flex-col gap-3">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="rounded-2xl border border-hairline bg-canvas p-5">
              <div className="mb-2.5 h-4 w-[45%] rounded bg-strong" />
              <div className="h-3 w-[70%] rounded bg-strong opacity-70" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
