import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";

export const metadata = {
  title: "Civic topics",
  description:
    "Plans, contracts, studies, and programs surfaced from City of Fairfax council-meeting discussion.",
};

export const dynamic = "force-dynamic";

/** Civic topics surfaced from council-meeting transcripts that are neither
 * official city projects nor built-environment developments: plans,
 * contracts, studies, programs, appointments, events. */
export default async function CivicTopicsPage({
  searchParams,
}: {
  searchParams: { q?: string };
}) {
  const params = new URLSearchParams();
  if (searchParams.q) params.set("q", searchParams.q);
  const allProjects = await api.developmentProjects(params);
  const topics = allProjects.filter(
    (p) => p.source === "meetings" && p.category === "civic",
  );

  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Civic topics</h1>
      <p className="mb-5 max-w-[820px] text-sm text-muted">
        Plans, contracts, studies, programs, and other initiatives surfaced from council
        meeting agendas, minutes, and discussion. Development projects live in the{" "}
        <Link href="/development" className="font-semibold underline underline-offset-2 hover:text-ink">
          development directory
        </Link>
        .
      </p>

      <form className="mb-4" action="/civic">
        <input
          name="q"
          defaultValue={searchParams.q ?? ""}
          placeholder="Search topics..."
          className="w-[260px] rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-sm outline-none placeholder:text-muted-soft focus:border-ink"
        />
      </form>

      <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {topics.map((topic) => (
          <li key={topic.entity_slug ?? topic.name} className="px-5 py-3.5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                {topic.entity_slug ? (
                  <Link
                    href={`/topics/${topic.entity_slug}`}
                    className="text-sm font-semibold text-ink underline underline-offset-2"
                  >
                    {topic.name}
                  </Link>
                ) : (
                  <span className="text-sm font-semibold">{topic.name}</span>
                )}
                {topic.entity_status && <StatusBadge status={topic.entity_status} />}
              </div>
              {topic.entity_slug && (
                <Link
                  href={`/topics/${topic.entity_slug}`}
                  className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                >
                  topic history
                </Link>
              )}
            </div>
          </li>
        ))}
        {topics.length === 0 && (
          <li className="px-5 py-6 text-sm text-muted">
            No civic topics match — the meeting ingest populates this list as
            transcripts are processed.
          </li>
        )}
      </ul>
    </div>
  );
}
