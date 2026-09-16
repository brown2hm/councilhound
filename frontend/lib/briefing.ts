import type { VoteInfo } from "@/lib/api";

// Outcome-line parser for the briefing's decision cards. The extractor
// records a roll call for some votes and prose for most; this reads the
// prose so the front page can say "unanimous" or "4–2".

/** Unanimous or split, from the roll call when the extractor recorded one
 * and from the outcome prose ("Approved 4-2", "5:0", "unanimously") when it
 * did not — which is most council meetings. */
export function voteShape(vote: VoteInfo, outcome: string | null): { tally: string; split: boolean; unanimous: boolean } {
  const counts = Object.values(vote.vote_breakdown ?? {});
  let yes = counts.filter((v) => v === "yes").length;
  let no = counts.filter((v) => v === "no").length;
  let abstain = counts.filter((v) => v === "abstain").length;
  const text = `${outcome ?? ""} ${vote.description ?? ""}`;
  if (!yes && !no) {
    // "4-2", "5-0-1", "(6-0)", "4:0" — not dates, times, or "3-year"
    const m =
      text.match(/(?<![\w$-])(\d{1,2})\s*[-–]\s*(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?![\d-])/) ??
      text.match(/(?<![\w$-])(\d{1,2}):(\d)(?!\d)/);
    if (m) {
      yes = Number(m[1]);
      no = Number(m[2]);
      abstain = m[3] ? Number(m[3]) : 0;
    }
  }
  if (yes || no) {
    const tally = abstain ? `${yes}–${no}–${abstain}` : `${yes}–${no}`;
    return { tally, split: no > 0, unanimous: no === 0 };
  }
  if (/unanimous/i.test(text)) return { tally: "unanimous", split: false, unanimous: true };
  return { tally: "", split: false, unanimous: false };
}
