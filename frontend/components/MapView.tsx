"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import Link from "next/link";
import { MapContainer, Marker, Popup, TileLayer, Tooltip } from "react-leaflet";
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

type MarkerKind = "official" | "project" | "mention";

function pinIcon(status: string | null, kind: MarkerKind) {
  const color = PIN_COLORS[status ?? ""] ?? "#1a3a3a";
  const size = kind === "official" ? 16 : kind === "project" ? 14 : 11;
  return L.divIcon({
    className: "",
    html: `<span class="map-pin-dot map-pin-dot--${kind}" style="background:${color}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function MapHoverCard({
  location,
  classification,
}: {
  location: MapLocation;
  classification: string;
}) {
  const status = location.current_status ?? location.official_status;
  return (
    <div className="w-[270px] text-left text-sm">
      <div className="flex items-start justify-between gap-2">
        <strong className="min-w-0 text-[13px] leading-tight text-ink">{location.name}</strong>
        <StatusBadge status={status} />
      </div>
      <div className="mt-1 text-[11px] font-medium uppercase text-muted">
        {classification}
      </div>
      {location.address && (
        <div className="mt-2 text-xs leading-snug text-muted">{location.address}</div>
      )}
      {location.summary && (
        <p className="map-hover-summary mt-2 text-xs leading-[1.45] text-body">
          {location.summary}
        </p>
      )}
      {location.related.length > 0 && (
        <div className="mt-2 border-t border-hairline pt-2">
          <div className="mb-1 text-[10px] font-medium uppercase text-muted">Discussed alongside</div>
          <ul className="space-y-1">
            {location.related.slice(0, 2).map((related) => (
              <li key={related.slug} className="flex items-center justify-between gap-2 text-xs text-body">
                <span className="min-w-0 truncate">{related.name}</span>
                <StatusBadge status={related.current_status} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
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
      {locations.map((loc) => {
        const isProject = loc.entity_type === "project";
        const markerKind: MarkerKind = loc.is_official_project
          ? "official"
          : isProject
            ? "project"
            : "mention";
        const classification = loc.is_official_project
          ? "Official city record"
          : isProject
            ? "Tracked project"
            : "Mentioned location";
        return (
          <Marker
            key={loc.slug}
            position={[loc.lat, loc.lng]}
            icon={pinIcon(loc.status_hint, markerKind)}
            title={loc.name}
            alt={`${classification}: ${loc.name}`}
            riseOnHover
          >
            <Tooltip
              direction="auto"
              offset={[12, 0]}
              opacity={1}
              className="map-marker-preview"
            >
              <MapHoverCard location={loc} classification={classification} />
            </Tooltip>
            <Popup>
              <div className="min-w-[210px] text-sm">
                <Link href={`/topics/${loc.slug}`} className="font-semibold underline underline-offset-2">
                  {loc.name}
                </Link>
                <div className="mt-1 text-xs text-muted">
                  {classification}
                </div>
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
        );
      })}
    </MapContainer>
  );
}
