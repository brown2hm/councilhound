"use client";

import dynamic from "next/dynamic";
import type { MapLocation } from "@/lib/api";

// Leaflet touches `window` at import time, so the real map loads client-only
const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[480px] w-full items-center justify-center rounded-3xl border border-hairline bg-soft text-sm text-muted">
      Loading map…
    </div>
  ),
});

export default function MapClient({ locations }: { locations: MapLocation[] }) {
  return <MapView locations={locations} />;
}
