import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "@/components/Markdown";
import { formatDate, type ImpactMetric, type ProjectWiki } from "@/lib/api";
import { metricsByKey, resolveBody, stripSection, WIKI_PAGE_LABELS } from "@/lib/wiki";
import { getEvaluation, getProject, getWiki } from "./project";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: { slug: string } }) {
  try {
    const project = await getProject(params.slug);
    let description = project.description ?? undefined;
    if (project.has_wiki) {
      try {
        const wiki = await getWiki(params.slug);
        description =
          wiki.pages.find((p) => p.page === "overview")?.description ?? description;
      } catch {
        // fall back to the city description
      }
    }
    return {
      title: project.has_wiki
        ? `${project.name} — project wiki`
        : `${project.name} — development project`,
      description: description && description.length > 300
        ? `${description.slice(0, 297)}...`
        : description,
    };
  } catch {
    return {};
  }
}

export default async function DevelopmentWikiPage({
  params,
}: {
  params: { slug: string };
}) {
  let project;
  try {
    project = await getProject(params.slug);
  } catch {
    notFound();
  }

  // the wiki carries the narrative; the evaluation is fetched only so
  // {{metric:...}} markers resolve to live figures
  let wiki: ProjectWiki | null = null;
  let metrics = new Map<string, ImpactMetric>();
  const [wikiResult, evalResult] = await Promise.allSettled([
    project.has_wiki ? getWiki(params.slug) : Promise.reject(new Error("no wiki")),
    project.has_evaluation
      ? getEvaluation(params.slug)
      : Promise.reject(new Error("no evaluation")),
  ]);
  if (wikiResult.status === "fulfilled") wiki = wikiResult.value;
  if (evalResult.status === "fulfilled") metrics = metricsByKey(evalResult.value.metrics);

  // documents.md lives on its own tab; everything else renders inline
  const pages = wiki ? wiki.pages.filter((p) => p.page !== "documents") : [];
  const pageHrefs = { documents: `/development/${params.slug}/documents` };

  if (!wiki) {
    // ~half the official directory has no wiki bundle yet — show the city's
    // own record instead of a dead end
    return (
      <div className="max-w-[880px]">
        <p className="mb-6 rounded-2xl border border-hairline bg-soft p-4 px-5 text-[13px] leading-[1.55] text-muted">
          No wiki yet for this project — it gets one once council meetings pick
          it up. Below is the city&apos;s official record.
        </p>
        {project.description && (
          <p className="mb-4 text-sm leading-[1.6] text-body">{project.description}</p>
        )}
        {project.requests && (
          <p className="mb-4 text-sm leading-[1.6] text-body">
            <span className="font-semibold">Requests:</span> {project.requests}
          </p>
        )}
        <div className="grid gap-3 text-[13px] text-muted sm:grid-cols-2">
          {project.address && (
            <div>
              <span className="font-semibold text-body">Location:</span> {project.address}
            </div>
          )}
          {project.applicant && (
            <div>
              <span className="font-semibold text-body">Applicant:</span> {project.applicant}
            </div>
          )}
          {project.planner_name && (
            <div>
              <span className="font-semibold text-body">Planner:</span> {project.planner_name}
            </div>
          )}
          {project.planner_email && (
            <a
              href={`mailto:${project.planner_email}`}
              className="font-semibold text-muted underline underline-offset-2 hover:text-ink"
            >
              {project.planner_email}
            </a>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[880px]">
      <p className="mb-6 text-[13px] text-muted">
        A maintained knowledge base built from council meetings and official
        records — updated as new meetings land.
        {wiki.pushed_at && ` Last synced ${formatDate(wiki.pushed_at.slice(0, 10))}.`}
      </p>

      <nav className="mb-8 flex flex-wrap gap-2">
        {pages.map((p) => (
          <a
            key={p.page}
            href={`#${p.page}`}
            className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-semibold text-body hover:bg-strong"
          >
            {WIKI_PAGE_LABELS[p.page] ?? p.title}
          </a>
        ))}
      </nav>

      {pages.map((p) => (
        <section
          key={p.page}
          id={p.page}
          className="mb-6 scroll-mt-6 rounded-2xl border border-hairline bg-canvas p-6"
        >
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold">
              {WIKI_PAGE_LABELS[p.page] ?? p.title}
            </h2>
            {p.timestamp && (
              <span className="text-[12px] text-muted">
                through {formatDate(String(p.timestamp).slice(0, 10))}
              </span>
            )}
          </div>
          <div className="text-[14px] leading-[1.6]">
            <Markdown>
              {resolveBody(
                p.page === "overview" ? stripSection(p.body, "In this wiki") : p.body,
                metrics,
                wiki.entity_slug,
                params.slug,
                "",
                pageHrefs,
              )}
            </Markdown>
          </div>
        </section>
      ))}

      {project.has_evaluation && (
        <p className="mb-8">
          <Link
            href={`/development/${params.slug}/analysis`}
            className="rounded-full border border-ink px-3.5 py-1.5 text-sm font-semibold text-ink hover:bg-ink hover:text-canvas"
          >
            Full impact analysis →
          </Link>
        </p>
      )}

      {wiki.log && (
        <details className="mb-8 rounded-2xl border border-hairline bg-soft p-5">
          <summary className="cursor-pointer text-[14px] font-semibold">
            Page history
          </summary>
          <div className="mt-3 text-[13px] leading-[1.6]">
            <Markdown>{wiki.log}</Markdown>
          </div>
        </details>
      )}

      <p className="text-[12px] text-muted">
        Impact figures shown on this page resolve live from the current
        evaluation — wiki text never carries stale numbers.
      </p>
    </div>
  );
}
