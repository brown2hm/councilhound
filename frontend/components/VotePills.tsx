import type { VoteInfo } from "@/lib/api";

// Glyph + tint per vote so the outcome survives color-blindness and grayscale.
const PILL: Record<string, { cls: string; glyph: string }> = {
  yes: { cls: "bg-tint-mint text-tint-mint-text", glyph: "✓" },
  no: { cls: "bg-tint-coral text-tint-coral-text", glyph: "✕" },
  abstain: { cls: "bg-tint-ochre text-tint-ochre-text", glyph: "–" },
  absent: { cls: "bg-card text-muted-soft", glyph: "·" },
};

const RESULT_CLS: Record<string, string> = {
  passed: "text-tint-mint-text",
  failed: "text-tint-coral-text",
};

export function VotePills({ breakdown }: { breakdown: Record<string, string> }) {
  const entries = Object.entries(breakdown ?? {});
  if (entries.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {entries.map(([member, vote]) => {
        const pill = PILL[vote] ?? { cls: "bg-card text-body", glyph: "" };
        return (
          <span
            key={member}
            title={`${member}: ${vote}`}
            className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold leading-none ${pill.cls}`}
          >
            {pill.glyph} {member}
          </span>
        );
      })}
    </div>
  );
}

export default function VoteBlock({ vote }: { vote: VoteInfo }) {
  return (
    <div className="mt-2 rounded-xl bg-soft p-3 px-3.5 text-sm">
      <span
        className={`mr-2 font-semibold ${RESULT_CLS[vote.motion_result ?? ""] ?? "text-tint-ochre-text"}`}
      >
        {vote.motion_result}
      </span>
      {vote.description}
      <VotePills breakdown={vote.vote_breakdown} />
    </div>
  );
}
