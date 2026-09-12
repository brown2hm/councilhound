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

export default function MapClient({
  locations,
  focus,
  compact = false,
  center,
}: {
  locations: MapLocation[];
  /** slug to open and center on when the map loads (e.g. ?focus= links) */
  focus?: string;
  /** a smaller, pane-less map for sidebars: clicking a pin navigates */
  compact?: boolean;
  /** override the auto-center (the searched point on /nearby) */
  center?: [number, number];
}) {
  return <MapView locations={locations} focus={focus} compact={compact} center={center} />;
}
