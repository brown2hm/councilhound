"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
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

function pinIcon(status: string | null, kind: MarkerKind, selected: boolean) {
  const color = PIN_COLORS[status ?? ""] ?? "#1a3a3a";
  const base = kind === "official" ? 16 : kind === "project" ? 14 : 11;
  const size = selected ? base + 4 : base;
  const cls = `map-pin-dot map-pin-dot--${kind}${selected ? " map-pin-dot--selected" : ""}`;
  return L.divIcon({
    className: "",
    html: `<span class="${cls}" style="background:${color}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function classify(loc: MapLocation): { kind: MarkerKind; label: string } {
  if (loc.is_official_project) return { kind: "official", label: "Official city record" };
  if (loc.entity_type === "project") return { kind: "project", label: "Tracked project" };
  return { kind: "mention", label: "Mentioned location" };
}

// Clears the selection when the user clicks empty map (Leaflet fires the map's
// own click only for the background, not for marker clicks).
function DeselectOnMapClick({ onDeselect }: { onDeselect: () => void }) {
  useMapEvents({ click: onDeselect });
  return null;
}

function DetailPane({
  location,
  onClose,
}: {
  location: MapLocation | null;
  onClose: () => void;
}) {
  if (!location) {
    return (
      <div className="hidden h-full flex-col items-center justify-center rounded-3xl border border-dashed border-hairline bg-soft px-6 text-center lg:flex">
        <p className="text-sm text-muted">
          Hover a pin for its name, then click to see the full record here.
        </p>
      </div>
    );
  }
  const { label } = classify(location);
  const status = location.current_status ?? location.official_status;
  const address = location.address ?? location.matched_address;
  return (
    <div className="flex h-full flex-col rounded-3xl border border-hairline bg-canvas">
      <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
        <div className="min-w-0">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">
            {label}
          </div>
          <h2 className="text-lg font-medium leading-tight tracking-[-0.3px] text-ink">
            {location.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="-mr-1 shrink-0 rounded-full px-2 py-1 text-lg leading-none text-muted transition hover:bg-soft hover:text-ink"
        >
          ×
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {status && (
          <div>
            <StatusBadge status={status} />
          </div>
        )}
        {address && (
          <div className="text-sm leading-snug text-body">{address}</div>
        )}
        {location.summary && (
          <p className="text-sm leading-relaxed text-body">{location.summary}</p>
        )}
        {location.related.length > 0 && (
          <div className="border-t border-hairline pt-4">
            <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">
              Discussed alongside
            </div>
            <ul className="space-y-2">
              {location.related.map((related) => (
                <li key={related.slug} className="flex items-center justify-between gap-2">
                  <Link
                    href={`/topics/${related.slug}`}
                    className="min-w-0 truncate text-sm text-body underline decoration-hairline underline-offset-2 hover:decoration-ink"
                  >
                    {related.name}
                  </Link>
                  <StatusBadge status={related.current_status} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="border-t border-hairline px-5 py-4">
        <Link
          href={`/topics/${location.slug}`}
          className="text-sm font-medium text-ink underline underline-offset-2"
        >
          View full topic →
        </Link>
      </div>
    </div>
  );
}

export default function MapView({ locations }: { locations: MapLocation[] }) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const selected = locations.find((l) => l.slug === selectedSlug) ?? null;
  const paneRef = useRef<HTMLElement>(null);

  // On narrow screens the pane stacks below the tall map, so a tap on a pin
  // would otherwise scroll nothing into view — bring the pane up to it.
  useEffect(() => {
    if (
      selectedSlug &&
      paneRef.current &&
      window.matchMedia("(max-width: 1023px)").matches
    ) {
      paneRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selectedSlug]);

  const center: [number, number] =
    locations.length > 0
      ? [
          locations.reduce((s, l) => s + l.lat, 0) / locations.length,
          locations.reduce((s, l) => s + l.lng, 0) / locations.length,
        ]
      : [38.8462, -77.3064]; // City of Fairfax

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <div className="min-w-0 flex-1">
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
          <DeselectOnMapClick onDeselect={() => setSelectedSlug(null)} />
          {locations.map((loc) => {
            const { kind, label } = classify(loc);
            const isSelected = loc.slug === selectedSlug;
            return (
              <Marker
                key={loc.slug}
                position={[loc.lat, loc.lng]}
                icon={pinIcon(loc.status_hint, kind, isSelected)}
                title={loc.name}
                alt={`${label}: ${loc.name}`}
                riseOnHover
                zIndexOffset={isSelected ? 1000 : 0}
                eventHandlers={{ click: () => setSelectedSlug(loc.slug) }}
              >
                <Tooltip direction="top" offset={[0, -8]} opacity={1} className="map-marker-label">
                  {loc.name}
                </Tooltip>
              </Marker>
            );
          })}
        </MapContainer>
      </div>

      <aside
        ref={paneRef}
        className="scroll-mt-4 lg:h-[calc(100vh-64px-140px)] lg:min-h-[480px] lg:w-[360px] lg:shrink-0"
      >
        <DetailPane location={selected} onClose={() => setSelectedSlug(null)} />
      </aside>
    </div>
  );
}
