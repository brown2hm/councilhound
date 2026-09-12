import Link from "next/link";
import MapClient from "@/components/MapClient";
import { api } from "@/lib/api";

export const metadata = {
  title: "Around the city",
  description:
    "City of Fairfax locations and projects named in council and commission business, mapped and colored by project status.",
};

export const dynamic = "force-dynamic";

export default async function MapPage({ searchParams }: { searchParams: { focus?: string } }) {
  const locations = await api.mapLocations();
  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-8 sm:px-8">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] font-medium tracking-[-0.5px]">Around the city</h1>
        <Link
          href="/nearby"
          className="rounded-full border border-hairline px-4 py-2 text-sm font-semibold text-muted hover:text-ink"
        >
          📍 What&apos;s near an address?
        </Link>
      </div>
      <p className="mb-4 text-sm text-muted">
        {locations.length} locations and projects named in council and commission business.
        Pin color follows the strongest related project’s status; filter by kind or status above the map.
      </p>
      <MapClient locations={locations} focus={searchParams.focus} />
    </div>
  );
}
