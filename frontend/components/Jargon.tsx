import Link from "next/link";
import { glossaryFor } from "@/lib/glossary";
import { jurisdiction } from "@/lib/jurisdiction";

/**
 * Wraps the first occurrence of each glossary term in a text with a hover
 * definition and a link to /glossary. One wrap per term per block keeps
 * agenda descriptions from turning into a field of dotted underlines.
 * Server-safe: no client JS, the tooltip is CSS.
 */
export default function Jargon({ children }: { children: string }) {
  const text = children;
  if (!text) return null;
  const { regex: GLOSSARY_RE, lookupTerm } = glossaryFor(jurisdiction());
  const out: React.ReactNode[] = [];
  const used = new Set<string>();
  let last = 0;
  let n = 0;
  for (const m of Array.from(text.matchAll(GLOSSARY_RE))) {
    const entry = lookupTerm(m[0]);
    if (!entry || used.has(entry.slug)) continue;
    used.add(entry.slug);
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push(
      <span key={n++} className="group/jargon relative inline">
        <Link
          href={`/glossary#${entry.slug}`}
          className="cursor-help underline decoration-muted-soft decoration-dotted underline-offset-[3px] hover:decoration-ink"
          aria-describedby={`jargon-${entry.slug}-${n}`}
        >
          {m[0]}
        </Link>
        <span
          role="tooltip"
          id={`jargon-${entry.slug}-${n}`}
          className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-[280px] rounded-xl border border-hairline bg-canvas p-3 text-left text-[13px] font-normal normal-case leading-[1.5] tracking-normal text-body shadow-lg group-hover/jargon:block group-focus-within/jargon:block"
        >
          <span className="mb-0.5 block font-semibold text-ink">{entry.term}</span>
          {entry.definition}
        </span>
      </span>,
    );
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}
