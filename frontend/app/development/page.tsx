import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DevelopmentPage({
  searchParams,
}: {
  searchParams: { type?: string; status?: string; q?: string };
}) {
  const params = new URLSearchParams();
  if (searchParams.type) params.set("project_type", searchParams.type);
  if (searchParams.status) params.set("status", searchParams.status);
  if (searchParams.q) params.set("q", searchParams.q);
  const allProjects = await api.developmentProjects(params);
  // tolerate an older API that doesn't tag source yet: untagged rows are
  // the official directory
  const projects = allProjects.filter((p) => (p.source ?? "official") === "official");
  const fromMeetings = allProjects.filter(
    (p) => p.source === "meetings" && (p.category ?? "development") === "development",
  );

  const types = Array.from(new Set(projects.map((p) => p.project_type).filter(Boolean))) as string[];
  const statuses = Array.from(new Set(projects.map((p) => p.official_status).filter(Boolean))) as string[];

  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-16 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Development directory</h1>
      <p className="mb-5 text-sm text-muted">
        Official City of Fairfax project records, linked back to CouncilHound topic history
        where available — followed by projects surfaced only from council-meeting discussion.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Link href="/development" className={`rounded-full px-4 py-2 text-sm font-medium ${!searchParams.type && !searchParams.status ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"}`}>
          All
        </Link>
        {types.map((type) => (
          <Link key={type} href={`/development?type=${encodeURIComponent(type)}`} className={`rounded-full px-4 py-2 text-sm font-medium ${searchParams.type === type ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"}`}>
            {type}
          </Link>
        ))}
        {statuses.map((status) => (
          <Link key={status} href={`/development?status=${encodeURIComponent(status)}`} className={`rounded-full px-4 py-2 text-sm font-medium ${searchParams.status === status ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"}`}>
            {status}
          </Link>
        ))}
        <form className="ml-auto" action="/development">
          <input
            name="q"
            defaultValue={searchParams.q ?? ""}
            placeholder="Search projects..."
            className="w-[220px] rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-sm outline-none placeholder:text-muted-soft focus:border-ink"
          />
        </form>
      </div>

      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-lg font-semibold">Official city projects</h2>
        <span className="text-[12px] text-muted">
          synced from the city&apos;s development directory
        </span>
      </div>
      <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {projects.map((project) => (
          <li key={project.slug} className="px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  {project.entity_slug ? (
                    <Link href={`/topics/${project.entity_slug}`} className="text-sm font-semibold text-ink underline underline-offset-2">
                      {project.name}
                    </Link>
                  ) : (
                    <span className="text-sm font-semibold">{project.name}</span>
                  )}
                  {project.entity_status && <StatusBadge status={project.entity_status} />}
                </div>
                <div className="mb-2 text-[13px] text-muted">
                  {[project.project_type, project.division, project.address].filter(Boolean).join(" · ")}
                </div>
                {project.description && (
                  <p className="max-w-[820px] text-sm leading-[1.55] text-body">{project.description}</p>
                )}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2 text-right">
                {project.official_status && (
                  <span className="rounded-full bg-strong px-3 py-1 text-xs font-semibold text-body">
                    {project.official_status}
                  </span>
                )}
                {project.has_evaluation && (
                  <Link
                    href={`/development/${project.slug}`}
                    className="rounded-full border border-ink px-3 py-1 text-xs font-semibold text-ink hover:bg-ink hover:text-canvas"
                  >
                    impact analysis
                  </Link>
                )}
                {project.detail_url && (
                  <a href={project.detail_url} target="_blank" className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink">
                    city record
                  </a>
                )}
              </div>
            </div>
          </li>
        ))}
        {projects.length === 0 && (
          <li className="px-5 py-6 text-sm text-muted">No projects match those filters.</li>
        )}
      </ul>

      {fromMeetings.length > 0 && (
        <>
          <div className="mb-2 mt-10 flex flex-wrap items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <h2 className="text-lg font-semibold">Heard in council meetings</h2>
              <span className="text-[12px] text-muted">
                development projects surfaced from meeting agendas, minutes, and discussion
                — not in the city&apos;s official directory
              </span>
            </div>
            <Link
              href="/civic"
              className="text-[13px] font-semibold underline underline-offset-4 hover:text-muted"
            >
              Other civic topics from meetings →
            </Link>
          </div>
          <ul className="divide-y divide-hairline-soft rounded-2xl border border-dashed border-hairline bg-soft">
            {fromMeetings.map((project) => (
              <li key={project.entity_slug} className="px-5 py-3.5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    {project.entity_slug ? (
                      <Link
                        href={`/topics/${project.entity_slug}`}
                        className="text-sm font-semibold text-ink underline underline-offset-2"
                      >
                        {project.name}
                      </Link>
                    ) : (
                      <span className="text-sm font-semibold">{project.name}</span>
                    )}
                    {project.entity_status && <StatusBadge status={project.entity_status} />}
                    <span className="rounded-full border border-hairline bg-canvas px-2.5 py-0.5 text-[11px] font-semibold text-muted">
                      from meetings
                    </span>
                  </div>
                  {project.entity_slug && (
                    <Link
                      href={`/topics/${project.entity_slug}`}
                      className="text-[13px] font-semibold text-muted underline underline-offset-2 hover:text-ink"
                    >
                      topic history
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
