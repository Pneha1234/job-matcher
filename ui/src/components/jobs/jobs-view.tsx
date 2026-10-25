"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { Btn, Card, Check, Chip, Drawer, Empty, FilterGroup, Kbd } from "@/components/bits";
import { useJobActions } from "@/components/jobs/actions";
import { ImportPanel } from "@/components/jobs/import-dialog";
import { JobCard } from "@/components/jobs/job-card";
import { JobDrawerBody } from "@/components/jobs/job-drawer";
import { CountryPicker, useSettings } from "@/components/profile/preferences";
import { apiGet, apiSend, toQuery, useTask, type JobCard as Job, type JobList, type Summary } from "@/lib/api";
import { JOB_TYPE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

type Filters = {
  min_match: number;
  include_unscored: boolean;
  q: string;
  types: string[];
  countries: string[];
  regions: string[];
  cities: string[];
  remote_eligible: boolean;
  location_unclear: boolean;
  salary_only: boolean;
  salary_min: number | null;
  posted_days: number | null;
  hide_applied: boolean;
  show_expired: boolean;
  show_hidden: boolean;
  visa: boolean;
  relocation: boolean;
  sort: string;
};

const DEFAULTS: Filters = {
  min_match: 60,
  include_unscored: true,
  q: "",
  types: [],
  countries: [],
  regions: [],
  cities: [],
  remote_eligible: false,
  location_unclear: true,
  salary_only: false,
  salary_min: null,
  posted_days: 30,
  hide_applied: false,
  show_expired: false,
  show_hidden: false,
  visa: false,
  relocation: false,
  sort: "match",
};

const VIEWS: { key: string; label: string; apply: Partial<Filters> & { new_today?: boolean; status?: string[] } }[] = [
  { key: "all", label: "All", apply: {} },
  { key: "top", label: "80%+ not applied", apply: { min_match: 80, include_unscored: false, hide_applied: true } },
  { key: "new", label: "New today", apply: { new_today: true } },
  { key: "remote", label: "Remote I'm eligible for", apply: { remote_eligible: true, location_unclear: false } },
  { key: "contract", label: "Contract", apply: { types: ["contract", "freelance"] } },
  { key: "saved", label: "Saved", apply: { status: ["saved"], min_match: 0 } },
];

const POSTED = [
  { v: 1, label: "24h" },
  { v: 7, label: "7d" },
  { v: 30, label: "30d" },
  { v: null, label: "Any" },
];
const PAGE = 50;
// The region shortcuts from docs/PLAN.md; any country is still one pick away below them.
const SHORTCUTS = ["EU", "DACH", "Nordics", "UK & Ireland", "North America", "GCC", "APAC",
  "India metros", "Kathmandu Valley", "South Asia"];

/** Opens the drawer for /jobs?job=ID (links from notifications and the digest). */
function JobLinkOpener({ onOpen }: { onOpen: (id: number) => void }) {
  const params = useSearchParams();
  const id = Number(params.get("job"));
  useEffect(() => {
    if (id) onOpen(id);
  }, [id, onOpen]);
  return null;
}

export function JobsView() {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: settingsData } = useSettings();
  const settings = settingsData?.settings;
  const currency = settings?.currency ?? "EUR";
  const { data: summary } = useQuery({ queryKey: ["summary"], queryFn: () => apiGet<Summary>("/summary"), refetchInterval: 20_000 });
  const scoring = useTask(summary?.scoring_task_id);

  const [f, setF] = useState<Filters>(DEFAULTS);
  const [view, setView] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  const [selected, setSelected] = useState<number | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [importing, setImporting] = useState(false);
  // When the page was opened, for the "new jobs" banner. A query function runs only in the
  // browser, never during prerender, so the time is read on each visit.
  const { data: openedAt } = useQuery({
    queryKey: ["jobs-opened-at"],
    queryFn: async () => new Date().toISOString(),
    staleTime: Infinity,
  });
  const [qText, setQText] = useState("");
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => (setF((p) => ({ ...p, [k]: v })), setLimit(PAGE));

  useEffect(() => {
    const t = setTimeout(() => set("q", qText), 250);
    return () => clearTimeout(t);
  }, [qText]);

  const params = useMemo(() => {
    const preset = VIEWS.find((v) => v.key === view)?.apply ?? {};
    return { ...f, ...preset, limit };
  }, [f, view, limit]);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["jobs", params],
    queryFn: () => apiGet<JobList>(`/jobs${toQuery(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: scoring.data?.status === "running" ? 15_000 : false,
  });
  const list = useMemo(() => data?.items ?? [], [data]);

  const { data: fresh } = useQuery({
    queryKey: ["jobs-new", openedAt],
    queryFn: () => apiGet<{ count: number }>(`/jobs/new-count${toQuery({ since: openedAt })}`),
    enabled: !!openedAt,
    refetchInterval: 60_000,
  });
  const { data: today } = useQuery({
    queryKey: ["jobs", "today-count"],
    queryFn: () => apiGet<JobList>(`/jobs${toQuery({ new_today: true, limit: 1 })}`),
  });

  const { save, apply, hide } = useJobActions();
  const openJob = useCallback((id: number) => {
    setSelected(id);
    setDrawer(true);
  }, []);
  const startScoring = useCallback(async () => {
    await apiSend("/scoring/run", "POST");
    qc.invalidateQueries({ queryKey: ["summary"] });
  }, [qc]);
  const onApply = useCallback(
    (job: Job) => {
      const s = job.application?.status;
      if (!s || s === "saved" || s === "archived") apply(job);
      else router.push("/applications");
    },
    [apply, router],
  );

  // Keyboard: j/k move, Enter open, s save, a applied, x hide, Esc close. The listener is
  // an effect, so it detaches while this page is hidden by navigation.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement as HTMLElement | null;
      if (el && (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) || el.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const items = list;
      const i = items.findIndex((j) => j.id === selected);
      const job = items[i];
      if (e.key === "j" || e.key === "k") {
        const n = e.key === "j" ? Math.min(items.length - 1, i + 1) : Math.max(0, i - 1);
        const next = items[n];
        if (next) {
          setSelected(next.id);
          document.querySelector(`[data-job-id="${next.id}"]`)?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "Enter" && job) setDrawer(true);
      else if (e.key === "Escape") setDrawer(false);
      else if (e.key === "s" && job) save(job);
      else if (e.key === "a" && job) onApply(job);
      else if (e.key === "x" && job) hide(job);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, selected, save, hide, onApply]);

  const meta = settingsData?.meta;
  const reset = () => (setF(DEFAULTS), setView("all"), setQText(""), setLimit(PAGE));
  const noProfile = summary && !summary.profile;
  const noJobs = summary && summary.jobs_active === 0;

  return (
    <section>
      <div className="mb-[18px] flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold">Jobs</h1>
        {!!today?.total && <Chip tone="acc">{today.total} new today</Chip>}
        <div className="flex-1" />
        {scoring.data?.status === "running" ? (
          <span className="text-xs text-faint">
            {scoring.data.progress.find((p) => p.state === "running")?.step ?? "Scoring"} ·{" "}
            {scoring.data.progress.find((p) => p.state === "running")?.detail ?? "starting"}
          </span>
        ) : (
          summary?.profile && (
            <Btn variant="ghost" className="text-xs" onClick={startScoring}>
              Score new jobs
            </Btn>
          )
        )}
        <span className="text-xs text-faint">
          {summary?.profile ? (
            <>
              Scored against <b>{summary.profile.label}</b>
            </>
          ) : (
            "No profile yet"
          )}
        </span>
        <Btn onClick={() => setImporting((v) => !v)}>+ Add a job</Btn>
      </div>

      {noProfile && (
        <Card className="mb-3 flex flex-wrap items-center gap-3 border-0 bg-brand-soft text-brand-soft-foreground">
          <span className="flex-1">Jobs are listed but not scored. Set up your profile to get match percentages.</span>
          <Link href="/profile" className="font-semibold">
            Set up profile →
          </Link>
        </Card>
      )}
      {!!fresh?.count && (
        <button
          type="button"
          className="mb-3 flex w-full items-center gap-2.5 rounded-[10px] bg-brand-soft px-3 py-2 text-left text-brand-soft-foreground"
          onClick={() => {
            qc.setQueryData(["jobs-opened-at"], new Date().toISOString());
            qc.invalidateQueries({ queryKey: ["jobs"] });
          }}
        >
          {fresh.count} new jobs found since you opened this page. Show them
        </button>
      )}
      {importing && (
        <ImportPanel
          onClose={() => setImporting(false)}
          onImported={(id) => {
            setImporting(false);
            setSelected(id);
            setDrawer(true);
          }}
        />
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4 self-start lg:sticky lg:top-5">
          <FilterGroup title="Min match" aside={`${f.min_match}%`}>
            <input type="range" min={0} max={100} step={5} value={f.min_match} onChange={(e) => set("min_match", Number(e.target.value))} className="w-full" aria-label="Minimum match" />
            <Check checked={f.include_unscored} onChange={(v) => set("include_unscored", v)}>
              Include jobs not scored yet
            </Check>
          </FilterGroup>
          <FilterGroup title="Location">
            <div className="mb-1.5 flex flex-wrap gap-1">
              {SHORTCUTS.filter((r) => meta?.regions.includes(r) || meta?.city_groups.includes(r)).map((r) => {
                const isCity = meta?.city_groups.includes(r);
                const on = isCity ? f.cities.includes(r) : f.regions.includes(r);
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() =>
                      isCity
                        ? set("cities", on ? f.cities.filter((x) => x !== r) : [...f.cities, r])
                        : set("regions", on ? f.regions.filter((x) => x !== r) : [...f.regions, r])
                    }
                    className={cn("rounded-full border px-2 py-0.5 text-xs", on ? "border-foreground bg-foreground text-background" : "border-input bg-card")}
                  >
                    {r}
                  </button>
                );
              })}
            </div>
            {meta && <CountryPicker countries={meta.countries} value={f.countries} onChange={(v) => set("countries", v)} placeholder="Add a country" />}
            <Check checked={f.remote_eligible} onChange={(v) => set("remote_eligible", v)}>
              Remote I&apos;m eligible for
            </Check>
            {f.remote_eligible && !settings?.home_country && (
              <div className="text-xs text-warn">
                Set where you live in <Link href="/settings" className="underline">Settings</Link> first.
              </div>
            )}
            <Check checked={f.location_unclear} onChange={(v) => set("location_unclear", v)}>
              Include &quot;location unclear&quot;
            </Check>
            <Check checked={f.visa} onChange={(v) => set("visa", v)}>
              Sponsors visas
            </Check>
            <Check checked={f.relocation} onChange={(v) => set("relocation", v)}>
              Relocation support
            </Check>
          </FilterGroup>
          <FilterGroup title="Job type">
            {Object.entries(JOB_TYPE_LABEL).map(([k, label]) => (
              <Check key={k} checked={f.types.includes(k)} onChange={(on) => set("types", on ? [...f.types, k] : f.types.filter((t) => t !== k))}>
                {label}
              </Check>
            ))}
            <div className="text-xs text-faint">None ticked shows every type.</div>
          </FilterGroup>
          <FilterGroup title="Salary">
            <Check checked={f.salary_only} onChange={(v) => set("salary_only", v)}>
              Only jobs that show salary
            </Check>
            <div className="mt-1.5 flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Min {currency}</span>
              <input
                type="number"
                step={5000}
                min={0}
                className="w-full"
                value={f.salary_min ?? ""}
                placeholder="per year"
                onChange={(e) => set("salary_min", e.target.value ? Number(e.target.value) : null)}
              />
            </div>
          </FilterGroup>
          <FilterGroup title="Posted">
            <div className="flex overflow-hidden rounded-lg border border-input">
              {POSTED.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => set("posted_days", p.v)}
                  className={cn("flex-1 py-1 text-[13px]", f.posted_days === p.v ? "bg-primary text-primary-foreground" : "bg-card hover:bg-muted")}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </FilterGroup>
          <FilterGroup title="Status">
            <Check checked={f.hide_applied} onChange={(v) => set("hide_applied", v)}>
              Hide applied
            </Check>
            <Check checked={f.show_expired} onChange={(v) => set("show_expired", v)}>
              Show expired
            </Check>
            <Check checked={f.show_hidden} onChange={(v) => set("show_hidden", v)}>
              Show hidden
            </Check>
          </FilterGroup>
          <Btn onClick={reset}>Reset filters</Btn>
        </div>

        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap gap-1.5">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                type="button"
                onClick={() => (setView(v.key), setLimit(PAGE))}
                className={cn("rounded-full border px-3 py-1 text-[13px]", view === v.key ? "border-foreground bg-foreground text-background" : "border-input bg-card hover:bg-muted")}
              >
                {v.label}
              </button>
            ))}
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-2.5">
            <input type="text" value={qText} onChange={(e) => setQText(e.target.value)} placeholder="Search title, company or skill" className="min-w-[180px] flex-1" aria-label="Search" />
            <select value={f.sort} onChange={(e) => set("sort", e.target.value)} aria-label="Sort">
              <option value="match">Best match</option>
              <option value="new">Newest</option>
              <option value="salary">Highest salary</option>
            </select>
            <span className="text-xs text-faint">{data ? `${data.total.toLocaleString()} jobs` : ""}{isFetching ? " · updating" : ""}</span>
          </div>

          {isError && <Empty title="Couldn't load jobs">Is the API running? Start everything with make dev.</Empty>}
          {data && !list.length && noJobs && (
            <Empty title="No jobs yet">
              <p>Run the free sources to fill this list. The first run takes a few minutes; scrapers wait between requests.</p>
              <Link href="/sources" className="font-semibold text-primary">
                Go to Sources →
              </Link>
            </Empty>
          )}
          {data && !list.length && !noJobs && (
            <Empty title="No jobs match these filters">
              <p>Try a lower match threshold or a wider posted window.</p>
              <Btn onClick={() => (setF((p) => ({ ...p, min_match: 50, posted_days: 30 })), setView("all"))}>Lower min match to 50% and show 30 days</Btn>
            </Empty>
          )}
          {list.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              currency={currency}
              selected={job.id === selected}
              onOpen={() => (setSelected(job.id), setDrawer(true))}
              onSave={() => save(job)}
              onApply={() => onApply(job)}
              onHide={() => hide(job)}
            />
          ))}
          {data && data.total > list.length && (
            <Btn className="w-full" onClick={() => setLimit((l) => l + PAGE)}>
              Show more ({(data.total - list.length).toLocaleString()} left)
            </Btn>
          )}
          <div className="mt-2 text-xs text-faint">
            Keyboard: <Kbd>j</Kbd>/<Kbd>k</Kbd> move · <Kbd>Enter</Kbd> open · <Kbd>s</Kbd> save · <Kbd>a</Kbd> applied · <Kbd>x</Kbd> hide · <Kbd>Esc</Kbd> close
          </div>
        </div>
      </div>

      <Suspense fallback={null}>
        <JobLinkOpener onOpen={openJob} />
      </Suspense>
      <Drawer open={drawer && selected !== null} onClose={() => setDrawer(false)} label="Job details">
        {selected !== null && <JobDrawerBody jobId={selected} weights={settings?.weights} currency={currency} onClose={() => setDrawer(false)} />}
      </Drawer>
    </section>
  );
}
