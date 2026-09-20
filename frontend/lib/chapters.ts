import type { AgendaItemInfo } from "@/lib/api";

/**
 * The chapter bar tints its segments by position among the timed items.
 * Rows elsewhere on the meeting page reuse this map, so an item's stripe is
 * the same colour as its segment in the bar above.
 */
export const SEGMENT_TINTS = ["bg-teal", "bg-ochre", "bg-mint"];

/** Colour for an item that has no index point, so no segment in the bar. */
export const UNCHAPTERED_TINT = "bg-strong";

/** Items in bar order: those with an index point inside the recording. */
export function timedItems(items: AgendaItemInfo[], durationSeconds: number | null): AgendaItemInfo[] {
  if (!durationSeconds) return [];
  const timed = items
    .filter((it) => it.start_seconds !== null && it.start_seconds < durationSeconds)
    .sort((a, b) => (a.start_seconds ?? 0) - (b.start_seconds ?? 0));
  // the bar needs two marks to divide anything; below that it doesn't render,
  // and with no bar there is nothing for a row stripe to key back to
  return timed.length < 2 ? [] : timed;
}

/** Item id → tint class, matching the bar. Empty when the bar doesn't render. */
export function chapterTints(items: AgendaItemInfo[], durationSeconds: number | null): Map<number, string> {
  const tints = new Map<number, string>();
  timedItems(items, durationSeconds).forEach((it, i) => {
    tints.set(it.id, SEGMENT_TINTS[i % SEGMENT_TINTS.length]);
  });
  return tints;
}
