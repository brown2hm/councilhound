import Link from "next/link";
import ProjectTabs from "@/components/ProjectTabs";
import { requireRecord } from "@/lib/not-found";
import { getProject } from "./project";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: { slug: string } }) {
  const project = await requireRecord(getProject(params.slug));
  return {
    title: `${project.name} — City of Fairfax development project`,
    description: project.description ?? undefined,
  };
}

export default async function DevelopmentProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { slug: string };
}) {
  const project = await requireRecord(getProject(params.slug));

  const meta = [project.project_type, project.division, project.address]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-16 pt-8 sm:px-8">
      <Link href="/topics?official=true" className="text-sm font-semibold text-muted hover:text-ink">
        ← Projects & topics
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Development project
      </div>
      <div className="flex flex-wrap items-start gap-5">
        {project.image_url && (
          // the city's own project rendering/photo; plain <img> since the host is external
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={project.image_url}
            alt={`${project.name}, as pictured in the city's project record`}
            className="order-last h-auto w-full max-w-[280px] rounded-2xl border border-hairline object-cover sm:order-none sm:w-[200px]"
          />
        )}
        <div className="min-w-0 flex-1">
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">{project.name}</h1>
        {project.official_status && (
          <span className="rounded-full bg-strong px-3 py-1 text-xs font-semibold text-body">
            {project.official_status}
          </span>
        )}
      </div>
      <p className="mb-5 text-[13px] text-muted">
        {meta}
        {meta && " · "}
        {project.entity_slug && (
          <>
            <Link
              href={`/topics/${project.entity_slug}`}
              className="font-semibold underline underline-offset-2 hover:text-ink"
            >
              topic history
            </Link>
            {" · "}
          </>
        )}
        <a
          href={project.detail_url}
          target="_blank"
          className="font-semibold underline underline-offset-2 hover:text-ink"
        >
          city record ↗
        </a>
        {project.lat !== null && project.entity_slug && (
          <>
            {" · "}
            <Link href={`/map?focus=${project.entity_slug}`} className="font-semibold underline underline-offset-2 hover:text-ink">
              on the map
            </Link>
          </>
        )}
      </p>
        </div>
      </div>

      <ProjectTabs
        slug={project.slug}
        hasAnalysis={project.has_evaluation}
        hasDocuments={project.documents.length > 0}
        noAnalysisReason={project.no_analysis_reason}
      />
      {children}
    </div>
  );
}
