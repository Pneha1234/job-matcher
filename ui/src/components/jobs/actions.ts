"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useToast } from "@/components/toast";
import { apiSend, type AppStatus } from "@/lib/api";

type Target = { id: number; company: string; application: { status: AppStatus } | null; hidden: boolean };

/** Save / Mark applied / Hide with an undo toast; shared by cards, drawer and keyboard. */
export function useJobActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
    qc.invalidateQueries({ queryKey: ["applications"] });
  }, [qc]);

  const setStatus = useCallback(
    async (job: Target, status: AppStatus, message: string) => {
      const r = await apiSend<{ previous_status: AppStatus }>(`/jobs/${job.id}/application`, "PUT", { status });
      refresh();
      toast(message, async () => {
        await apiSend(`/jobs/${job.id}/application`, "PUT", { status: r.previous_status, note: "Undo" });
        refresh();
      });
    },
    [refresh, toast],
  );

  const save = useCallback(
    (job: Target) =>
      job.application?.status === "saved"
        ? setStatus(job, "archived", `Removed ${job.company} from saved`)
        : setStatus(job, "saved", `Saved ${job.company}`),
    [setStatus],
  );

  const apply = useCallback(
    (job: Target) => setStatus(job, "applied", `Marked ${job.company} as applied today`),
    [setStatus],
  );

  const hide = useCallback(
    async (job: Target) => {
      const hidden = !job.hidden;
      await apiSend(`/jobs/${job.id}/flags`, "PUT", { hidden });
      refresh();
      toast(hidden ? `Hidden ${job.company}` : `Unhid ${job.company}`, async () => {
        await apiSend(`/jobs/${job.id}/flags`, "PUT", { hidden: !hidden });
        refresh();
      });
    },
    [refresh, toast],
  );

  return { save, apply, hide, refresh };
}
