"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Bar, Btn, Card, Chip, ScoreBadge } from "@/components/bits";
import { useJobActions } from "@/components/jobs/actions";
import { apiGet, apiSend, useTask, type JobDetail, type Weights } from "@/lib/api";
import { ago, JOB_TYPE_LABEL, postedLabel, salaryRange, sourceLabel, STATUS_LABEL, WORK_MODE_LABEL } from "@/lib/format";

const PARTS: { key: keyof Weights; label: string }[] = [
  { key: "required", label: "Required skills" },
  { key: "nice", label: "Nice to have" },
  { key: "seniority", label: "Seniority" },
  { key: "domain", label: "Domain" },
  { key: "location", label: "Location and language" },
];

function CoverLetter({ jobId }: { jobId: number }) {
  const [taskId, setTaskId] = useState<number | null>(null);
  const [edited, setEdited] = useState<string | null>(null);
  const { data: task } = useTask<{ letter: string }>(taskId);
  const text = edited ?? task?.result?.letter ?? "";
  const setText = setEdited;
  const start = useMutation({
    mutationFn: () => apiSend<{ task_id: number }>(`/jobs/${jobId}/cover-letter`, "POST"),
    onSuccess: (r) => setTaskId(r.task_id),
  });
  if (!taskId)
    return (
      <Btn onClick={() => start.mutate()} disabled={start.isPending}>
        Draft cover letter
      </Btn>
    );
  return (
    <Card className="mt-3 w-full">
      <div className="mb-1.5 text-xs text-muted-foreground">
        {task?.status === "error"
          ? task.error
          : text
            ? "Draft from your local model. Edit before you use it."
            : "Writing a draft with your local model…"}
      </div>
      {text && (
        <>
          <textarea className="min-h-48 w-full leading-relaxed" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="mt-2 flex gap-2">
            <Btn onClick={() => navigator.clipboard.writeText(text)}>Copy</Btn>
            <Btn variant="ghost" onClick={() => (setTaskId(null), setEdited(null))}>
              Discard
            </Btn>
          </div>
        </>
      )}
    </Card>
  );
}

export function JobDrawerBody({ jobId, weights, currency, onClose }: { jobId: number; weights?: Weights; currency: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { save, apply, hide } = useJobActions();
  const { data: job } = useQuery({ queryKey: ["job", jobId], queryFn: () => apiGet<JobDetail>(`/jobs/${jobId}`) });
  const [scoreTask, setScoreTask] = useState<number | null>(null);
  const scoring = useTask(scoreTask);
  useEffect(() => {
    if (scoring.data?.status === "done" || scoring.data?.status === "error") {
      qc.invalidateQueries({ queryKey: ["job", jobId] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [scoring.data, qc, jobId]);
  const rescore = useMutation({
    mutationFn: () => apiSend<{ task_id: number }>(`/jobs/${jobId}/score`, "POST"),
    onSuccess: (r) => setScoreTask(r.task_id),
  });

  if (!job) return <div className="text-muted-foreground">Loading…</div>;
  const target = { id: job.id, company: job.company_name, application: job.application, hidden: job.hidden };
  const app = job.application?.status;
  const open = !app || app === "saved";
  const m = job.match;
  const salary = job.salary_annual_max ? salaryRange(job.salary_annual_min, job.salary_annual_max, currency) : job.salary_text;
  const busy = rescore.isPending || (scoring.data && scoring.data.status === "running");
  const places = job.locations.map((l) => (l.city ? `${l.city}${l.country_code ? `, ${l.country_code}` : ""}` : l.country_code || l.raw));
  const remote = job.remote_eligibility;

  return (
    <div>
      <div className="flex justify-between gap-2.5">
        <div>
          <div className="text-[19px] font-bold">{job.title}</div>
          <div className="text-muted-foreground">
            {[job.company_name, job.work_mode && WORK_MODE_LABEL[job.work_mode], job.job_type && JOB_TYPE_LABEL[job.job_type]].filter(Boolean).join(" · ")}
          </div>
        </div>
        <Btn variant="ghost" aria-label="Close" onClick={onClose}>
          ✕
        </Btn>
      </div>
      <div className="my-3 flex flex-wrap gap-2">
        <Chip>{salary || "Salary not shown"}</Chip>
        <Chip>Posted {postedLabel(job.posted_at || job.first_seen_at).toLowerCase()}</Chip>
        {job.status === "active" ? (
          <Chip tone="ok">Active · last seen {ago(job.last_seen_at)}</Chip>
        ) : (
          <Chip tone="bad">
            {job.status === "stale" ? "Stale" : "Expired"} · {job.expired_reason}
          </Chip>
        )}
        {app && <Chip tone="acc">{STATUS_LABEL[app]}</Chip>}
        {job.visa_sponsorship && <Chip tone={job.visa_sponsorship === "yes" ? "ok" : "warn"}>{job.visa_sponsorship === "yes" ? "Sponsors visas" : "No visa sponsorship"}</Chip>}
        {job.relocation ? <Chip tone="ok">Relocation support</Chip> : null}
      </div>
      <div className="mb-3 text-xs text-muted-foreground">
        {places.length ? places.join(" · ") : "Location unclear"}
        {remote?.remote &&
          ` · Remote ${remote.worldwide ? "(worldwide)" : remote.countries?.length || remote.regions?.length ? `(${[...(remote.countries ?? []), ...(remote.regions ?? [])].join(", ")})` : "(scope unclear)"}`}
        {job.language_reqs?.length ? ` · Requires ${job.language_reqs.join(", ").toUpperCase()}` : ""}
      </div>

      <Card className="border-0 bg-muted">
        {m && m.status === "scored" ? (
          <>
            <div className="mb-1.5 flex items-center gap-3.5">
              <ScoreBadge pct={m.pct} />
              <div>
                <b>Match breakdown</b>
                <div className="text-xs text-muted-foreground">
                  Weighted by your settings · {m.version_label}
                  {m.stale_version && " (older profile version)"}
                </div>
              </div>
            </div>
            {PARTS.map(({ key, label }) => {
              const v = m.sub_scores[key];
              return (
                <div key={key} className="my-[7px] grid grid-cols-[150px_1fr_34px] items-center gap-2.5 text-[13px]">
                  <span className="text-muted-foreground">
                    {label} <span className="text-faint">({weights?.[key] ?? "–"})</span>
                  </span>
                  {v === null ? <span className="text-xs text-faint">Not stated in the posting</span> : <Bar value={v} />}
                  <span className="text-right">{v ?? "–"}</span>
                </div>
              );
            })}
            <p className="mt-2.5 mb-0">{m.explanation}</p>
            {m.location_reason && <p className="mt-1 mb-0 text-xs text-warn">{m.location_reason}</p>}
          </>
        ) : (
          <div>
            <b>{m?.status === "unscored" ? "Unscored" : "Not scored yet"}</b>
            <div className="mt-1 text-xs text-muted-foreground">
              {m?.status === "unscored"
                ? `The local model's answer didn't pass validation, so there's no number. ${m.error ?? ""}`
                : "Only the best embedding matches get an LLM score automatically. You can score this one now."}
            </div>
            <Btn className="mt-2" disabled={!!busy} onClick={() => rescore.mutate()}>
              {busy ? "Scoring… (about a minute)" : m?.status === "unscored" ? "Retry scoring" : "Score now"}
            </Btn>
            {scoring.data?.status === "error" && <div className="mt-1 text-xs text-bad">{scoring.data.error}</div>}
          </div>
        )}
      </Card>

      {m && (m.matched.length > 0 || m.missing.length > 0) && (
        <div className="mt-3.5">
          <div className="text-xs text-muted-foreground">Matched</div>
          <div className="mt-1 mb-2.5 flex flex-wrap gap-1">
            {m.matched.map((s) => (
              <Chip key={s} tone="ok">
                ✓ {s}
              </Chip>
            ))}
          </div>
          <div className="text-xs text-muted-foreground">Missing</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {m.missing.length ? (
              m.missing.map((s) => (
                <Chip key={s} tone="bad">
                  ✕ {s}
                </Chip>
              ))
            ) : (
              <span className="text-xs text-faint">Nothing missing</span>
            )}
          </div>
        </div>
      )}

      <div className="mt-3.5">
        <div className="text-xs text-muted-foreground">Found on</div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {job.sources.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="no-underline">
              <Chip tone={s.status === "listed" ? "acc" : "plain"} title={s.status === "gone" ? "No longer listed there" : `Seen ${ago(s.last_seen_at)}`}>
                {sourceLabel(s.source)} ↗
              </Chip>
            </a>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Btn onClick={() => save(target)}>{app === "saved" ? "★ Saved" : "☆ Save"}</Btn>
        {open ? (
          <Btn variant="primary" onClick={() => apply(target)}>
            Mark applied
          </Btn>
        ) : (
          <Link href="/applications" className="rounded-lg border border-input bg-card px-3 py-1.5 text-sm hover:bg-muted">
            View in applications
          </Link>
        )}
        <CoverLetter key={job.id} jobId={job.id} />
        <Btn variant="ghost" onClick={() => hide(target)}>
          {job.hidden ? "Unhide" : "Not interested"}
        </Btn>
      </div>

      <div className="mt-4 border-t border-border pt-3.5 text-[13px] whitespace-pre-line text-muted-foreground">
        <b className="text-foreground">About the role</b>
        {"\n"}
        {job.description || "The source didn't include a description. Open the posting above."}
      </div>
    </div>
  );
}
