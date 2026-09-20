import type { WikiTrust } from "@/lib/api";

// The OKF v0.2 trust and lifecycle signals for one wiki page, read from the
// API's `trust` block (api/app/wiki.py derives it from the page frontmatter):
// who produced the prose, whether a person has confirmed it, and whether a
// scheduled meeting has passed since the pipeline last ran. Tints follow
// VotePills — mint for confirmed, ochre for "look again" — so the same
// colors mean the same thing across the site.

const PILL = "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold leading-none";

const PRODUCER: Record<string, { label: string; hint: string }> = {
  pipeline: {
    label: "From the record",
    hint: "Rendered directly from the meeting record and official documents.",
  },
  curator: {
    label: "AI-curated",
    hint: "Prose maintained by the wiki curator model from the meeting record.",
  },
  human: {
    label: "Hand-written",
    hint: "Written by a person.",
  },
};

/** A meeting instant in city-local time, so a 7:30 pm meeting is dated the
 * evening it happens rather than the UTC day after. */
function fmtInstant(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}

export default function WikiTrustBadges({ trust }: { trust: WikiTrust | null | undefined }) {
  if (!trust) return null;
  const producer = trust.producer_kind ? PRODUCER[trust.producer_kind] : null;
  const reviewed = trust.tier === "human-reviewed" && trust.verified_at;

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {producer && (
        <span className={`${PILL} bg-card text-body`} title={trust.producer ?? producer.hint}>
          {producer.label}
        </span>
      )}
      {reviewed ? (
        trust.edited_since_review ? (
          <span
            className={`${PILL} bg-tint-ochre text-tint-ochre-text`}
            title={`Reviewed by ${trust.verified_by}; the page has changed since.`}
          >
            Reviewed {fmtInstant(trust.verified_at!)} · edited since
          </span>
        ) : (
          <span
            className={`${PILL} bg-tint-mint text-tint-mint-text`}
            title={`Confirmed against the record by ${trust.verified_by}.`}
          >
            ✓ Reviewed {fmtInstant(trust.verified_at!)}
          </span>
        )
      ) : (
        <span
          className={`${PILL} bg-card text-muted-soft`}
          title="No person has signed off on this page yet."
        >
          Not yet reviewed
        </span>
      )}
      {trust.stale && trust.stale_after && (
        <span
          className={`${PILL} bg-tint-ochre text-tint-ochre-text`}
          title="A scheduled meeting has passed since this page was last updated; it may not reflect what happened there."
        >
          May have changed at the {fmtInstant(trust.stale_after)} meeting
        </span>
      )}
    </span>
  );
}
