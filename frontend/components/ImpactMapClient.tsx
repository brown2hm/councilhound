"use client";

import dynamic from "next/dynamic";

// Leaflet touches `window` at import time, so the real map loads client-only
const ImpactMap = dynamic(() => import("@/components/ImpactMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] w-full items-center justify-center rounded-2xl border border-hairline bg-soft text-sm text-muted">
      Loading map…
    </div>
  ),
});

export default function ImpactMapClient({
  layers,
}: {
  layers: Record<string, GeoJSON.FeatureCollection>;
}) {
  return <ImpactMap layers={layers} />;
}
