import { NextResponse, type NextRequest } from "next/server";
import { API_URL, isMissingRecordStatus } from "@/lib/api";

/** Decide "no such record" before the response starts.
 *
 * Every detail route renders under a loading.tsx, so its body streams inside
 * a Suspense boundary: by the time the page throws notFound() the document
 * shell has gone out with a 200, and Next 14 can only add a noindex meta.
 * (Throwing from generateMetadata doesn't help — 14.2 rethrows metadata
 * errors inside the leaf segment, behind the same boundary.) The only place
 * the status is still decidable is here, so for full-document requests of a
 * detail route we ask the API whether the record exists and, if not, rewrite
 * to the not-found page, which Next serves with a real 404.
 *
 * Only document loads are checked. Client-side navigations and link
 * prefetches don't need a status code (the page's own notFound() renders the
 * right UI there), and prefetching every visible link on a directory page
 * would otherwise cost one API call each. Next strips its RSC headers before
 * middleware runs, so those requests are recognised by the browser's own
 * Sec-Fetch-Mode instead; a client that doesn't send it (curl, crawlers) is
 * treated as a document load. Anything but a definite "missing" answer from
 * the API — an outage, a timeout, a 5xx — falls through to the normal render
 * so a wobble never turns into a 404. */

// Which API record each detail route renders. Keep in step with the routes'
// own fetches; a route left out still shows the not-found page, just with the
// streamed 200. The slug group is left percent-encoded, as the API expects.
const RECORD_ROUTES: { route: RegExp; record: (slug: string) => string }[] = [
  { route: /^\/members\/([^/]+)$/, record: (slug) => `/members/${slug}` },
  { route: /^\/meetings\/upcoming\/([^/]+)$/, record: (id) => `/meetings/upcoming/${id}` },
  { route: /^\/meetings\/((?!upcoming$)[^/]+)$/, record: (id) => `/meetings/${id}` },
  { route: /^\/meetings\/([^/]+)\/transcript$/, record: (id) => `/meetings/${id}/transcript` },
  { route: /^\/topics\/([^/]+)$/, record: (slug) => `/entities/${slug}` },
  { route: /^\/topics\/([^/]+)\/wiki$/, record: (slug) => `/entities/${slug}/wiki` },
  // /development/methods is a page of its own; the tabs all hang off the project
  {
    route: /^\/development\/((?!methods$)[^/]+)(?:\/(?:analysis|documents|wiki|methods))?$/,
    record: (slug) => `/development/${slug}`,
  },
];

const CHECK_TIMEOUT_MS = 3000;

export async function middleware(req: NextRequest) {
  // fetch() from the router reports "cors" (or "same-origin"); a navigation
  // reports "navigate" (a framed one "nested-navigate")
  const fetchMode = req.headers.get("sec-fetch-mode");
  if (fetchMode && !fetchMode.endsWith("navigate")) return NextResponse.next();

  const { pathname } = req.nextUrl;
  let recordPath: string | null = null;
  for (const { route, record } of RECORD_ROUTES) {
    const m = pathname.match(route);
    if (m) {
      recordPath = record(m[1]);
      break;
    }
  }
  if (!recordPath) return NextResponse.next();

  let status: number;
  try {
    const resp = await fetch(`${API_URL}${recordPath}`, {
      method: "HEAD",
      cache: "no-store",
      signal: AbortSignal.timeout(CHECK_TIMEOUT_MS),
    });
    status = resp.status;
  } catch {
    return NextResponse.next();
  }
  if (!isMissingRecordStatus(status)) return NextResponse.next();

  // a path no route claims: Next renders app/not-found.tsx with a 404 status
  // while the address bar keeps the URL the visitor asked for
  return NextResponse.rewrite(new URL("/_not-found", req.url));
}

export const config = {
  matcher: ["/members/:path+", "/meetings/:path+", "/topics/:path+", "/development/:path+"],
};
