"use client";

import { Chip, ScoreBadge } from "@/components/bits";
import type { JobCard as Job } from "@/lib/api";
import { isToday, JOB_TYPE_LABEL, postedLabel, salaryRange, sourceLabel, STATUS_LABEL, WORK_MODE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

const OPEN = new Set(["saved", undefined]);

export function JobCard({
  job,
  currency,
  selected,
  onOpen,
  onSave,
  onApply,
  onHide,
}: {
  job: Job;
  currency: string;
  selected: boolean;
  onOpen: () => void;
  onSave: () => void;
  onApply: () => void;
  onHide: () => void;
}) {
  const app = job.application?.status;
  const salary = job.salary_annual_max ? salaryRange(job.salary_annual_min, job.salary_annual_max, currency) : job.salary_text;
  const isNew = isToday(job.first_seen_at) && job.status === "active";
  return (
    <div
      data-job-id={job.id}
      onClick={onOpen}
      className={cn(
        "mb-2.5 flex cursor-pointer gap-3.5 rounded-xl border border-border bg-card p-3.5 transition-colors hover:border-input",
        selected && "border-primary ring-1 ring-primary",
        job.status !== "active" && "opacity-60",
      )}
    >
      <ScoreBadge pct={job.match.pct} status={job.match.status} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[15px] font-semibold">{job.title}</span>
          {app && app !== "archived" && <Chip tone="acc">{STATUS_LABEL[app]}</Chip>}
          {job.status !== "active" && <Chip tone="bad">{job.status === "stale" ? "Stale" : "Expired"}</Chip>}
          {job.hidden && <Chip>Hidden</Chip>}
          {isNew && <Chip tone="ok">New</Chip>}
          {job.match.status === "unscored" && <Chip tone="warn">Unscored</Chip>}
          {job.match.stale_version && <Chip title="Scored against an older profile version">{job.match.version_label}</Chip>}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
          <b className="text-foreground">{job.company}</b>
          <span>{job.location}</span>
          {job.work_mode && <span>{WORK_MODE_LABEL[job.work_mode]}</span>}
          {job.job_type && <span>{JOB_TYPE_LABEL[job.job_type]}</span>}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
          <span>{salary || <span className="text-faint">Salary not shown</span>}</span>
          <span>{postedLabel(job.posted_at)}</span>
          <span>
            {sourceLabel(job.sources[0] ?? "")}
            {job.sources.length > 1 ? ` +${job.sources.length - 1}` : ""}
          </span>
          {job.visa_sponsorship === "yes" && <span className="text-ok">Visa sponsor</span>}
          {job.relocation && <span className="text-ok">Relocation help</span>}
        </div>
        {(job.match.matched.length > 0 || job.match.missing.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-1">
            {job.match.matched.slice(0, 4).map((s) => (
              <Chip key={`m${s}`} tone="ok">
                ✓ {s}
              </Chip>
            ))}
            {job.match.missing.slice(0, 4).map((s) => (
              <Chip key={`x${s}`} tone="bad">
                ✕ {s}
              </Chip>
            ))}
          </div>
        )}
      </div>
      <div className="ml-auto hidden flex-none flex-col gap-1.5 md:flex" onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={onSave} className="rounded-lg border border-input bg-card px-2.5 py-1 text-xs hover:bg-muted">
          {app === "saved" ? "★ Saved" : "☆ Save"}
        </button>
        <button
          type="button"
          onClick={onApply}
          className={cn(
            "rounded-lg border px-2.5 py-1 text-xs",
            OPEN.has(app) || app === "archived" ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card hover:bg-muted",
          )}
        >
          {OPEN.has(app) || app === "archived" ? "Mark applied" : STATUS_LABEL[app as string]}
        </button>
        <button type="button" onClick={onHide} className="rounded-lg px-2.5 py-1 text-xs hover:bg-muted">
          {job.hidden ? "Unhide" : "Hide"}
        </button>
      </div>
    </div>
  );
}
