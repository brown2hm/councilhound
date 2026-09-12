"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Marker, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
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

const STATUS_FILTERS = ["proposed", "in_progress", "approved", "denied", "deferred", "completed"];
const KIND_FILTERS: { key: MarkerKind; label: string }[] = [
  { key: "official", label: "Official projects" },
  { key: "project", label: "Tracked projects" },
  { key: "mention", label: "Mentioned places" },
];

// Pans to a slug once when it changes; a hook so it can live inside the map
function FlyTo({ target }: { target: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.setView(target, 16, { animate: false });
  }, [map, target]);
  return null;
}

export default function MapView({
  locations,
  focus,
  compact = false,
  center: centerOverride,
}: {
  locations: MapLocation[];
  focus?: string;
  compact?: boolean;
  center?: [number, number];
}) {
  const router = useRouter();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(focus ?? null);
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [kinds, setKinds] = useState<Set<MarkerKind>>(new Set());
  const paneRef = useRef<HTMLElement>(null);

  const visible = useMemo(
    () =>
      locations.filter((l) => {
        if (kinds.size > 0 && !kinds.has(classify(l).kind)) return false;
        if (statuses.size > 0 && !statuses.has(l.status_hint ?? l.current_status ?? "")) return false;
        return true;
      }),
    [locations, kinds, statuses],
  );
  const selected = locations.find((l) => l.slug === selectedSlug) ?? null;
  const focused = locations.find((l) => l.slug === focus);
  const flyTarget: [number, number] | null = focused ? [focused.lat, focused.lng] : null;

  function toggle<T>(set: Set<T>, value: T, apply: (next: Set<T>) => void) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  }

  // Leaflet makes markers focusable and Enter-activatable, but activating one
  // leaves focus back on the map while the content appears in the pane — so
  // send focus there. preventScroll keeps the narrow-screen scroll below in
  // charge of where the viewport lands.
  useEffect(() => {
    if (!selectedSlug || !paneRef.current) return;
    paneRef.current.focus({ preventScroll: true });
  }, [selectedSlug]);

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
    centerOverride ??
    (locations.length > 0
      ? [
          locations.reduce((s, l) => s + l.lat, 0) / locations.length,
          locations.reduce((s, l) => s + l.lng, 0) / locations.length,
        ]
      : [38.8462, -77.3064]); // City of Fairfax

  const mapHeight = compact
    ? "h-[420px]"
    : "h-[calc(100vh-64px-140px)] min-h-[480px]";

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <div className="min-w-0 flex-1">
        {!compact && (
          <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[12px]">
            {KIND_FILTERS.map((k) => (
              <button
                key={k.key}
                type="button"
                aria-pressed={kinds.has(k.key)}
                onClick={() => toggle(kinds, k.key, setKinds)}
                className={`rounded-full px-3 py-1 font-medium ${
                  kinds.has(k.key) ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
                }`}
              >
                {k.label}
              </button>
            ))}
            <span className="mx-1 h-4 w-px bg-hairline" />
            {STATUS_FILTERS.map((st) => (
              <button
                key={st}
                type="button"
                aria-pressed={statuses.has(st)}
                onClick={() => toggle(statuses, st, setStatuses)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-medium ${
                  statuses.has(st) ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
                }`}
              >
                <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: PIN_COLORS[st] }} />
                {st.replace("_", " ")}
              </button>
            ))}
            {(kinds.size > 0 || statuses.size > 0) && (
              <button
                type="button"
                onClick={() => {
                  setKinds(new Set());
                  setStatuses(new Set());
                }}
                className="ml-1 font-semibold text-muted underline underline-offset-2 hover:text-ink"
              >
                clear · {visible.length} of {locations.length}
              </button>
            )}
          </div>
        )}
        <MapContainer
          center={center}
          zoom={compact ? 15 : 14}
          scrollWheelZoom={!compact}
          className={`${mapHeight} w-full rounded-3xl border border-hairline`}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FlyTo target={flyTarget} />
          {!compact && <DeselectOnMapClick onDeselect={() => setSelectedSlug(null)} />}
          {centerOverride && (
            <CircleMarker
              center={centerOverride}
              radius={7}
              pathOptions={{ color: "#fffaf0", fillColor: "#0a0a0a", fillOpacity: 1, weight: 2 }}
            >
              <Tooltip direction="top" offset={[0, -8]} opacity={1} className="map-marker-label">
                Your spot
              </Tooltip>
            </CircleMarker>
          )}
          {visible.map((loc) => {
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
                eventHandlers={{
                  click: () =>
                    compact
                      ? router.push(loc.slug.startsWith("official-")
                          ? `/development/${loc.slug.slice("official-".length)}`
                          : `/topics/${loc.slug}`)
                      : setSelectedSlug(loc.slug),
                }}
              >
                <Tooltip direction="top" offset={[0, -8]} opacity={1} className="map-marker-label">
                  {loc.name}
                </Tooltip>
              </Marker>
            );
          })}
        </MapContainer>
      </div>

      {!compact && (
      <aside
        ref={paneRef}
        tabIndex={-1}
        aria-label="Location details"
        className="scroll-mt-4 outline-none lg:h-[calc(100vh-64px-140px)] lg:min-h-[480px] lg:w-[360px] lg:shrink-0"
      >
        <DetailPane location={selected} onClose={() => setSelectedSlug(null)} />
      </aside>
      )}
    </div>
  );
}
