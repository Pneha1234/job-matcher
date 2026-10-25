"use client";

import "leaflet/dist/leaflet.css";

import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

import { scoreTone } from "@/lib/format";

export type MapPoint = {
  city: string;
  country: string;
  lat: number;
  lon: number;
  count: number;
  best: number | null;
  jobs: { id: number; title: string; company: string; pct: number | null }[];
};

const COLOR = { hi: "#15803d", mid: "#a16207", lo: "#5b6472" } as const;

/** One circle per city, sized by how many matching jobs it has, coloured by the best match. */
export default function JobMap({ points, onOpen }: { points: MapPoint[]; onOpen: (id: number) => void }) {
  const max = Math.max(1, ...points.map((p) => p.count));
  return (
    <MapContainer center={[30, 20]} zoom={2} minZoom={2} worldCopyJump className="h-[640px] w-full rounded-xl border border-border">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {points.map((p) => {
        const color = COLOR[scoreTone(p.best)];
        return (
          <CircleMarker
            key={`${p.city}-${p.country}`}
            center={[p.lat, p.lon]}
            radius={6 + 18 * Math.sqrt(p.count / max)}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.45, weight: 1 }}
          >
            <Popup>
              <div className="text-[13px]">
                <b>
                  {p.city}, {p.country}
                </b>{" "}
                · {p.count} {p.count === 1 ? "job" : "jobs"}
                <ul className="mt-1 space-y-0.5">
                  {p.jobs.map((j) => (
                    <li key={j.id}>
                      <button type="button" className="text-left text-primary" onClick={() => onOpen(j.id)}>
                        {j.pct !== null ? `${Math.round(j.pct)}% · ` : ""}
                        {j.title} · {j.company}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
