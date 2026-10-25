"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Btn, Card, Chip, Progress } from "@/components/bits";
import { PreferencesForm } from "@/components/profile/preferences";
import { DiffCard, ProfileEditor } from "@/components/profile/review";
import { useToast } from "@/components/toast";
import { apiGet, apiSend, ApiError, useTask, type Profile, type ProfileVersion } from "@/lib/api";
import { cn } from "@/lib/utils";

type Stage = "overview" | "upload" | "parsing" | "review" | "preferences";
const MAX_BYTES = 10 * 1024 * 1024;
const GITHUB = /^(https?:\/\/)?(www\.)?github\.com\/[A-Za-z0-9-]{1,39}\/?$/i;
const URL_OK = /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i;

function Steps({ stage }: { stage: Stage }) {
  const at = { upload: 1, parsing: 1, review: 2, preferences: 3, overview: 0 }[stage];
  const steps = ["Resume and links", "Review profile", "Preferences"];
  return (
    <div className="mb-[18px] flex flex-wrap gap-[22px]">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = at > n;
        const on = at === n;
        return (
          <div key={label} className={cn("flex items-center gap-2 text-[13px] text-faint", on && "font-semibold text-foreground", done && "text-ok")}>
            <span
              className={cn(
                "grid size-6 place-items-center rounded-full border border-input text-xs",
                on && "border-primary text-primary",
                done && "border-ok bg-ok-bg",
              )}
            >
              {done ? "✓" : n}
            </span>
            {label}
          </div>
        );
      })}
    </div>
  );
}

function FileRow({ file, onRemove }: { file: File; onRemove: () => void }) {
  return (
    <div className="mt-2.5 flex items-center gap-2.5 rounded-lg bg-muted p-2.5">
      <span className="text-xl" aria-hidden>
        📄
      </span>
      <div className="flex-1">
        <div className="font-semibold">{file.name}</div>
        <div className="text-xs text-faint">{Math.round(file.size / 1024)} KB</div>
      </div>
      <Btn variant="ghost" aria-label="Remove file" onClick={onRemove}>
        ✕
      </Btn>
    </div>
  );
}

function UploadStage({ onStarted }: { onStarted: (taskId: number) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [zip, setZip] = useState<File | null>(null);
  const [github, setGithub] = useState("");
  const [portfolio, setPortfolio] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);

  function pick(f: File | undefined) {
    if (!f) return;
    if (!/\.(pdf|docx)$/i.test(f.name)) return setErrors((e) => ({ ...e, resume: "That file type isn't supported. Upload a PDF or DOCX." }));
    if (f.size > MAX_BYTES) return setErrors((e) => ({ ...e, resume: "That file is over 10 MB." }));
    setErrors((e) => ({ ...e, resume: "" }));
    setFile(f);
  }

  const parse = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("resume", file as File);
      form.append("github", github);
      form.append("portfolio", portfolio);
      if (zip) form.append("linkedin", zip);
      return apiSend<{ task_id: number }>("/profile/parse", "POST", form);
    },
    onSuccess: (r) => onStarted(r.task_id),
    onError: (e: Error) => setErrors(e instanceof ApiError && Object.keys(e.fields).length ? e.fields : { form: e.message }),
  });

  function submit() {
    const next: Record<string, string> = {};
    if (!file) next.resume = "Add your resume first.";
    if (github.trim() && !GITHUB.test(github.trim())) next.github = "Enter a GitHub profile URL, like github.com/yourname.";
    if (portfolio.trim() && !URL_OK.test(portfolio.trim())) next.portfolio = "Enter a valid website address.";
    setErrors(next);
    if (!Object.keys(next).length) parse.mutate();
  }

  return (
    <div className="max-w-[720px]">
      <Card className="mb-3.5">
        <b>Your resume</b>
        {file ? (
          <FileRow
            file={file}
            onRemove={() => {
              setFile(null);
              if (fileInput.current) fileInput.current.value = "";
            }}
          />
        ) : (
          <label
            htmlFor="resume-file"
            onDragOver={(e) => (e.preventDefault(), setOver(true))}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              pick(e.dataTransfer.files[0]);
            }}
            className={cn("mt-2.5 block cursor-pointer rounded-xl border-2 border-dashed border-input p-[30px] text-center", over && "border-primary bg-brand-soft")}
          >
            <div className="text-[28px]" aria-hidden>
              ⇧
            </div>
            <div>
              Drop your resume here or <span className="text-primary">browse</span>
            </div>
            <div className="text-xs text-faint">PDF or DOCX, up to 10 MB. It stays on this computer.</div>
          </label>
        )}
        <input ref={fileInput} id="resume-file" type="file" accept=".pdf,.docx" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <div className="mt-1 min-h-4 text-xs text-bad">{errors.resume}</div>
      </Card>
      <Card className="mb-3.5">
        <b>Profile links</b>
        <div className="text-xs text-muted-foreground">Optional. These add evidence for your skills.</div>
        <label className="mt-2.5 flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">GitHub</span>
          <input value={github} placeholder="github.com/yourname" onChange={(e) => (setGithub(e.target.value), setErrors((x) => ({ ...x, github: "" })))} />
          <span className="min-h-4 text-xs text-bad">{errors.github}</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Portfolio</span>
          <input value={portfolio} placeholder="yourname.dev" onChange={(e) => (setPortfolio(e.target.value), setErrors((x) => ({ ...x, portfolio: "" })))} />
          <span className="min-h-4 text-xs text-bad">{errors.portfolio}</span>
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">LinkedIn</span>
          <div className="flex flex-wrap items-center gap-2.5">
            <Btn onClick={() => zipInput.current?.click()}>{zip ? "Replace LinkedIn export" : "Upload LinkedIn export (.zip)"}</Btn>
            <span className={cn("text-xs", zip ? "text-ok" : "text-faint")}>
              {zip ? `${zip.name} added` : "LinkedIn → Settings → Data privacy → Get a copy of your data"}
            </span>
            {zip && (
              <Btn variant="ghost" aria-label="Remove LinkedIn export" onClick={() => setZip(null)}>
                ✕
              </Btn>
            )}
          </div>
          <input
            ref={zipInput}
            type="file"
            accept=".zip"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f && !/\.zip$/i.test(f.name)) setErrors((x) => ({ ...x, linkedin: "Upload the .zip LinkedIn emailed you." }));
              else if (f) {
                setZip(f);
                setErrors((x) => ({ ...x, linkedin: "" }));
              }
            }}
          />
          <span className="min-h-4 text-xs text-bad">{errors.linkedin}</span>
        </div>
      </Card>
      <div className="flex items-center justify-end gap-2">
        <span className="text-xs text-bad">{errors.form}</span>
        <Btn variant="primary" disabled={parse.isPending} onClick={submit}>
          {parse.isPending ? "Uploading…" : "Read my profile →"}
        </Btn>
      </div>
    </div>
  );
}

function ParsingStage({ taskId, onDone, onBack }: { taskId: number; onDone: (versionId: number) => void; onBack: () => void }) {
  const { data: task } = useTask<{ profile_version_id: number; llm_error: string | null }>(taskId);
  useEffect(() => {
    if (task?.status === "done" && task.result) onDone(task.result.profile_version_id);
  }, [task, onDone]);
  return (
    <Card className="max-w-[720px]">
      <b>Reading your profile</b>
      <div className="text-xs text-muted-foreground">
        Running on your local model. Nothing leaves this computer. Reading a full resume usually takes one to two minutes.
      </div>
      <Progress steps={task?.progress ?? []} />
      {task?.status === "error" && (
        <div className="mt-3 text-sm text-bad">
          {task.error} <Btn className="ml-2" onClick={onBack}>← Back</Btn>
        </div>
      )}
    </Card>
  );
}

function ReviewStage({ versionId, onBack, onSaved }: { versionId: number; onBack: () => void; onSaved: (v: ProfileVersion) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: version, refetch } = useQuery({
    queryKey: ["profile-version", versionId],
    queryFn: () => apiGet<ProfileVersion>(`/profile/versions/${versionId}`),
  });
  // Edits are tied to the version they started from, so a re-read replaces them.
  const [edits, setEdits] = useState<{ base: string; value: Profile } | null>(null);
  const [retryTask, setRetryTask] = useState<number | null>(null);
  const [error, setError] = useState("");
  const retry = useTask(retryTask);
  const retrying = !!retryTask && retry.data?.status !== "done" && retry.data?.status !== "error";
  useEffect(() => {
    if (retry.data?.status === "done") refetch();
  }, [retry.data?.status, refetch]);
  const base = version ? JSON.stringify(version.profile) : "";
  const draft = edits && edits.base === base ? edits.value : (version?.profile ?? null);
  const setDraft = (value: Profile) => setEdits({ base, value });

  const save = useMutation({
    mutationFn: async () => {
      await apiSend(`/profile/versions/${versionId}`, "PUT", draft);
      return apiSend<ProfileVersion>(`/profile/versions/${versionId}/save`, "POST");
    },
    onSuccess: (v) => {
      qc.invalidateQueries();
      toast(`${v.label} saved. Scoring jobs against it in the background.`);
      onSaved(v);
    },
    onError: (e: Error) => setError(e.message),
  });
  const reparse = useMutation({
    mutationFn: () => apiSend<{ task_id: number }>(`/profile/versions/${versionId}/reparse`, "POST"),
    onSuccess: (r) => setRetryTask(r.task_id),
  });

  if (!version || !draft) return <Card className="max-w-[720px] text-muted-foreground">Loading your draft…</Card>;
  const savedCount = qc.getQueryData<ProfileVersion[]>(["profile-versions"])?.filter((v) => v.status === "saved").length ?? 0;
  return (
    <div className="max-w-[720px]">
      {version.inputs.llm_error && (
        <Card className="mb-3.5 border-warn bg-warn-bg text-warn">
          <b>The local model couldn&apos;t read your resume.</b>
          <div className="mt-1 text-xs">{version.inputs.llm_error}</div>
          <div className="mt-1 text-xs">What GitHub and LinkedIn show is filled in below; nothing was guessed. Try again, or fill in the rest by hand.</div>
          <div className="mt-2 flex items-center gap-2">
            <Btn disabled={retrying || reparse.isPending} onClick={() => reparse.mutate()}>
              {retrying ? "Reading again…" : "Try again"}
            </Btn>
            {retry.data && <span className="text-xs">{retry.data.progress.find((p) => p.state === "running")?.step}</span>}
          </div>
        </Card>
      )}
      <Card className="mb-3.5">
        <div className="flex items-center justify-between">
          <b>Review your profile</b>
          <Chip tone="ok">Profile v{savedCount + 1} · draft</Chip>
        </div>
        <div className="mb-3 text-xs text-muted-foreground">Fix anything the model got wrong. Every match score uses this.</div>
        <ProfileEditor value={draft} onChange={setDraft} />
        <DiffCard diff={version.diff} />
      </Card>
      <div className="flex items-center justify-between gap-2">
        <Btn onClick={onBack}>← Re-upload</Btn>
        <span className="text-xs text-bad">{error}</span>
        <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : `Save as Profile v${savedCount + 1} and score jobs`}
        </Btn>
      </div>
    </div>
  );
}

function Overview({ version, onUpload, onPreferences }: { version: ProfileVersion; onUpload: () => void; onPreferences: () => void }) {
  const p = version.profile;
  return (
    <div className="max-w-[720px] space-y-3.5">
      <Card>
        <div className="flex items-center justify-between">
          <b>{p.current_title || "Your profile"}</b>
          <Chip tone="ok">{version.label} · active</Chip>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {[p.seniority && p.seniority[0].toUpperCase() + p.seniority.slice(1), p.years_experience != null && `${p.years_experience} years`, version.inputs.resume_filename]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {p.skills.map((s) => (
            <Chip key={s.name} tone="acc" title={s.sources.join(" + ")}>
              {s.name}
              {s.years ? <span className="text-faint">· {s.years === 1 ? "1 yr" : `${s.years} yrs`}</span> : null}
            </Chip>
          ))}
        </div>
        {(p.domains.length > 0 || p.languages.length > 0) && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {p.domains.map((d) => (
              <Chip key={d}>{d}</Chip>
            ))}
            {p.languages.map((l) => (
              <Chip key={l.language}>
                {l.language} · {l.level}
              </Chip>
            ))}
          </div>
        )}
      </Card>
      <div className="flex flex-wrap justify-end gap-2">
        <Btn onClick={onPreferences}>Edit preferences</Btn>
        <Btn variant="primary" onClick={onUpload}>
          Upload a new resume
        </Btn>
      </div>
    </div>
  );
}

export function ProfileView() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: versions } = useQuery({ queryKey: ["profile-versions"], queryFn: () => apiGet<ProfileVersion[]>("/profile/versions") });
  const active = versions?.find((v) => v.is_active);
  const [stage, setStage] = useState<Stage | null>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [rescoreTask, setRescoreTask] = useState<number | null>(null);
  const rescore = useTask(rescoreTask);
  // An unsaved draft newer than the active version (say, after a reload) is picked up again.
  const pendingDraft = versions?.find((v) => v.status === "draft" && (!active || v.id > active.id));
  const current: Stage =
    stage ?? (versions === undefined ? "overview" : pendingDraft ? "review" : active ? "overview" : "upload");
  const reviewId = versionId ?? pendingDraft?.id ?? null;

  const activate = useMutation({
    mutationFn: (id: number) => apiSend<ProfileVersion>(`/profile/versions/${id}/activate`, "POST"),
    onSuccess: (v) => {
      qc.invalidateQueries();
      setRescoreTask(v.rescore_task_id ?? null);
      toast(`${v.label} is active again. Jobs it hasn't scored are being scored.`);
    },
  });

  const saved = versions?.filter((v) => v.status === "saved") ?? [];
  return (
    <section>
      <div className="mb-[18px] flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold">Profile</h1>
        <div className="flex-1" />
        {saved.length > 0 && (
          <select
            aria-label="Profile version"
            value={active?.id ?? ""}
            onChange={(e) => activate.mutate(Number(e.target.value))}
          >
            {saved.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} · {new Date(v.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                {v.is_active ? " (active)" : ""}
              </option>
            ))}
          </select>
        )}
      </div>
      {current !== "overview" && <Steps stage={current} />}
      {rescore.data && rescore.data.status !== "done" && (
        <Card className="mb-3.5 max-w-[720px]">
          <b className="text-sm">Scoring jobs against your profile</b>
          <Progress steps={rescore.data.progress} />
        </Card>
      )}
      {current === "overview" && active && (
        <Overview version={active} onUpload={() => setStage("upload")} onPreferences={() => setStage("preferences")} />
      )}
      {current === "upload" && <UploadStage onStarted={(id) => (setTaskId(id), setStage("parsing"))} />}
      {current === "parsing" && taskId && (
        <ParsingStage taskId={taskId} onBack={() => setStage("upload")} onDone={(id) => (setVersionId(id), setStage("review"))} />
      )}
      {current === "review" && reviewId && (
        <ReviewStage
          key={reviewId}
          versionId={reviewId}
          onBack={() => setStage("upload")}
          onSaved={(v) => {
            setRescoreTask(v.rescore_task_id ?? null);
            setStage("preferences");
          }}
        />
      )}
      {current === "preferences" && (
        <div className="max-w-[720px] space-y-3">
          <PreferencesForm />
          <div className="flex justify-between">
            <Btn onClick={() => setStage("overview")}>Done</Btn>
            <Link href="/jobs" className="rounded-lg border border-primary bg-primary px-3 py-1.5 text-sm text-primary-foreground">
              See my matches →
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
