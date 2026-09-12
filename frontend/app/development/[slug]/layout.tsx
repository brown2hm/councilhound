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
      <Link href="/development" className="text-sm font-semibold text-muted hover:text-ink">
        ← Development directory
      </Link>
      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        Development project
      </div>
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
      </p>

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
