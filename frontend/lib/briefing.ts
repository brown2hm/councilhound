import type { VoteInfo } from "@/lib/api";

// Outcome-line parsers for the briefing's decision cards. The extractor
// records a roll call for some votes and prose for most; these read the
// prose so the front page can say "unanimous" or "4–2" and lead each card
// with the one quantity the decision turns on.

/** The one concrete quantity a decision turns on: a dollar figure, a
 * headcount, an acreage. Pulled from the outcome line so the card can lead
 * with it instead of burying it in muted prose. */
export interface Figure {
  value: string;
  label: string;
}

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

const NUM_WORDS: Record<string, number> = {
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17,
  eighteen: 18, nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60,
  seventy: 70, eighty: 80, ninety: 90, hundred: 100,
};
// what a council decision is usually sized in, most telling first
const UNITS = [
  "children", "dwelling units", "residential units", "units", "homes", "townhomes", "townhouses",
  "apartments", "condominiums", "acres", "square feet", "stories", "parking spaces", "spaces",
  "rooms", "lots", "trees", "employees", "positions", "appointments", "reappointments",
  "members", "seats", "years", "months", "conditions",
];
const UNIT_RE = new RegExp(
  `\\b(up to|approximately|about|nearly|over|more than)?\\s*(\\d{1,3}(?:,\\d{3})*|${Object.keys(NUM_WORDS).join("|")})[- ](${UNITS.join("|")})\\b`,
  "i",
);
const MONEY_NOUNS = ["contract", "grant", "budget", "appropriation", "bond", "loan", "lease", "purchase", "fee", "transfer", "award"];
const QUALIFIER: Record<string, string> = { "up to": "≤", approximately: "≈", about: "≈", nearly: "≈", over: ">", "more than": ">" };

export function figure(text: string): Figure | null {
  const money = text.match(/\$\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(million|billion)?/i);
  if (money) {
    const value = "$" + money[1] + (money[2] ? (/^m/i.test(money[2]) ? "M" : "B") : "");
    // what the money is: most specific noun first, wherever it sits in the sentence
    const label =
      MONEY_NOUNS.find((k) => new RegExp(`\\b${k}\\b`, "i").test(text)) ?? "amount";
    return { value, label };
  }
  const m = text.match(UNIT_RE);
  if (!m) return null;
  const n = NUM_WORDS[m[2].toLowerCase()] ?? m[2];
  const q = m[1] ? QUALIFIER[m[1].toLowerCase()] ?? "" : "";
  return { value: `${q}${n}`, label: m[3].toLowerCase() };
}
