"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useMemo } from "react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip } from "react-leaflet";

// foot-traffic delta styling: greens for gains, red for losses, weight by magnitude
function edgeStyle(deltaPct: number) {
  const gain = deltaPct >= 0;
  const magnitude = Math.min(Math.abs(deltaPct) / 50, 1);
  return {
    color: gain ? "#14453a" : "#c2402a",
    weight: 1.5 + magnitude * 3.5,
    opacity: 0.35 + magnitude * 0.55,
  };
}

function fmtDollars(x: number): string {
  if (x >= 1_000_000) return `$${(x / 1_000_000).toFixed(1)}M`;
  if (x >= 1_000) return `$${Math.round(x / 1_000)}k`;
  return `$${Math.round(x)}`;
}

export default function ImpactMap({
  layers,
}: {
  layers: Record<string, GeoJSON.FeatureCollection>;
}) {
  const site = layers.site;
  const clusters = layers.capture_clusters;
  const footTraffic = layers.foot_traffic_delta;

  const bounds = useMemo(() => {
    const b = L.latLngBounds([]);
    const extend = (fc?: GeoJSON.FeatureCollection) =>
      fc?.features.forEach((f) => {
        try {
          b.extend(L.geoJSON(f as GeoJSON.GeoJsonObject).getBounds());
        } catch {
          /* skip malformed feature */
        }
      });
    extend(site);
    extend(clusters);
    return b.isValid() ? b.pad(0.4) : L.latLngBounds([[38.83, -77.33], [38.87, -77.27]]);
  }, [site, clusters]);

  const maxCapture = useMemo(
    () =>
      Math.max(
        1,
        ...(clusters?.features ?? []).map(
          (f) => (f.properties as { annual_capture_usd?: number })?.annual_capture_usd ?? 0,
        ),
      ),
    [clusters],
  );

  return (
    <div className="relative">
      <MapContainer
        bounds={bounds}
        scrollWheelZoom={false}
        className="h-[440px] w-full rounded-3xl border border-hairline"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        {footTraffic && (
          <GeoJSON
            data={footTraffic}
            style={(feature) =>
              edgeStyle((feature?.properties as { delta_pct?: number })?.delta_pct ?? 0)
            }
          />
        )}
        {site && (
          <GeoJSON
            data={site}
            style={{ color: "#1a3a3a", weight: 2, fillColor: "#7c5cd4", fillOpacity: 0.25 }}
          />
        )}
        {(clusters?.features ?? []).map((f, i) => {
          if (f.geometry.type !== "Point") return null;
          const [lng, lat] = f.geometry.coordinates as [number, number];
          const props = f.properties as {
            name?: string;
            annual_capture_usd?: number;
            own?: boolean;
          };
          const capture = props.annual_capture_usd ?? 0;
          const radius = 6 + 16 * Math.sqrt(capture / maxCapture);
          return (
            <CircleMarker
              key={i}
              center={[lat, lng]}
              radius={radius}
              pathOptions={{
                color: props.own ? "#7c5cd4" : "#14453a",
                weight: props.own ? 2.5 : 1.5,
                fillColor: props.own ? "#7c5cd4" : "#14453a",
                fillOpacity: 0.3,
              }}
            >
              <Tooltip>
                <span className="font-semibold">{props.name}</span>
                <br />
                {fmtDollars(capture)}/yr captured
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-xl border border-hairline bg-canvas/90 px-3 py-2 text-[11px] leading-relaxed text-muted">
        <span className="mr-3">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-full border-2 border-[#7c5cd4] bg-[#7c5cd4]/30 align-middle" />
          site &amp; its retail
        </span>
        <span className="mr-3">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-[#14453a]/60 align-middle" />
          spending captured
        </span>
        <span>
          <span className="mr-1 inline-block h-0.5 w-4 bg-[#14453a] align-middle" />
          foot-traffic gain
        </span>
      </div>
    </div>
  );
}
