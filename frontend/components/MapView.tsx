"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import Link from "next/link";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import StatusBadge from "@/components/StatusBadge";
import type { MapLocation } from "@/lib/api";

// status → pin color (design tokens); divIcons avoid Leaflet's bundled
// image assets, which break under Next bundling
const PIN_COLORS: Record<string, string> = {
  approved: "#14453a",
  completed: "#14453a",
  in_progress: "#e8b94a",
  proposed: "#7c5cd4",
  denied: "#c2402a",
  deferred: "#6a6a6a",
  withdrawn: "#6a6a6a",
};

function pinIcon(status: string | null) {
  const color = PIN_COLORS[status ?? ""] ?? "#1a3a3a";
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;border-radius:9999px;background:${color};border:2.5px solid #fffaf0;box-shadow:0 1px 4px rgba(0,0,0,.35)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

export default function MapView({ locations }: { locations: MapLocation[] }) {
  const center: [number, number] =
    locations.length > 0
      ? [
          locations.reduce((s, l) => s + l.lat, 0) / locations.length,
          locations.reduce((s, l) => s + l.lng, 0) / locations.length,
        ]
      : [38.8462, -77.3064]; // City of Fairfax

  return (
    <MapContainer
      center={center}
      zoom={14}
      scrollWheelZoom
      className="h-[calc(100vh-64px-140px)] min-h-[480px] w-full rounded-3xl border border-hairline"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {locations.map((loc) => (
        <Marker key={loc.slug} position={[loc.lat, loc.lng]} icon={pinIcon(loc.status_hint)}>
          <Popup>
            <div className="min-w-[210px] text-sm">
              <Link href={`/topics/${loc.slug}`} className="font-semibold underline underline-offset-2">
                {loc.name}
              </Link>
              {loc.related.length > 0 && (
                <ul className="mt-2 space-y-1.5">
                  {loc.related.map((r) => (
                    <li key={r.slug} className="flex items-center gap-1.5">
                      <Link href={`/topics/${r.slug}`} className="underline underline-offset-2">
                        {r.name}
                      </Link>
                      <StatusBadge status={r.current_status} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
