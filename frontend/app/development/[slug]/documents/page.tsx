import { redirect } from "next/navigation";
import { getJurisdiction } from "@/lib/jurisdiction";
import { requireRecord } from "@/lib/not-found";
import { getProject } from "../project";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: { slug: string } }) {
  const [project, j] = await Promise.all([requireRecord(getProject(params.slug)), getJurisdiction()]);
  return {
    title: `${project.name} — documents (${project.documents.length})`,
    description: `Documents ${j.identity.short_name} lists in the official project record for ${project.name}.`,
  };
}

export default async function ProjectDocumentsPage({
  params,
}: {
  params: { slug: string };
}) {
  const j = await getJurisdiction();
  const project = await requireRecord(getProject(params.slug));
  if (project.documents.length === 0) {
    redirect(`/development/${params.slug}`);
  }

  return (
    <div className="max-w-[880px]">
      <p className="mb-6 text-[13px] text-muted">
        Documents published in the {j.identity.noun}&apos;s project record, in the order the
        {j.identity.noun} lists them.
        {project.synced_at && ` Synced ${new Date(project.synced_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}.`}
      </p>

      <ul className="mb-8 divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {project.documents.map((doc, i) => (
          <li key={i}>
            <a
              href={doc.url}
              target="_blank"
              className="block px-5 py-3.5 text-sm font-medium text-body hover:bg-soft"
            >
              {doc.label}
            </a>
          </li>
        ))}
      </ul>

      {project.official_timeline.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2 text-lg font-semibold">Official timeline</h2>
          <ul className="space-y-1.5 text-[13px] leading-[1.55] text-body">
            {project.official_timeline.map((entry, i) => (
              <li key={i}>{entry}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-[12px] text-muted">
        Source:{" "}
        <a
          href={project.detail_url}
          target="_blank"
          className="font-semibold underline underline-offset-2 hover:text-ink"
        >
          the {j.identity.noun}&apos;s project page ↗
        </a>
      </p>
    </div>
  );
}
