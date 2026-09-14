import MapClient from "@/components/MapClient";
import { api } from "@/lib/api";

export const metadata = {
  title: "Around the city",
  description:
    "City of Fairfax locations and projects named in council and commission business, mapped and colored by project status, with a lookup for what's near any address.",
};

export const dynamic = "force-dynamic";

export default async function MapPage({ searchParams }: { searchParams: { focus?: string } }) {
  const locations = await api.mapLocations();
  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-8 sm:px-8">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <h1 className="text-[32px] font-medium tracking-[-0.5px]">Around the city</h1>
          <p className="mt-1 max-w-[70ch] text-sm text-muted">
            {locations.length} places and projects named in council and commission business. Pin color follows the
            project&apos;s status; open decisions are the loud ones.
          </p>
        </div>
        <form
          action="/nearby"
          method="get"
          className="flex w-full items-center gap-2 rounded-xl border border-ink bg-white p-1 pl-3.5 sm:w-[420px]"
        >
          <input
            name="q"
            placeholder="What's near an address? e.g. 10455 Armstrong St"
            aria-label="What's near an address?"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-muted-soft"
          />
          <button className="shrink-0 rounded-lg bg-ink px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-ink-active">
            Look up
          </button>
        </form>
      </div>
      <MapClient locations={locations} focus={searchParams.focus} />
    </div>
  );
}
