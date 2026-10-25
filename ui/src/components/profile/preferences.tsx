"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Btn, Card, Check, Chip, Field } from "@/components/bits";
import { useToast } from "@/components/toast";
import { apiGet, apiSend, ApiError, type AppSettings, type JobType, type SettingsResponse } from "@/lib/api";
import { JOB_TYPE_LABEL } from "@/lib/format";

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => apiGet<SettingsResponse>("/settings") });
}

export function CountryPicker({
  countries,
  value,
  onChange,
  placeholder = "Add a country",
}: {
  countries: { code: string; name: string }[];
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const name = (code: string) => countries.find((c) => c.code === code)?.name ?? code;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {value.map((code) => (
          <Chip key={code} tone="acc">
            {name(code)}
            <button type="button" aria-label={`Remove ${name(code)}`} className="opacity-70" onClick={() => onChange(value.filter((c) => c !== code))}>
              ✕
            </button>
          </Chip>
        ))}
        {!value.length && <span className="text-xs text-faint">None: no location filter</span>}
      </div>
      <select
        value=""
        onChange={(e) => e.target.value && onChange([...value, e.target.value])}
        aria-label={placeholder}
      >
        <option value="">{placeholder}…</option>
        {countries
          .filter((c) => !value.includes(c.code))
          .map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
      </select>
    </div>
  );
}

export function PreferencesForm({ onSaved }: { onSaved?: () => void }) {
  const { data } = useSettings();
  if (!data) return <Card className="text-muted-foreground">Loading preferences…</Card>;
  return <PreferencesInner initial={data} onSaved={onSaved} />;
}

function PreferencesInner({ initial, onSaved }: { initial: SettingsResponse; onSaved?: () => void }) {
  const [s, setS] = useState<AppSettings>(initial.settings);
  const [errors, setErrors] = useState<string>("");
  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () => apiSend<{ settings: AppSettings }>("/settings", "PUT", s),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("Preferences saved. Jobs re-rank with them on the next scoring run.");
      onSaved?.();
    },
    onError: (e: Error) => setErrors(e instanceof ApiError ? e.message : String(e)),
  });
  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => setS((prev) => ({ ...prev, [key]: value }));
  const countries = initial.meta.countries;

  return (
    <Card>
      <b>Preferences</b>
      <div className="mb-3 text-xs text-muted-foreground">
        Where you live decides which remote jobs you are eligible for. Target countries are a hard filter before scoring.
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="You live in">
          <select value={s.home_country ?? ""} onChange={(e) => set("home_country", e.target.value || null)}>
            <option value="">Choose a country…</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="City (optional)">
          <input value={s.home_city ?? ""} onChange={(e) => set("home_city", e.target.value || null)} placeholder="Kathmandu" />
        </Field>
      </div>
      <Field label="Countries you want to work in">
        <CountryPicker countries={countries} value={s.target_countries} onChange={(v) => set("target_countries", v)} />
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-xs text-muted-foreground">Job types (none ticked = all)</div>
          {(Object.keys(JOB_TYPE_LABEL) as JobType[]).map((t) => (
            <Check
              key={t}
              checked={s.job_types.includes(t)}
              onChange={(on) => set("job_types", on ? [...s.job_types, t] : s.job_types.filter((x) => x !== t))}
            >
              {JOB_TYPE_LABEL[t]}
            </Check>
          ))}
        </div>
        <div>
          <Field label={`Minimum annual salary (${s.currency})`}>
            <input
              type="number"
              min={0}
              step={5000}
              value={s.min_salary ?? ""}
              onChange={(e) => set("min_salary", e.target.value ? Number(e.target.value) : null)}
              placeholder="Jobs without a salary still show"
            />
          </Field>
          <Check checked={s.open_to_relocation} onChange={(v) => set("open_to_relocation", v)}>
            Open to relocating
          </Check>
          <Check checked={s.needs_visa} onChange={(v) => set("needs_visa", v)}>
            I need visa sponsorship outside my country
          </Check>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-3">
        <span className="text-xs text-bad">{errors}</span>
        <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save preferences"}
        </Btn>
      </div>
    </Card>
  );
}
