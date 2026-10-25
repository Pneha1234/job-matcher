"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Btn, Card, Check, Chip, Field } from "@/components/bits";
import { PreferencesForm, useSettings } from "@/components/profile/preferences";
import { useToast } from "@/components/toast";
import {
  apiGet,
  apiSend,
  ApiError,
  useTask,
  type AppSettings,
  type SavedSearch,
  type SettingsResponse,
  type SourceRow,
  type Weights,
} from "@/lib/api";
import { scoreTone } from "@/lib/format";

const DEFAULT_WEIGHTS: Weights = { required: 50, nice: 15, seniority: 15, domain: 10, location: 10 };
const LABELS: Record<keyof Weights, string> = {
  required: "Required skills",
  nice: "Nice to have",
  seniority: "Seniority",
  domain: "Domain",
  location: "Location and language",
};
const CURRENCIES = ["EUR", "USD", "GBP", "INR", "NPR", "CHF", "SEK", "NOK", "CAD", "AUD"];

function WeightsCard({ data }: { data: SettingsResponse }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [w, setW] = useState<Weights>(data.settings.weights);
  const [debounced, setDebounced] = useState(w);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(w), 200);
    return () => clearTimeout(t);
  }, [w]);
  const total = Object.values(w).reduce((a, b) => a + b, 0);
  const { data: preview } = useQuery({
    queryKey: ["preview", debounced],
    queryFn: () => apiSend<{ id: number; title: string; company: string; pct: number }[]>("/settings/preview", "POST", { weights: debounced }),
  });
  const dirty = JSON.stringify(w) !== JSON.stringify(data.settings.weights);
  const save = useMutation({
    mutationFn: () => apiSend<{ reweighted: number }>("/settings", "PUT", { ...data.settings, weights: w }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast(`Weights saved. ${r.reweighted} scored jobs re-ranked.`);
    },
  });
  return (
    <>
      <Card>
        <b>Match weights</b>
        <div className="mb-2.5 text-xs text-muted-foreground">How much each part counts toward the match %. The preview re-ranks as you drag.</div>
        {(Object.keys(LABELS) as (keyof Weights)[]).map((k) => (
          <div key={k} className="my-2 grid grid-cols-[150px_1fr_36px] items-center gap-2.5">
            <span>{LABELS[k]}</span>
            <input type="range" min={0} max={100} step={5} value={w[k]} aria-label={LABELS[k]} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} />
            <b className="text-right">{w[k]}</b>
          </div>
        ))}
        <div className={`mt-1.5 text-xs ${total ? "text-muted-foreground" : "text-bad"}`}>
          {total ? `Total ${total}. Each part counts as its share of the total.` : "All weights are 0. Set at least one above 0."}
        </div>
        <div className="mt-2.5 flex gap-2">
          <Btn onClick={() => setW(DEFAULT_WEIGHTS)}>Reset to defaults</Btn>
          <Btn variant="primary" disabled={!dirty || !total || save.isPending} onClick={() => save.mutate()}>
            Save weights
          </Btn>
        </div>
      </Card>
      <Card>
        <b>Top 5 with these weights</b>
        <div className="mb-2 text-xs text-muted-foreground">Live preview</div>
        {preview?.length ? (
          preview.map((j, i) => {
            const tone = scoreTone(j.pct);
            return (
              <div key={j.id} className="flex items-center gap-2.5 border-b border-border py-1.5">
                <span className="w-4 text-faint">{i + 1}</span>
                <Chip tone={tone === "hi" ? "ok" : tone === "mid" ? "warn" : "plain"} className="w-11 justify-center">
                  {Math.round(j.pct)}%
                </Chip>
                <span className="flex-1">
                  {j.title} <span className="text-muted-foreground">· {j.company}</span>
                </span>
              </div>
            );
          })
        ) : (
          <div className="text-xs text-faint">No scored jobs yet.</div>
        )}
      </Card>
    </>
  );
}

function SearchesCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["searches"], queryFn: () => apiGet<SavedSearch[]>("/searches") });
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const add = useMutation({
    mutationFn: () => apiSend<SavedSearch>("/searches", "POST", { text }),
    onSuccess: () => (setText(""), qc.invalidateQueries({ queryKey: ["searches"] })),
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  async function remove(s: SavedSearch) {
    setError("");
    await apiSend(`/searches/${s.id}/archive`, "POST");
    qc.invalidateQueries({ queryKey: ["searches"] });
    toast(`Removed “${s.label ?? s.query}”`, async () => {
      await apiSend(`/searches/${s.id}/restore`, "POST");
      qc.invalidateQueries({ queryKey: ["searches"] });
    });
  }
  return (
    <Card>
      <b>Saved searches</b>
      <div className="mb-2 text-xs text-muted-foreground">What the job-board scrapers look for. Write “role · place”.</div>
      {data?.map((s) => (
        <div key={s.id} className="flex items-center gap-2 border-b border-border py-1.5">
          <span className="flex-1">
            {s.query}
            {s.location && <span className="text-muted-foreground"> · {s.location}</span>}
          </span>
          <Btn variant="ghost" className="text-xs" onClick={() => remove(s)}>
            Remove
          </Btn>
        </div>
      ))}
      {data && !data.length && <div className="text-xs text-faint">No searches yet. Company boards and feeds still run without one.</div>}
      <div className="mt-2.5 flex gap-2">
        <input
          className="flex-1"
          value={text}
          placeholder="Django developer · Utrecht"
          onChange={(e) => (setText(e.target.value), setError(""))}
          onKeyDown={(e) => e.key === "Enter" && (text.trim() ? add.mutate() : setError("Enter a search, like “Django developer · Utrecht”."))}
        />
        <Btn onClick={() => (text.trim() ? add.mutate() : setError("Enter a search, like “Django developer · Utrecht”."))}>Add</Btn>
      </div>
      <div className="min-h-4 text-xs text-bad">{error}</div>
    </Card>
  );
}

function ScheduleCard({ data }: { data: SettingsResponse }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [s, setS] = useState<AppSettings>(data.settings);
  const save = useMutation({
    mutationFn: () => apiSend("/settings", "PUT", s),
    onSuccess: () => (qc.invalidateQueries(), toast("Saved")),
  });
  const hours = (k: keyof AppSettings["schedules"], label: string, options: number[]) => (
    <Field label={label}>
      <select value={s.schedules[k]} onChange={(e) => setS({ ...s, schedules: { ...s.schedules, [k]: Number(e.target.value) } })}>
        {options.map((h) => (
          <option key={h} value={h}>
            {h === 0 ? "Off" : h === 24 ? "Daily" : `Every ${h} hours`}
          </option>
        ))}
      </select>
    </Field>
  );
  const models = Array.from(new Set([s.llm_model ?? "", ...data.meta.models])).filter((m) => m && !m.startsWith("bge"));
  return (
    <Card>
      <b>Schedule and model</b>
      <div className="mt-2.5 grid grid-cols-1 gap-x-3 sm:grid-cols-2">
        {hours("jobspy", "Job boards (LinkedIn, Indeed, Glassdoor, Google, Naukri)", [6, 12, 24, 0])}
        {hours("ats", "Company job boards (Greenhouse, Lever, Ashby, Workday…)", [12, 24, 0])}
        {hours("feeds", "Remote feeds and public APIs", [6, 12, 24, 0])}
        {hours("gentle", "Small sites (Merojob, Kumarijob, career pages)", [8, 12, 24, 0])}
        <Field label="Scoring model">
          <select value={s.llm_model ?? ""} onChange={(e) => setS({ ...s, llm_model: e.target.value || null })}>
            <option value="">Default ({data.meta.models.find((m) => m.startsWith("qwen")) ?? "qwen2.5:14b"})</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Jobs the model scores per run (Stage A shortlist)">
          <select value={s.shortlist_size} onChange={(e) => setS({ ...s, shortlist_size: Number(e.target.value) })}>
            {[50, 100, 150, 300].map((n) => (
              <option key={n} value={n}>
                {n}
                {n === 150 ? " (default)" : n === 50 ? " (slow machine)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Currency">
          <select value={s.currency} onChange={(e) => setS({ ...s, currency: e.target.value })}>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
      </div>
      <Check checked={s.scheduler_enabled} onChange={(v) => setS({ ...s, scheduler_enabled: v })}>
        Run sources on this schedule while the app is open
      </Check>
      <div className="mt-2.5 flex justify-end">
        <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          Save
        </Btn>
      </div>
    </Card>
  );
}

function NotificationsCard({ data }: { data: SettingsResponse }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [s, setS] = useState<AppSettings>(data.settings);
  // The browser's permission isn't known during prerender; read it on the client only.
  const browserPermission = useSyncExternalStore(
    () => () => {},
    () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission),
    () => "default",
  );
  const [asked, setAsked] = useState<string | null>(null);
  const permission = asked ?? browserPermission;
  const setPermission = setAsked;
  const save = useMutation({
    mutationFn: () => apiSend("/settings", "PUT", s),
    onSuccess: () => (qc.invalidateQueries({ queryKey: ["settings"] }), toast("Saved")),
  });
  return (
    <Card>
      <b>Notifications</b>
      <div className="mb-2 text-xs text-muted-foreground">
        A desktop notification when a newly scored job reaches your threshold, while Job Matcher is open in a browser tab.
      </div>
      <Check checked={s.notify} onChange={(v) => setS({ ...s, notify: v })}>
        Notify me about new strong matches
      </Check>
      <div className="my-2 grid grid-cols-[1fr_44px] items-center gap-2.5">
        <input
          type="range"
          min={50}
          max={100}
          step={5}
          value={s.notify_threshold}
          aria-label="Notification threshold"
          onChange={(e) => setS({ ...s, notify_threshold: Number(e.target.value) })}
        />
        <b className="text-right">{s.notify_threshold}%</b>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {permission === "granted" ? (
          <Chip tone="ok">Browser notifications allowed</Chip>
        ) : permission === "unsupported" ? (
          <Chip>This browser can&apos;t show notifications</Chip>
        ) : permission === "denied" ? (
          <Chip tone="warn">Blocked: allow notifications for this site in your browser</Chip>
        ) : (
          <Btn onClick={async () => setPermission(await Notification.requestPermission())}>Allow desktop notifications</Btn>
        )}
        <div className="flex-1" />
        <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          Save
        </Btn>
      </div>
    </Card>
  );
}

function KeysCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({
    queryKey: ["sources"],
    queryFn: () => apiGet<{ sources: SourceRow[] }>("/sources"),
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const keyed = (data?.sources ?? []).filter((s) => s.key_help);
  async function save(source: SourceRow, value: string) {
    await apiSend("/settings/keys", "PUT", { source: source.name, value });
    setValues((v) => ({ ...v, [source.name]: "" }));
    qc.invalidateQueries({ queryKey: ["sources"] });
    toast(value ? `Saved the ${source.label} key` : `Removed the ${source.label} key`);
  }
  return (
    <Card>
      <b>Free API keys</b>
      <div className="mb-2 text-xs text-muted-foreground">
        Optional sources with a free sign-up and a daily limit. Keys stay in the local database.
      </div>
      {keyed.map((s) => (
        <div key={s.name} className="border-b border-border py-2">
          <div className="flex items-center gap-2">
            <span className="flex-1 font-medium">{s.label}</span>
            {s.has_key ? <Chip tone="ok">Key saved</Chip> : <Chip>No key</Chip>}
          </div>
          <div className="text-xs text-faint">{s.key_help}</div>
          <div className="mt-1.5 flex gap-2">
            <input
              type="password"
              autoComplete="off"
              className="flex-1"
              aria-label={`${s.label} key`}
              placeholder={s.has_key ? "Paste a new key to replace it" : "Paste the key"}
              value={values[s.name] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [s.name]: e.target.value }))}
            />
            <Btn disabled={!(values[s.name] ?? "").trim()} onClick={() => save(s, values[s.name].trim())}>
              Save
            </Btn>
            {s.has_key && (
              <Btn variant="ghost" onClick={() => save(s, "")}>
                Remove
              </Btn>
            )}
          </div>
        </div>
      ))}
    </Card>
  );
}

function DataCard({ data }: { data: SettingsResponse }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [geoTask, setGeoTask] = useState<number | null>(null);
  const geo = useTask(geoTask);
  const fx = useMutation({
    mutationFn: () => apiSend<{ currencies: number }>("/settings/fx", "POST"),
    onSuccess: (r) => (qc.invalidateQueries({ queryKey: ["settings"] }), toast(`ECB rates updated (${r.currencies} currencies)`)),
    onError: (e: Error) => toast(`Couldn't reach the ECB: ${e.message}`),
  });
  return (
    <Card>
      <b>Reference data</b>
      <div className="mb-2 text-xs text-muted-foreground">Free, downloaded once and kept on this computer.</div>
      <div className="flex items-center gap-2 border-b border-border py-1.5">
        <span className="flex-1">GeoNames cities (locations and aliases)</span>
        {data.meta.geonames || geo.data?.status === "done" ? (
          <Chip tone="ok">Ready</Chip>
        ) : (
          <Btn className="text-xs" disabled={geo.data?.status === "running"} onClick={async () => setGeoTask((await apiSend<{ task_id: number }>("/settings/geonames", "POST")).task_id)}>
            {geo.data?.status === "running" ? "Downloading…" : "Download (3 MB)"}
          </Btn>
        )}
      </div>
      <div className="flex items-center gap-2 py-1.5">
        <span className="flex-1">ECB exchange rates {data.meta.fx_date && <span className="text-faint">· {data.meta.fx_date}</span>}</span>
        <Btn className="text-xs" disabled={fx.isPending} onClick={() => fx.mutate()}>
          Refresh
        </Btn>
      </div>
    </Card>
  );
}

export function SettingsView() {
  const { data } = useSettings();
  return (
    <section>
      <div className="mb-[18px] flex items-center">
        <h1 className="text-[22px] font-semibold">Settings</h1>
      </div>
      {!data ? (
        <Card className="text-muted-foreground">Loading…</Card>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
          <WeightsCard data={data} />
          <SearchesCard />
          <PreferencesForm />
          <ScheduleCard data={data} />
          <NotificationsCard data={data} />
          <KeysCard />
          <DataCard data={data} />
        </div>
      )}
    </section>
  );
}
