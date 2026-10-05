"use client";

import "leaflet/dist/leaflet.css";
import { useJurisdiction } from "@/components/JurisdictionProvider";
import L from "leaflet";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Marker, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import StatusBadge from "@/components/StatusBadge";
import type { MapLocation } from "@/lib/api";

// status → pin color. Open decisions are the loud pins (in progress, proposed,
// pre-application); settled ones are quiet; no status at all gets its own grey
// rather than borrowing one. divIcons avoid Leaflet's bundled image assets,
// which break under Next bundling.
const PIN_COLORS: Record<string, string> = {
  in_progress: "#e8b94a",
  proposed: "#7c5cbf",
  pre_application: "#b39ddb",
  under_construction: "#1a3a3a",
  approved: "#a4d4c5",
  completed: "#a4d4c5",
  denied: "#c65a32",
  deferred: "#9a9a9a",
  withdrawn: "#9a9a9a",
};
const NO_STATUS_COLOR = "#c9c3b2";
const STATUS_LABELS: Record<string, string> = {
  in_progress: "in progress",
  proposed: "proposed",
  pre_application: "pre-application",
  under_construction: "under construction",
  approved: "approved",
  completed: "completed",
  denied: "denied",
  deferred: "deferred",
  withdrawn: "withdrawn",
};
// list order: what is still being decided first, then settled, then unknown
const STATUS_ORDER = ["in_progress", "proposed", "pre_application", "under_construction", "approved", "completed", "denied", "deferred", "withdrawn"];
const statusOf = (l: MapLocation) => l.status_hint ?? l.current_status ?? null;
const statusRank = (l: MapLocation) => {
  const i = STATUS_ORDER.indexOf(statusOf(l) ?? "");
  return i === -1 ? STATUS_ORDER.length : i;
};

type MarkerKind = "official" | "project" | "mention";

function pinIcon(status: string | null, kind: MarkerKind, selected: boolean) {
  const color = PIN_COLORS[status ?? ""] ?? NO_STATUS_COLOR;
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
  if (loc.is_official_project) return { kind: "official", label: "Official project" };
  if (loc.entity_type === "project") return { kind: "project", label: "Project from meetings" };
  return { kind: "mention", label: "Place from meetings" };
}

// Clears the selection when the user clicks empty map (Leaflet fires the map's
// own click only for the background, not for marker clicks).
function DeselectOnMapClick({ onDeselect }: { onDeselect: () => void }) {
  useMapEvents({ click: onDeselect });
  return null;
}

function ListMark({ loc }: { loc: MapLocation }) {
  const { kind } = classify(loc);
  const color = PIN_COLORS[statusOf(loc) ?? ""] ?? NO_STATUS_COLOR;
  return (
    <span
      aria-hidden
      className={`inline-block shrink-0 ${kind === "official" ? "h-[9px] w-[9px] rotate-45 rounded-[2px]" : kind === "project" ? "h-[9px] w-[9px] rounded-full" : "h-[7px] w-[7px] rounded-full"}`}
      style={{ background: color }}
    />
  );
}

function statusPill(status: string | null) {
  if (!status) return <span className="shrink-0 text-[12px] text-muted-soft">no status yet</span>;
  return <StatusBadge status={status} />;
}

/** Every visible pin, open decisions first. Clicking a row selects its pin
 * and pans the map to it. */
function PinList({
  locations,
  total,
  onPick,
}: {
  locations: MapLocation[];
  total: number;
  onPick: (slug: string) => void;
}) {
  const { display } = useJurisdiction();
  const stripRe = new RegExp(display.address_strip_regex || "$^", "i");
  const ordered = [...locations].sort(
    (a, b) => statusRank(a) - statusRank(b) || Number(b.is_official_project) - Number(a.is_official_project) || a.name.localeCompare(b.name),
  );
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-3xl border border-hairline bg-canvas">
      <div className="border-b border-hairline px-4 pb-2.5 pt-3.5">
        <div className="text-sm font-semibold">On the map</div>
        <div className="text-[12px] text-muted">Open decisions first. Click a row to find its pin, or a pin to open the record here.</div>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {ordered.map((loc) => {
          const { label } = classify(loc);
          const address = loc.address ?? loc.matched_address;
          return (
            <li key={loc.slug}>
              <button
                type="button"
                onClick={() => onPick(loc.slug)}
                className="grid w-full grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-2 border-b border-hairline-soft px-4 py-2 text-left hover:bg-soft"
              >
                <ListMark loc={loc} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{loc.name}</span>
                  <span className="block truncate text-[12px] text-muted">
                    {label}
                    {address ? ` · ${address.split(stripRe)[0]}` : ""}
                  </span>
                </span>
                {statusPill(statusOf(loc))}
              </button>
            </li>
          );
        })}
        {ordered.length === 0 && <li className="px-4 py-6 text-sm text-muted">Nothing matches these filters.</li>}
      </ul>
      <div className="border-t border-hairline px-4 py-2 text-[12px] text-muted">
        {ordered.length === total ? `${total} on the map` : `${ordered.length} of ${total}`}
      </div>
    </div>
  );
}

function DetailPane({
  location,
  onClose,
}: {
  location: MapLocation;
  onClose: () => void;
}) {
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
          aria-label="Back to the list"
          className="-mr-1 shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold text-muted transition hover:bg-soft hover:text-ink"
        >
          ← list
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

const KIND_FILTERS: { key: MarkerKind; label: string }[] = [
  { key: "official", label: "Official projects" },
  { key: "project", label: "Projects from meetings" },
  { key: "mention", label: "Places from meetings" },
];

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-muted">
      <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block h-[9px] w-[9px] rotate-45 rounded-[2px] bg-muted" /> city project</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block h-[9px] w-[9px] rounded-full bg-muted" /> project from meetings</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block h-[7px] w-[7px] rounded-full bg-muted" /> place from meetings</span>
      <span aria-hidden className="h-3.5 w-px bg-hairline" />
      {STATUS_ORDER.filter((st) => st !== "completed" && st !== "withdrawn").map((st) => (
        <span key={st} className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: PIN_COLORS[st] }} />
          {STATUS_LABELS[st]}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: NO_STATUS_COLOR }} /> no status yet
      </span>
    </div>
  );
}

// Pans to a point when it changes; `key` lets the same point be re-requested
function FlyTo({ target, animate = false }: { target: [number, number] | null; animate?: boolean }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.setView(target, Math.max(map.getZoom(), 16), { animate });
  }, [map, target, animate]);
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
  const { display } = useJurisdiction();
  const router = useRouter();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(focus ?? null);
  const [status, setStatus] = useState<string>("");
  const [kinds, setKinds] = useState<Set<MarkerKind>>(new Set());
  const [picked, setPicked] = useState<[number, number] | null>(null);
  const paneRef = useRef<HTMLElement>(null);

  const visible = useMemo(
    () =>
      locations.filter((l) => {
        if (kinds.size > 0 && !kinds.has(classify(l).kind)) return false;
        if (status === "none" ? statusOf(l) !== null : status && statusOf(l) !== status) return false;
        return true;
      }),
    [locations, kinds, status],
  );
  const kindCounts = useMemo(() => {
    const c: Record<MarkerKind, number> = { official: 0, project: 0, mention: 0 };
    for (const l of locations) c[classify(l).kind] += 1;
    return c;
  }, [locations]);
  const statusOptions = useMemo(
    () => STATUS_ORDER.filter((st) => locations.some((l) => statusOf(l) === st)),
    [locations],
  );
  const selected = locations.find((l) => l.slug === selectedSlug) ?? null;
  const focused = locations.find((l) => l.slug === focus);
  const flyTarget: [number, number] | null = picked ?? (focused ? [focused.lat, focused.lng] : null);

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
      : display.map_center);

  const mapHeight = compact
    ? "h-[420px]"
    : "h-[calc(100vh-64px-140px)] min-h-[480px]";

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <div className="min-w-0 flex-1">
        {!compact && (
          <div className="mb-3 flex flex-col gap-2.5">
            <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
              <button
                type="button"
                aria-pressed={kinds.size === 0}
                onClick={() => setKinds(new Set())}
                className={`rounded-full px-3 py-1.5 font-medium ${kinds.size === 0 ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"}`}
              >
                All {locations.length}
              </button>
              {KIND_FILTERS.map((k) => (
                <button
                  key={k.key}
                  type="button"
                  aria-pressed={kinds.has(k.key)}
                  onClick={() => toggle(kinds, k.key, setKinds)}
                  className={`rounded-full px-3 py-1.5 font-medium ${
                    kinds.has(k.key) ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
                  }`}
                >
                  {k.label} {kindCounts[k.key]}
                </button>
              ))}
              <label className="ml-1 inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas py-1 pl-3 pr-1.5 text-[13px] text-muted">
                Status
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="bg-transparent pr-1 text-[13px] font-semibold text-ink outline-none"
                >
                  <option value="">Any</option>
                  {statusOptions.map((st) => (
                    <option key={st} value={st}>
                      {STATUS_LABELS[st] ?? st}
                    </option>
                  ))}
                  <option value="none">no status yet</option>
                </select>
              </label>
              {(kinds.size > 0 || status) && (
                <button
                  type="button"
                  onClick={() => {
                    setKinds(new Set());
                    setStatus("");
                  }}
                  className="ml-1 font-semibold text-muted underline underline-offset-2 hover:text-ink"
                >
                  clear
                </button>
              )}
            </div>
            <Legend />
          </div>
        )}
        <MapContainer
          center={center}
          zoom={compact ? display.map_zoom.compact : display.map_zoom.full}
          scrollWheelZoom={!compact}
          className={`${mapHeight} w-full rounded-3xl border border-hairline`}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FlyTo target={flyTarget} animate={picked !== null} />
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
                zIndexOffset={isSelected ? 1000 : statusOf(loc) ? 100 : 0}
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
        className="h-[420px] scroll-mt-4 outline-none lg:h-[calc(100vh-64px-140px)] lg:min-h-[480px] lg:w-[380px] lg:shrink-0"
      >
        {selected ? (
          <DetailPane location={selected} onClose={() => setSelectedSlug(null)} />
        ) : (
          <PinList
            locations={visible}
            total={locations.length}
            onPick={(slug) => {
              const loc = locations.find((l) => l.slug === slug);
              if (!loc) return;
              setSelectedSlug(slug);
              setPicked([loc.lat, loc.lng]);
            }}
          />
        )}
      </aside>
      )}
    </div>
  );
}
