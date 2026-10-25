"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Btn, Card, Progress } from "@/components/bits";
import { apiSend, ApiError, useTask } from "@/lib/api";

export function ImportPanel({ onClose, onImported }: { onClose: () => void; onImported: (jobId: number) => void }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState<number | null>(null);
  const { data: task } = useTask<{ job_id: number }>(taskId);
  useEffect(() => {
    if (task?.status === "done" && task.result) {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onImported(task.result.job_id);
    }
  }, [task, qc, onImported]);
  const start = useMutation({
    mutationFn: () => apiSend<{ task_id: number }>("/jobs/import", "POST", { url: url || null, text: text || null }),
    onSuccess: (r) => setTaskId(r.task_id),
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  return (
    <Card className="mb-3">
      <div className="flex items-center justify-between">
        <b>Add a job by hand</b>
        <Btn variant="ghost" aria-label="Close" onClick={onClose}>
          ✕
        </Btn>
      </div>
      <div className="mb-2 text-xs text-muted-foreground">
        Paste a job link, or the posting text (for Facebook groups and pages that need a login). Your local model reads it.
      </div>
      <input className="w-full" placeholder="https://company.com/careers/backend-engineer" value={url} onChange={(e) => (setUrl(e.target.value), setError(""))} />
      <div className="my-1.5 text-center text-xs text-faint">or</div>
      <textarea className="min-h-24 w-full" placeholder="Paste the posting text" value={text} onChange={(e) => (setText(e.target.value), setError(""))} />
      {task && <Progress steps={task.progress} />}
      {task?.status === "error" && <div className="mt-1 text-xs text-bad">{task.error}</div>}
      <div className="mt-2 flex items-center justify-end gap-2">
        <span className="text-xs text-bad">{error}</span>
        <Btn
          variant="primary"
          disabled={start.isPending || task?.status === "running"}
          onClick={() => {
            if (!url.trim() && !text.trim()) return setError("Paste a job link or the posting text.");
            start.mutate();
          }}
        >
          {task?.status === "running" ? "Reading…" : "Add job"}
        </Btn>
      </div>
    </Card>
  );
}
