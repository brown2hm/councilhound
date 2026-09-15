import Link from "next/link";
import { GLOSSARY } from "@/lib/glossary";

export const metadata = {
  title: "Glossary",
  description:
    "Plain-language definitions of the terms that show up in City of Fairfax council, commission, and board agendas.",
};

export default function GlossaryPage() {
  const entries = [...GLOSSARY].sort((a, b) => a.term.localeCompare(b.term));
  return (
    <div className="mx-auto max-w-[860px] px-4 pb-16 pt-8 sm:px-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Glossary</h1>
      <p className="mb-6 text-sm text-muted">
        What the words on an agenda actually mean. Terms in agenda items and summaries across
        the site carry these definitions on hover.
      </p>
      <nav className="mb-8 flex flex-wrap gap-2">
        {entries.map((e) => (
          <a
            key={e.slug}
            href={`#${e.slug}`}
            className="rounded-full border border-hairline bg-canvas px-3 py-1 text-[13px] font-medium text-muted hover:text-ink"
          >
            {e.term}
          </a>
        ))}
      </nav>
      <dl className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
        {entries.map((e) => (
          <div key={e.slug} id={e.slug} className="scroll-mt-24 px-5 py-4">
            <dt className="flex flex-wrap items-baseline gap-2">
              <span className="text-[15px] font-semibold">{e.term}</span>
              {e.aliases && e.aliases.length > 0 && (
                <span className="text-[12px] text-muted-soft">
                  also: {e.aliases.join(", ")}
                </span>
              )}
            </dt>
            <dd className="mt-1 text-sm leading-[1.6] text-body">{e.definition}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-6 text-[13px] text-muted">
        Missing a term you hit in the record?{" "}
        <Link href="/ask" className="font-semibold underline underline-offset-2 hover:text-ink">
          Ask the hound
        </Link>{" "}
        and it will explain it from the meetings themselves.
      </p>
    </div>
  );
}
