"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Chip } from "@/components/bits";
import { apiGet } from "@/lib/api";

export type Near = { name: string; country: string; lat: number; lon: number } | null;
type City = { name: string; region: string | null; country: string; lat: number; lon: number };

const RADII = [25, 50, 100, 250, 500];

/** "Near a city" with GeoNames autocomplete and a radius. */
export function NearPicker({
  near,
  radius,
  onChange,
}: {
  near: Near;
  radius: number;
  onChange: (near: Near, radius: number) => void;
}) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(text.trim()), 200);
    return () => clearTimeout(t);
  }, [text]);
  const { data: options } = useQuery({
    queryKey: ["geo-cities", query],
    queryFn: () => apiGet<City[]>(`/geo/cities?q=${encodeURIComponent(query)}`),
    enabled: query.length >= 2,
  });

  if (near) {
    return (
      <div className="mt-1.5 flex items-center gap-1.5">
        <Chip tone="acc">
          Near {near.name}, {near.country}
          <button type="button" aria-label="Clear the city" className="opacity-70" onClick={() => onChange(null, radius)}>
            ✕
          </button>
        </Chip>
        <select aria-label="Radius" className="py-0.5 text-xs" value={radius} onChange={(e) => onChange(near, Number(e.target.value))}>
          {RADII.map((r) => (
            <option key={r} value={r}>
              {r} km
            </option>
          ))}
        </select>
      </div>
    );
  }
  return (
    <div className="relative mt-1.5">
      <input className="w-full" placeholder="Near a city…" aria-label="Near a city" value={text} onChange={(e) => setText(e.target.value)} />
      {!!options?.length && text && (
        <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {options.map((c) => (
            <li key={`${c.name}-${c.lat}`}>
              <button
                type="button"
                className="w-full px-2.5 py-1.5 text-left text-[13px] hover:bg-muted"
                onClick={() => {
                  onChange({ name: c.name, country: c.country, lat: c.lat, lon: c.lon }, radius);
                  setText("");
                }}
              >
                {c.name}
                <span className="text-muted-foreground">
                  {c.region ? `, ${c.region}` : ""}, {c.country}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
