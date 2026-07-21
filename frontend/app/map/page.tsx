import MapClient from "@/components/MapClient";
import { api } from "@/lib/api";

export const metadata = {
  title: "Around the city",
  description:
    "City of Fairfax locations and projects named in council and commission business, mapped and colored by project status.",
};

export const dynamic = "force-dynamic";

export default async function MapPage() {
  const locations = await api.mapLocations();
  return (
    <div className="mx-auto max-w-[1280px] px-8 pb-10 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Around the city</h1>
      <p className="mb-6 text-sm text-muted">
        {locations.length} locations and projects named in council and commission business.
        Pin color follows the strongest related project’s status.
      </p>
      <MapClient locations={locations} />
    </div>
  );
}
