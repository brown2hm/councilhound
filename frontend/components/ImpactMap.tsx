"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import "leaflet.heat";
import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  GeoJSON,
  LayerGroup,
  LayersControl,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";

// viridis control points (matplotlib); linear interpolation between stops
const VIRIDIS: [number, number, number][] = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
  [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37],
];

function viridis(t: number): string {
  const x = Math.min(Math.max(t, 0), 1) * (VIRIDIS.length - 1);
  const i = Math.min(Math.floor(x), VIRIDIS.length - 2);
  const f = x - i;
  const [r0, g0, b0] = VIRIDIS[i];
  const [r1, g1, b1] = VIRIDIS[i + 1];
  return `rgb(${Math.round(r0 + f * (r1 - r0))},${Math.round(g0 + f * (g1 - g0))},${Math.round(b0 + f * (b1 - b0))})`;
}

const VIRIDIS_GRADIENT = Object.fromEntries(
  VIRIDIS.map((rgb, i) => [i / (VIRIDIS.length - 1), `rgb(${rgb.join(",")})`]),
);

function fmtDollars(x: number): string {
  if (x >= 1_000_000) return `$${(x / 1_000_000).toFixed(1)}M`;
  if (x >= 1_000) return `$${Math.round(x / 1_000)}k`;
  return `$${Math.round(x)}`;
}

/** Kernel heatmap of spending capture (leaflet.heat with a viridis gradient).
 * Prefers the per-POI capture_points layer (one weighted point per business);
 * falls back to cluster centroids for evaluations computed before it existed. */
function SpendingHeatLayer({ source }: { source: GeoJSON.FeatureCollection }) {
  const map = useMap();
  useEffect(() => {
    const captures = source.features
      .filter((f) => f.geometry.type === "Point")
      .map((f) => {
        const props = f.properties as { capture_usd?: number; annual_capture_usd?: number };
        return {
          coords: (f.geometry as GeoJSON.Point).coordinates as [number, number],
          capture: props?.capture_usd ?? props?.annual_capture_usd ?? 0,
        };
      });
    const max = Math.max(1, ...captures.map((c) => c.capture));
    // sqrt scaling keeps mid-size destinations visible next to the top one
    const points = captures.map(
      ({ coords: [lng, lat], capture }) =>
        [lat, lng, Math.sqrt(capture / max)] as [number, number, number],
    );
    const layer = (L as unknown as { heatLayer: (pts: unknown, opts: unknown) => L.Layer })
      .heatLayer(points, {
        radius: 22,
        blur: 16,
        maxZoom: 16,
        max: 1.0,
        gradient: VIRIDIS_GRADIENT,
      });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, source]);
  return null;
}

export default function ImpactMap({
  layers,
}: {
  layers: Record<string, GeoJSON.FeatureCollection>;
}) {
  const site = layers.site;
  const clusters = layers.capture_clusters;
  const capturePoints = layers.capture_points;
  const footTraffic = layers.foot_traffic_delta;
  const walkDollars = layers.walk_dollars;

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

  // foot-traffic -> viridis by exact marginal trips (sqrt-scaled); older
  // evaluations without trips_per_day fall back to the delta_pct range
  const flowScale = useMemo(() => {
    const features = footTraffic?.features ?? [];
    const trips = features.map(
      (f) => (f.properties as { trips_per_day?: number })?.trips_per_day,
    );
    if (trips.some((t) => t != null)) {
      const max = Math.max(1e-9, ...trips.map((t) => t ?? 0));
      return (props: { trips_per_day?: number; delta_pct?: number }) =>
        Math.sqrt((props.trips_per_day ?? 0) / max);
    }
    const deltas = features.map(
      (f) => (f.properties as { delta_pct?: number })?.delta_pct ?? 0,
    );
    const min = Math.min(0, ...deltas);
    const max = Math.max(1, ...deltas);
    return (props: { trips_per_day?: number; delta_pct?: number }) =>
      ((props.delta_pct ?? 0) - min) / (max - min);
  }, [footTraffic]);

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
        <LayersControl position="topright">
          <LayersControl.Overlay checked name="Spending captured (heatmap)">
            <SpendingHeatLayerWrapper source={capturePoints ?? clusters} />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={!walkDollars} name="Foot traffic (trips/day)">
            <FootTrafficLayer footTraffic={footTraffic} flowScale={flowScale} />
          </LayersControl.Overlay>
          {walkDollars && (
            <LayersControl.Overlay checked name="Walking expenditures ($/yr)">
              <WalkDollarsLayer walkDollars={walkDollars} />
            </LayersControl.Overlay>
          )}
          <LayersControl.Overlay checked name="Cluster details">
            <ClusterMarkers clusters={clusters} maxCapture={maxCapture} />
          </LayersControl.Overlay>
        </LayersControl>
        {site && (
          <GeoJSON
            data={site}
            style={{ color: "#1a3a3a", weight: 2.5, fillColor: "#ffffff", fillOpacity: 0.35 }}
          />
        )}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-xl border border-hairline bg-canvas/90 px-3 py-2 text-[11px] leading-relaxed text-muted">
        <div className="mb-1 flex items-center gap-2">
          <span
            className="inline-block h-2 w-24 rounded-full"
            style={{
              background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1]
                .map((t) => viridis(t))
                .join(", ")})`,
            }}
          />
          <span>low → high (both layers)</span>
        </div>
        <span className="mr-3">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border-2 border-[#1a3a3a] bg-white/60 align-middle" />
          project site
        </span>
        <span>blur: $ captured per business · lines: walking $/yr (toggle for trips)</span>
      </div>
    </div>
  );
}

// react-leaflet's LayersControl needs layer-ish children; wrap the imperative
// heat layer and the marker groups in components it can toggle
function SpendingHeatLayerWrapper({ source }: { source?: GeoJSON.FeatureCollection }) {
  if (!source) return <LayerGroup />;
  return (
    <LayerGroup>
      <SpendingHeatLayer source={source} />
    </LayerGroup>
  );
}

function FootTrafficLayer({
  footTraffic,
  flowScale,
}: {
  footTraffic?: GeoJSON.FeatureCollection;
  flowScale: (props: { trips_per_day?: number; delta_pct?: number }) => number;
}) {
  if (!footTraffic) return <LayerGroup />;
  return (
    <LayerGroup>
      <GeoJSON
        data={footTraffic}
        style={(feature) => {
          const props = (feature?.properties ?? {}) as {
            trips_per_day?: number;
            delta_pct?: number;
          };
          return { color: viridis(flowScale(props)), weight: 3, opacity: 0.85 };
        }}
        onEachFeature={(feature, layer) => {
          const props = (feature.properties ?? {}) as {
            trips_per_day?: number;
            delta_pct?: number;
          };
          const parts = [];
          if (props.trips_per_day != null)
            parts.push(`≈${props.trips_per_day} new walk trips/day`);
          if (props.delta_pct != null)
            parts.push(`${props.delta_pct >= 0 ? "+" : ""}${props.delta_pct}% vs baseline`);
          layer.bindTooltip(parts.join(" · ") || "foot traffic");
        }}
      />
    </LayerGroup>
  );
}

function WalkDollarsLayer({ walkDollars }: { walkDollars: GeoJSON.FeatureCollection }) {
  const max = Math.max(
    1e-9,
    ...walkDollars.features.map(
      (f) => (f.properties as { dollars_per_year?: number })?.dollars_per_year ?? 0,
    ),
  );
  return (
    <LayerGroup>
      <GeoJSON
        data={walkDollars}
        style={(feature) => {
          const dollars =
            (feature?.properties as { dollars_per_year?: number })?.dollars_per_year ?? 0;
          return { color: viridis(Math.sqrt(dollars / max)), weight: 3.5, opacity: 0.85 };
        }}
        onEachFeature={(feature, layer) => {
          const dollars =
            (feature.properties as { dollars_per_year?: number })?.dollars_per_year ?? 0;
          layer.bindTooltip(`${fmtDollars(dollars)}/yr in new pedestrian spending`);
        }}
      />
    </LayerGroup>
  );
}

function ClusterMarkers({
  clusters,
  maxCapture,
}: {
  clusters?: GeoJSON.FeatureCollection;
  maxCapture: number;
}) {
  return (
    <LayerGroup>
      {(clusters?.features ?? []).map((f, i) => {
        if (f.geometry.type !== "Point") return null;
        const [lng, lat] = f.geometry.coordinates as [number, number];
        const props = f.properties as {
          name?: string;
          annual_capture_usd?: number;
          poi_count?: number;
          own?: boolean;
        };
        const capture = props.annual_capture_usd ?? 0;
        const radius = 5 + 13 * Math.sqrt(capture / maxCapture);
        return (
          <CircleMarker
            key={i}
            center={[lat, lng]}
            radius={radius}
            pathOptions={{
              color: props.own ? "#1a3a3a" : "#ffffff",
              weight: props.own ? 2.5 : 1.5,
              fillColor: viridis(Math.sqrt(capture / maxCapture)),
              fillOpacity: 0.75,
            }}
          >
            <Tooltip>
              <span className="font-semibold">{props.name}</span>
              <br />
              {fmtDollars(capture)}/yr captured
              {props.own
                ? " · this project"
                : props.poi_count
                  ? ` · ${props.poi_count} businesses (named for the one nearest the cluster center)`
                  : ""}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </LayerGroup>
  );
}
