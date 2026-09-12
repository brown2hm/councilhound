import { notFound } from "next/navigation";
import { ApiError, isMissingRecordStatus } from "@/lib/api";

/** Await a record fetch, turning the API's "no such record" into this
 * route's not-found.
 *
 * Call it from generateMetadata as well as the page: the document then gets
 * the not-found title (and Next's noindex) instead of the layout default, and
 * the body is never rendered for a missing record. The HTTP status itself is
 * decided earlier, in middleware.ts — see there for why a notFound() thrown
 * during render, from either place, comes too late to set it.
 *
 * Anything else (API down, 5xx) propagates to error.tsx: an outage must not
 * read as a missing record. */
export async function requireRecord<T>(fetching: Promise<T>): Promise<T> {
  try {
    return await fetching;
  } catch (err) {
    if (err instanceof ApiError && isMissingRecordStatus(err.status)) notFound();
    throw err;
  }
}
