/** Motion descriptions and item titles arrive as filed ("Motion to approve…",
 * "Consideration of an ordinance amending…"). Drop the opener and clip at a
 * word so the text reads as a subject. */
export function subjectOf(text: string | null | undefined, max = 72): string {
  if (!text) return "";
  let t = text
    .replace(
      /^(motion to |approval of |approve |consideration (of|and appropriation of|for) |adopt(ion of)? |introduction of |public hearing and council action (on|–|-) ?)(an? |the )?/i,
      "",
    )
    .trim();
  if (t) t = t.charAt(0).toUpperCase() + t.slice(1);
  if (t.length <= max) return t;
  let cut = t.slice(0, max).replace(/\s+\S*$/, "");
  // never end inside a parenthetical, or on a joining word
  const open = cut.lastIndexOf("(");
  if (open > 0 && !cut.slice(open).includes(")")) cut = cut.slice(0, open);
  cut = cut.replace(/\s+(and|or|of|the|to|for|a|an|in|on|at|by|with)$/i, "");
  return cut.replace(/[\s,;:(–-]+$/, "") + "…";
}

/** "Passed 4–3", "Failed 3–3", "Passed, unanimous", from the body's tally. */
export function resultLine(tally: Record<string, number>, result: string | null): string {
  const yes = tally.yes ?? 0;
  const no = tally.no ?? 0;
  const word =
    result === "passed" ? "Passed" : result === "failed" ? "Failed" : result ? result.charAt(0).toUpperCase() + result.slice(1) : "Recorded";
  if (yes + no === 0) return word;
  return no === 0 ? `${word}, unanimous` : `${word} ${yes}–${no}`;
}
