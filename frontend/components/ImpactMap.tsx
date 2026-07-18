"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import "leaflet.heat";
import { useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { useLeafletContext } from "@react-leaflet/core";
import {
  CircleMarker,
  GeoJSON,
  LayerGroup,
  LayersControl,
  MapContainer,
  TileLayer,
  Tooltip,
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

type HeatPoint = [number, number, number]; // lat, lng, weight 0..1
type Position = [number, number]; // lng, lat
type HeatLayerInternals = L.Layer & {
  _canvas?: HTMLCanvasElement;
  _redraw?: () => unknown;
};

function fmtDollars(x: number): string {
  if (x >= 1_000_000) return `$${(x / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (x >= 1_000) return `$${Math.round(x / 1_000)}k`;
  return `$${Math.round(x)}`;
}

/** Snap up to a "nice" dollar ceiling so the color ramp tops out at a round
 * number the legend can state ($319,556 -> $400k). */
function niceCeil(x: number): number {
  if (x <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(x));
  for (const mult of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (mult * power >= x) return mult * power;
  }
  return 10 * power;
}

/** Dollars -> ramp position under the pinned sqrt scale. */
function dollarT(value: number, scaleMax: number): number {
  return Math.sqrt(Math.min(Math.max(value, 0), scaleMax) / scaleMax);
}

function maxDollar(fc: GeoJSON.FeatureCollection | undefined, keys: string[]): number {
  let max = 0;
  for (const f of fc?.features ?? []) {
    const props = (f.properties ?? {}) as Record<string, unknown>;
    for (const key of keys) {
      const v = props[key];
      if (typeof v === "number" && v > max) max = v;
    }
  }
  return max;
}

function zonePolygons(zones?: GeoJSON.FeatureCollection): Position[][][] {
  const polygons: Position[][][] = [];
  for (const feature of zones?.features ?? []) {
    if (feature.geometry.type === "Polygon") {
      polygons.push(feature.geometry.coordinates as Position[][]);
    } else if (feature.geometry.type === "MultiPolygon") {
      polygons.push(...(feature.geometry.coordinates as Position[][][]));
    }
  }
  return polygons;
}

function pointInRing([x, y]: Position, ring: Position[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const crosses = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

function pointInZones(point: Position, zones?: GeoJSON.FeatureCollection): boolean {
  const polygons = zonePolygons(zones);
  if (polygons.length === 0) return true;
  return polygons.some(
    (rings) => pointInRing(point, rings[0]) && !rings.slice(1).some((ring) => pointInRing(point, ring)),
  );
}

function clipHeatCanvas(
  layer: HeatLayerInternals,
  map: L.Map,
  zones?: GeoJSON.FeatureCollection,
) {
  const canvas = layer._canvas;
  const polygons = zonePolygons(zones);
  if (!canvas || polygons.length === 0) return;

  const mask = document.createElement("canvas");
  mask.width = canvas.width;
  mask.height = canvas.height;
  const maskContext = mask.getContext("2d");
  const heatContext = canvas.getContext("2d");
  if (!maskContext || !heatContext) return;

  maskContext.fillStyle = "#000";
  maskContext.beginPath();
  for (const rings of polygons) {
    for (const ring of rings) {
      ring.forEach(([lng, lat], index) => {
        const point = map.latLngToContainerPoint([lat, lng]);
        if (index === 0) maskContext.moveTo(point.x, point.y);
        else maskContext.lineTo(point.x, point.y);
      });
      maskContext.closePath();
    }
  }
  maskContext.fill("evenodd");

  heatContext.save();
  heatContext.globalCompositeOperation = "destination-in";
  heatContext.drawImage(mask, 0, 0);
  heatContext.restore();
}

/** leaflet.heat canvas attached to the PARENT layer container (the
 * LayersControl overlay's LayerGroup), so the checkbox actually adds and
 * removes it — attaching straight to the map made it un-toggleable. */
function HeatCanvas({
  points,
  radius,
  blur,
  minOpacity = 0.55,
  clipZones,
}: {
  points: HeatPoint[];
  radius: number;
  blur: number;
  minOpacity?: number;
  clipZones?: GeoJSON.FeatureCollection;
}) {
  const context = useLeafletContext();
  useEffect(() => {
    const layer = (L as unknown as { heatLayer: (pts: unknown, opts: unknown) => L.Layer })
      .heatLayer(points, {
        radius,
        blur,
        minOpacity,
        maxZoom: 16,
        max: 1.0,
        gradient: VIRIDIS_GRADIENT,
      }) as HeatLayerInternals;
    const container = context.layerContainer ?? context.map;
    const originalRedraw = layer._redraw;
    if (originalRedraw) {
      layer._redraw = function redrawAndClip() {
        const result = originalRedraw.call(layer);
        clipHeatCanvas(layer, context.map, clipZones);
        return result;
      };
    }
    container.addLayer(layer);
    return () => {
      if (originalRedraw) layer._redraw = originalRedraw;
      container.removeLayer(layer);
    };
  }, [context, points, radius, blur, minOpacity, clipZones]);
  return null;
}

/** Per-POI capture -> heat points (sqrt-scaled so mid-size destinations stay
 * visible next to the top one). Accepts the legacy cluster layer as a
 * fallback for evaluations computed before capture_points existed. */
function captureHeatPoints(
  source: GeoJSON.FeatureCollection,
  valueKeys: string[],
  scaleMax: number,
  zones?: GeoJSON.FeatureCollection,
  minValue = 0,
): HeatPoint[] {
  // minValue guards against the additive-kernel artifact: hundreds of
  // near-zero points in a dense cluster would otherwise SUM to a bright
  // blob, misreading as real dollars (bit us on the walk-in layer, where
  // distant businesses each get a sliver)
  return source.features
    .filter((f) => f.geometry.type === "Point")
    .map((f) => {
      const props = (f.properties ?? {}) as Record<string, unknown>;
      const key = valueKeys.find((k) => typeof props[k] === "number");
      return {
        coords: (f.geometry as GeoJSON.Point).coordinates as [number, number],
        value: key ? (props[key] as number) : 0,
      };
    })
    .filter(({ coords, value }) => value > minValue && pointInZones(coords, zones))
    .map(({ coords: [lng, lat], value }): HeatPoint => [lat, lng, dollarT(value, scaleMax)]);
}

function pointFeaturesForValue(
  source: GeoJSON.FeatureCollection | undefined,
  key: string,
  minValue = 0,
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: (source?.features ?? []).filter((f) => {
      const props = (f.properties ?? {}) as Record<string, unknown>;
      return f.geometry.type === "Point" && typeof props[key] === "number" && props[key] > minValue;
    }),
  };
}

function boundsFor(
  layers: Array<GeoJSON.FeatureCollection | undefined>,
  fallback: L.LatLngBoundsLiteral,
  pad: number,
): L.LatLngBounds {
  const b = L.latLngBounds([]);
  for (const fc of layers) {
    fc?.features.forEach((f) => {
      try {
        b.extend(L.geoJSON(f as GeoJSON.GeoJsonObject).getBounds());
      } catch {
        /* skip malformed feature */
      }
    });
  }
  return b.isValid() ? b.pad(pad) : L.latLngBounds(fallback);
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
  const commercialRetailZones = layers.commercial_retail_zones;
  const cityBoundary = layers.city_boundary;

  const defaultBounds: L.LatLngBoundsLiteral = [[38.83, -77.33], [38.87, -77.27]];

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

  // pinned dollar scales: nice round ceilings computed from the UNFILTERED
  // data, so a color always means the same dollars regardless of zoning
  // filtering or layer toggling, and the legend can state the values
  const captureScaleMax = useMemo(
    () => niceCeil(maxDollar(capturePoints ?? clusters, ["capture_usd", "annual_capture_usd"])),
    [capturePoints, clusters],
  );

  const emptyFc: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
  const spendingHeat = useMemo(
    () =>
      captureHeatPoints(
        capturePoints ?? clusters ?? emptyFc,
        ["capture_usd", "annual_capture_usd"],
        captureScaleMax,
        commercialRetailZones,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [capturePoints, clusters, captureScaleMax, commercialRetailZones],
  );
  // walk-in capture: the walk-arriving share of each business's capture, on
  // the SAME dollar scale as total capture so toggling the two heatmaps
  // shows how much of a business's gain depends on walk access
  const walkInHeat = useMemo(
    () =>
      captureHeatPoints(
        capturePoints ?? emptyFc,
        ["walk_usd"],
        captureScaleMax,
        commercialRetailZones,
        captureScaleMax * 0.005, // drop the long near-zero tail (see above)
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [capturePoints, captureScaleMax, commercialRetailZones],
  );
  const hasWalkIn = walkInHeat.length > 0;
  const walkPointsForBounds = useMemo(
    () => pointFeaturesForValue(capturePoints, "walk_usd", captureScaleMax * 0.005),
    [capturePoints, captureScaleMax],
  );
  const captureBounds = useMemo(
    () => boundsFor([cityBoundary], defaultBounds, 0.04),
    [cityBoundary],
  );
  const walkBounds = useMemo(
    () => boundsFor([site, walkPointsForBounds, footTraffic], defaultBounds, 0.12),
    [site, walkPointsForBounds, footTraffic],
  );

  // trips styling for the optional street-lines overlay
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
    <div className="grid gap-4 lg:grid-cols-2">
      <MapPanel title="Overall Economic Impact">
        <CaptureMap
          bounds={captureBounds}
          site={site}
          clusters={clusters}
          maxCapture={maxCapture}
          commercialRetailZones={commercialRetailZones}
          spendingHeat={spendingHeat}
          captureScaleMax={captureScaleMax}
        />
      </MapPanel>
      <MapPanel title="Walk-Based Impact">
        <WalkMap
          bounds={walkBounds}
          site={site}
          footTraffic={footTraffic}
          flowScale={flowScale}
          commercialRetailZones={commercialRetailZones}
          walkInHeat={walkInHeat}
          hasWalkIn={hasWalkIn}
          captureScaleMax={captureScaleMax}
        />
      </MapPanel>
    </div>
  );
}

function MapPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-body">{title}</h3>
      <div className="relative">{children}</div>
    </div>
  );
}

function CaptureMap({
  bounds,
  site,
  clusters,
  maxCapture,
  commercialRetailZones,
  spendingHeat,
  captureScaleMax,
}: {
  bounds: L.LatLngBoundsExpression;
  site?: GeoJSON.FeatureCollection;
  clusters?: GeoJSON.FeatureCollection;
  maxCapture: number;
  commercialRetailZones?: GeoJSON.FeatureCollection;
  spendingHeat: HeatPoint[];
  captureScaleMax: number;
}) {
  return (
    <>
      <MapContainer
        bounds={bounds}
        scrollWheelZoom={false}
        className="h-[420px] w-full rounded-2xl border border-hairline"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        <LayersControl position="topright">
          <LayersControl.Overlay checked name="Spending captured (heatmap)">
            <LayerGroup>
              <HeatCanvas
                points={spendingHeat}
                radius={22}
                blur={16}
                clipZones={commercialRetailZones}
              />
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Cluster details">
            <ClusterMarkers clusters={clusters} maxCapture={maxCapture} />
          </LayersControl.Overlay>
          {commercialRetailZones && (
            <LayersControl.Overlay name="Commercial Retail zoning (CR)">
              <GeoJSON
                data={commercialRetailZones}
                style={{ color: "#1a3a3a", weight: 1.5, dashArray: "5 4", fillOpacity: 0 }}
              />
            </LayersControl.Overlay>
          )}
        </LayersControl>
        {site && (
          <GeoJSON
            data={site}
            style={{ color: "#1a3a3a", weight: 2.5, fillColor: "#ffffff", fillOpacity: 0.35 }}
          />
        )}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-xl border border-hairline bg-canvas/90 px-3 py-2 text-[11px] leading-relaxed text-muted">
        <DollarScaleRow
          label="$ captured /business/yr"
          scaleMax={captureScaleMax}
        />
        <span className="mr-3">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border-2 border-[#1a3a3a] bg-white/60 align-middle" />
          project site
        </span>
        <span>overlapping sources render brighter</span>
      </div>
    </>
  );
}

function WalkMap({
  bounds,
  site,
  footTraffic,
  flowScale,
  commercialRetailZones,
  walkInHeat,
  hasWalkIn,
  captureScaleMax,
}: {
  bounds: L.LatLngBoundsExpression;
  site?: GeoJSON.FeatureCollection;
  footTraffic?: GeoJSON.FeatureCollection;
  flowScale: (props: { trips_per_day?: number; delta_pct?: number }) => number;
  commercialRetailZones?: GeoJSON.FeatureCollection;
  walkInHeat: HeatPoint[];
  hasWalkIn: boolean;
  captureScaleMax: number;
}) {
  return (
    <>
      <MapContainer
        bounds={bounds}
        scrollWheelZoom={false}
        className="h-[420px] w-full rounded-2xl border border-hairline"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        <LayersControl position="topright">
          {hasWalkIn && (
            <LayersControl.Overlay checked name="Walk-in capture (heatmap)">
              <LayerGroup>
                <HeatCanvas
                  points={walkInHeat}
                  radius={22}
                  blur={16}
                  minOpacity={0.75}
                  clipZones={commercialRetailZones}
                />
              </LayerGroup>
            </LayersControl.Overlay>
          )}
          <LayersControl.Overlay checked name="Foot traffic (trips/day)">
            <FootTrafficLayer footTraffic={footTraffic} flowScale={flowScale} />
          </LayersControl.Overlay>
          {commercialRetailZones && (
            <LayersControl.Overlay name="Commercial Retail zoning (CR)">
              <GeoJSON
                data={commercialRetailZones}
                style={{ color: "#1a3a3a", weight: 1.5, dashArray: "5 4", fillOpacity: 0 }}
              />
            </LayersControl.Overlay>
          )}
        </LayersControl>
        {site && (
          <GeoJSON
            data={site}
            style={{ color: "#1a3a3a", weight: 2.5, fillColor: "#ffffff", fillOpacity: 0.35 }}
          />
        )}
      </MapContainer>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-xl border border-hairline bg-canvas/90 px-3 py-2 text-[11px] leading-relaxed text-muted">
        {hasWalkIn && (
          <DollarScaleRow label="$ arriving on foot /business/yr" scaleMax={captureScaleMax} />
        )}
        <span className="mr-3">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border-2 border-[#1a3a3a] bg-white/60 align-middle" />
          project site
        </span>
        <span>street color ranks new walk trips/day</span>
      </div>
    </>
  );
}

/** Chips at fixed fractions of the pinned ceiling, so the legend states the
 * dollars each color means (top chip is the ceiling itself, hence the +). */
function DollarScaleRow({ label, scaleMax }: { label: string; scaleMax: number }) {
  const fractions = [0.01, 0.1, 0.5, 1];
  return (
    <div className="mb-1 flex items-center gap-2">
      <span className="flex items-center gap-1">
        {fractions.map((f) => (
          <span key={f} className="flex items-center gap-0.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: viridis(dollarT(f * scaleMax, scaleMax)) }}
            />
            <span>
              {fmtDollars(f * scaleMax)}
              {f === 1 ? "+" : ""}
            </span>
          </span>
        ))}
      </span>
      <span>{label}</span>
    </div>
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
          return { color: viridis(flowScale(props)), weight: 2.5, opacity: 0.55 };
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
          walk_usd?: number;
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
              {props.walk_usd != null && props.walk_usd > 0 && (
                <> · {fmtDollars(props.walk_usd)} arriving on foot</>
              )}
              {props.own
                ? " · this project"
                : props.poi_count
                  ? ` · ${props.poi_count} businesses near this intersection`
                  : ""}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </LayerGroup>
  );
}
