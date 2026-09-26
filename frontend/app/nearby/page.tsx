import Link from "next/link";
import { redirect } from "next/navigation";
import FollowButton from "@/components/FollowButton";
import MapClient from "@/components/MapClient";
import StatusBadge from "@/components/StatusBadge";
import UseMyLocation from "@/components/UseMyLocation";
import { api, formatDate, type GeocodeHit, type MapLocation, type NearbyResult } from "@/lib/api";
import { getJurisdiction, type Jurisdiction } from "@/lib/jurisdiction";

export async function generateMetadata() {
  const j = await getJurisdiction();
  return {
    title: "Near me",
    description: `What ${j.identity.short_name}'s public bodies are deciding near an address: projects and named places nearby, nearest first.`,
  };
}

export const dynamic = "force-dynamic";

/** The radius chips, from the jurisdiction's nearby_radii_m (a walkable
 * city offers ½/1/2 miles; a county, 1/2/5). */
function radiiFor(j: Jurisdiction): { m: number; label: string }[] {
  return j.display.nearby_radii_m.map((m) => {
    const mi = m / 1609.344;
    const label = Math.abs(mi - 0.5) < 0.06 ? "½ mile" : `${Math.round(mi * 10) / 10} mile${Math.round(mi * 10) / 10 === 1 ? "" : "s"}`;
    return { m, label };
  });
}

function fmtDistance(m: number): string {
  const miles = m / 1609.344;
  if (m < 300) return `${Math.round(m / 10) * 10} m`;
  return `${miles < 1 ? miles.toFixed(2) : miles.toFixed(1)} mi`;
}

function toMapLocation(r: NearbyResult): MapLocation {
  return {
    slug: r.slug ?? `official-${r.official?.slug}`,
    name: r.name,
    entity_type: r.entity_type,
    is_official_project: r.official !== null,
    lat: r.lat,
    lng: r.lng,
    matched_address: null,
    address: r.address,
    current_status: r.current_status,
    official_status: r.official?.official_status ?? null,
    summary: r.summary,
    status_hint: r.current_status,
    related: [],
  };
}

export default async function NearbyPage({
  searchParams,
}: {
  searchParams: { q?: string; lat?: string; lng?: string; r?: string };
}) {
  const j = await getJurisdiction();
  const RADII = radiiFor(j);
  const q = (searchParams.q ?? "").trim();
  const radius = RADII.some((r) => String(r.m) === searchParams.r) ? Number(searchParams.r) : RADII[1]?.m ?? RADII[0].m;
  const lat = Number(searchParams.lat);
  const lng = Number(searchParams.lng);
  const haveCoords = Number.isFinite(lat) && Number.isFinite(lng) && searchParams.lat !== undefined;
  let geocodeError: string | null = null;

  if (!haveCoords && q) {
    let hit: GeocodeHit | null = null;
    try {
      hit = await api.geocode(q);
    } catch (e) {
      geocodeError =
        e instanceof Error && e.message.endsWith("404")
          ? `No street address matched that. Try a house number and street, like “${j.display.example_address}”.`
          : "The address lookup is unavailable right now. Try again in a minute, or use your location.";
    }
    if (hit) {
      const sp = new URLSearchParams({
        lat: hit.lat.toFixed(5),
        lng: hit.lng.toFixed(5),
        r: String(radius),
        q: hit.matched_address ?? q,
      });
      redirect(`/nearby?${sp.toString()}`);
    }
  }

  const nearby = haveCoords ? await api.near(lat, lng, radius).catch(() => null) : null;
  const results = nearby?.results ?? [];
  const label = q && q !== "my location" ? `within ${RADII.find((r) => r.m === radius)?.label} of ${q}` : `within ${RADII.find((r) => r.m === radius)?.label} of this spot`;

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-8 sm:px-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Near me</h1>
      <p className="mb-5 max-w-[720px] text-sm text-muted">
        Projects and named places {j.identity.short_name}&apos;s public bodies have taken up near an
        address, nearest first. Addresses are looked up and forgotten; nothing is stored.
      </p>

      <form method="get" action="/nearby" className="mb-3 flex flex-wrap items-center gap-2">
        <input type="hidden" name="r" value={radius} />
        <input
          name="q"
          defaultValue={q === "my location" ? "" : q}
          placeholder={`A street address in the ${j.identity.noun}, e.g. ${j.display.example_address}`}
          aria-label="Street address"
          className="min-w-0 flex-1 rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-[15px] outline-none placeholder:text-muted-soft focus:border-ink sm:min-w-[320px] sm:flex-none sm:basis-[420px]"
        />
        <button className="rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active">
          Look up
        </button>
        <UseMyLocation radius={radius} />
      </form>
      {geocodeError && <p className="mb-4 text-sm text-tint-coral-text">{geocodeError}</p>}

      {haveCoords && (
        <div className="mb-5 flex flex-wrap items-center gap-2 text-[13px] text-muted">
          <span>Within</span>
          {RADII.map((r) => {
            const sp = new URLSearchParams({ lat: String(lat), lng: String(lng), r: String(r.m) });
            if (q) sp.set("q", q);
            return (
              <Link
                key={r.m}
                href={`/nearby?${sp.toString()}`}
                className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium ${
                  r.m === radius ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
                }`}
              >
                {r.label}
              </Link>
            );
          })}
          <span>of {q && q !== "my location" ? q : "your location"}</span>
          <FollowButton
            target={{ kind: "area", lat, lng, radiusM: radius, label }}
            label="Follow this area"
            size="sm"
            className="sm:ml-auto"
          />
        </div>
      )}

      {!haveCoords && !geocodeError && (
        <p className="rounded-2xl border border-dashed border-hairline p-6 text-sm text-muted">
          Enter an address or share your location to see what&apos;s being decided nearby. Or browse{" "}
          <Link href="/map" className="font-semibold underline underline-offset-2">
            the whole {j.identity.noun} on the map
          </Link>
          .
        </p>
      )}

      {haveCoords && nearby === null && (
        <p className="rounded-2xl border border-dashed border-hairline p-6 text-sm text-muted">
          Couldn&apos;t load nearby topics right now. Try again in a minute.
        </p>
      )}

      {nearby && (
        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          <div>
            <p className="mb-3 text-[13px] text-muted">
              {results.length} {results.length === 1 ? "topic" : "topics"} {label}.
            </p>
            <ul className="divide-y divide-hairline-soft rounded-2xl border border-hairline bg-canvas">
              {results.map((r) => {
                const href = r.slug ? `/topics/${r.slug}` : `/development/${r.official?.slug}`;
                return (
                  <li key={`${r.slug}-${r.official?.slug}`} className="flex gap-4 px-5 py-3.5">
                    {r.official?.image_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={r.official.image_url}
                        alt=""
                        loading="lazy"
                        className="hidden h-[64px] w-[92px] shrink-0 rounded-xl border border-hairline object-cover sm:block"
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 flex flex-wrap items-center gap-2">
                        <span className="w-14 shrink-0 text-[13px] font-semibold text-muted">
                          {fmtDistance(r.distance_m)}
                        </span>
                        <Link href={href} className="text-[15px] font-semibold underline-offset-2 hover:underline">
                          {r.name}
                        </Link>
                        <StatusBadge status={r.current_status} />
                        {r.official?.official_status && (
                          <span className="rounded-full bg-strong px-2.5 py-[3px] text-xs font-semibold text-body">
                            {r.official.official_status}
                          </span>
                        )}
                      </div>
                      <div className="pl-16 text-[13px] text-muted">
                        {r.address ?? r.entity_type.replace("_", " ")}
                        {r.update_count > 0 && ` · ${r.update_count} update${r.update_count === 1 ? "" : "s"}`}
                        {r.last_seen && ` · last ${formatDate(r.last_seen)}`}
                      </div>
                      {r.summary && (
                        <p className="mt-1 pl-16 text-sm leading-[1.5] text-body">
                          {r.summary.length > 180 ? `${r.summary.slice(0, 177)}…` : r.summary}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
              {results.length === 0 && (
                <li className="px-5 py-6 text-sm text-muted">
                  Nothing on the record within this distance. Widen the radius, or{" "}
                  <Link href="/topics" className="font-semibold underline underline-offset-2">
                    browse everything
                  </Link>
                  .
                </li>
              )}
            </ul>
          </div>
          <div className="lg:sticky lg:top-20 lg:self-start">
            {results.length > 0 && (
              <MapClient locations={results.map(toMapLocation)} compact center={[lat, lng]} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
