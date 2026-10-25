// Calls go to /api/*, which next.config.ts rewrites to the FastAPI backend.
"use client";

import { useQuery } from "@tanstack/react-query";

export type Health = {
  status: "ok" | "degraded";
  db: { ok: boolean; sqlite_vec_version: string | null; schema_version: number | null; error: string | null };
  ollama: {
    ok: boolean;
    url: string;
    version: string | null;
    llm_model: string;
    embed_model: string;
    llm_model_ready: boolean;
    embed_model_ready: boolean;
    error: string | null;
  };
};

export type MatchSummary = {
  pct: number | null;
  status: "scored" | "unscored" | "pending";
  error: string | null;
  stale_version: boolean;
  version_label: string | null;
  matched: string[];
  missing: string[];
};

export type AppStatus = "saved" | "applied" | "interviewing" | "offer" | "rejected" | "withdrawn" | "archived";

export type JobCard = {
  id: number;
  title: string;
  company: string;
  location: string;
  countries: string[];
  work_mode: string | null;
  job_type: string | null;
  salary_text: string | null;
  salary_annual_min: number | null;
  salary_annual_max: number | null;
  posted_at: string;
  first_seen_at: string;
  last_seen_at: string;
  status: "active" | "expired" | "stale";
  expired_reason: string | null;
  visa_sponsorship: "yes" | "no" | null;
  relocation: boolean;
  sources: string[];
  match: MatchSummary;
  application: { id: number; status: AppStatus; applied_at: string | null } | null;
  hidden: boolean;
};

export type JobList = { total: number; items: JobCard[] };

export type SubScores = { required: number | null; nice: number | null; seniority: number | null; domain: number | null; location: number | null };

export type JobDetail = {
  id: number;
  title: string;
  company_name: string;
  description: string;
  job_type: string | null;
  work_mode: string | null;
  salary_text: string | null;
  salary_annual_min: number | null;
  salary_annual_max: number | null;
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  valid_through: string | null;
  status: "active" | "expired" | "stale";
  expired_reason: string | null;
  visa_sponsorship: "yes" | "no" | null;
  relocation: number | null;
  language_reqs: string[] | null;
  remote_eligibility: { remote?: boolean; worldwide?: boolean; countries?: string[]; regions?: string[] } | null;
  extra: Record<string, unknown> | null;
  locations: { raw: string; city: string | null; region: string | null; country_code: string | null; resolved: number }[];
  sources: { source: string; url: string; status: string; first_seen_at: string; last_seen_at: string }[];
  match: null | {
    status: "scored" | "unscored";
    pct: number | null;
    sub_scores: SubScores;
    location_reason: string | null;
    matched: string[];
    missing: string[];
    explanation: string | null;
    error: string | null;
    model: string | null;
    scored_at: string;
    version_label: string;
    stale_version: boolean;
  };
  application: { id: number; status: AppStatus; applied_at: string | null; notes: string } | null;
  hidden: boolean;
};

export type Application = {
  id: number;
  job_id: number;
  status: AppStatus;
  title: string;
  company: string;
  url: string | null;
  match_pct: number | null;
  applied_at: string | null;
  days_since_applied: number | null;
  follow_up: boolean;
  posting_expired: boolean;
  expired_reason: string | null;
  notes: string;
  status_changed_at: string;
  updated_at: string;
};

export type TaskStep = { step: string; state: "pending" | "running" | "done" | "error"; detail?: string };
export type Task<R = Record<string, unknown>> = {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: TaskStep[];
  result: R | null;
  error: string | null;
};

export type Skill = { name: string; years: number | null; last_used: number | null; sources: string[] };
export type Language = { language: string; level: "native" | "fluent" | "professional" | "basic" | "none" };
export type Profile = {
  current_title: string | null;
  seniority: string | null;
  years_experience: number | null;
  summary: string | null;
  skills: Skill[];
  roles: string[];
  domains: string[];
  languages: Language[];
};
export type ProfileVersion = {
  id: number;
  label: string | null;
  status: "draft" | "saved" | "archived";
  is_active: boolean;
  created_at: string;
  profile: Profile;
  inputs: { resume_filename: string | null; github: string | null; portfolio_url: string | null; linkedin: boolean; llm_error: string | null };
  diff?: {
    against: string | null;
    added: string[];
    removed: string[];
    changed: { field: string; from: unknown; to: unknown }[];
  };
  rescore_task_id?: number | null;
};

export type Weights = { required: number; nice: number; seniority: number; domain: number; location: number };
export type JobType = "full-time" | "contract" | "freelance" | "part-time" | "internship";
export type AppSettings = {
  weights: Weights;
  currency: string;
  home_country: string | null;
  home_city: string | null;
  target_countries: string[];
  open_to_relocation: boolean;
  needs_visa: boolean;
  job_types: JobType[];
  min_salary: number | null;
  llm_model: string | null;
  shortlist_size: number;
  notify_threshold: number;
  notify: boolean;
  schedules: { jobspy: number; ats: number; feeds: number; gentle: number };
  scheduler_enabled: boolean;
};
export type SettingsResponse = {
  settings: AppSettings;
  meta: {
    models: string[];
    geonames: boolean;
    countries: { code: string; name: string }[];
    regions: string[];
    city_groups: string[];
    fx_date: string | null;
  };
};

export type SourceRow = {
  name: string;
  label: string;
  via: string;
  kind: string;
  group: string;
  needs_searches: boolean;
  platform: string | null;
  health: "ok" | "warn" | "broken" | "paused" | "never";
  detail: string | null;
  paused: boolean;
  paused_until: string | null;
  last_run_at: string | null;
  found: number | null;
  new: number | null;
  history: number[];
  budget_used: number;
  budget: number;
  running_task_id: number | null;
};

export type Company = { id: number; name: string; platform: string; slug: string; careers_url: string | null; status: string; last_crawled_at: string | null };
export type SavedSearch = { id: number; query: string; location: string | null; label: string | null; archived: boolean };
export type Summary = {
  profile: { id: number; label: string } | null;
  jobs_active: number;
  applications_open: number;
  sources_attention: number;
  last_scrape_at: string | null;
  scoring_task_id: number | null;
};

export type Insights = {
  has_profile: boolean;
  currency: string;
  stats: { active_matches: number; matches_80: number; applied_30d: number; response_rate: number | null };
  missing_skills: { skill: string; share: number }[];
  top_count: number;
  funnel: { label: string; value: number }[];
  per_day: { day: string; count: number }[];
  salary_by_place: { place: string; jobs: number; low: number; high: number }[];
  best_sources: { source: string; jobs: number }[];
};

export class ApiError extends Error {
  status: number;
  fields: Record<string, string>;
  constructor(status: number, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

async function parse<T>(response: Response, path: string): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  let message = `${path} returned ${response.status}`;
  let fields: Record<string, string> = {};
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") message = detail;
    else if (detail?.fields) {
      fields = detail.fields;
      message = Object.values(fields).join(" ");
    } else if (Array.isArray(detail)) {
      message = detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    }
  } catch {
    // Non-JSON error bodies keep the status message.
  }
  throw new ApiError(response.status, message, fields);
}

export async function apiGet<T>(path: string): Promise<T> {
  return parse<T>(await fetch(`/api${path}`, { cache: "no-store" }), path);
}

export async function apiSend<T>(path: string, method: "POST" | "PUT" | "PATCH", body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  return parse<T>(await fetch(`/api${path}`, init), path);
}

export function toQuery(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    if (Array.isArray(value)) value.forEach((v) => q.append(key, String(v)));
    else q.set(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Polls a background task until it finishes. */
export function useTask<R = Record<string, unknown>>(taskId: number | null | undefined) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => apiGet<Task<R>>(`/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "error" ? false : 1000;
    },
  });
}
