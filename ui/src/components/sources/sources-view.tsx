"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Btn, Card, Chip, Progress, Sparkline } from "@/components/bits";
import { useToast } from "@/components/toast";
import { apiGet, apiSend, ApiError, useTask, type Company, type SavedSearch, type SourceRow } from "@/lib/api";
import { ago } from "@/lib/format";

const HEALTH: Record<SourceRow["health"], { tone: "ok" | "warn" | "bad" | "plain"; label: string }> = {
  ok: { tone: "ok", label: "Healthy" },
  warn: { tone: "warn", label: "Dropping" },
  broken: { tone: "bad", label: "Broken" },
  paused: { tone: "plain", label: "Paused" },
  never: { tone: "plain", label: "Not run yet" },
};

function RunButton({ row }: { row: SourceRow }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [taskId, setTaskId] = useState<number | null>(row.running_task_id);
  const { data: task } = useTask<{ found: number; new: number; status: string; error: string | null }>(taskId);
  const running = !!taskId && (!task || task.status === "running");
  useEffect(() => {
    if (task?.status === "done" || task?.status === "error") {
      qc.invalidateQueries();
      const r = task.result;
      toast(
        task.status === "error"
          ? `${row.label} failed: ${task.error}`
          : r?.status === "ok"
            ? `${row.label} finished: ${r.found} found, ${r.new} new`
            : `${row.label}: ${r?.error ?? r?.status}`,
      );
    }
    // Only react to the task finishing.
  }, [task?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Btn
      className="text-xs"
      disabled={running || row.paused}
      onClick={async () => setTaskId((await apiSend<{ task_id: number }>(`/sources/${row.name}/run`, "POST")).task_id)}
    >
      {running ? "Running…" : "Run now"}
    </Btn>
  );
}

function Companies() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["companies"], queryFn: () => apiGet<Company[]>("/companies") });
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [discoverTask, setDiscoverTask] = useState<number | null>(null);
  const discover = useTask(discoverTask);
  const add = useMutation({
    mutationFn: () => apiSend<Company>("/companies", "POST", { url }),
    onSuccess: (c) => {
      setUrl("");
      qc.invalidateQueries();
      toast(`Added ${c.name} (${c.platform}). It's crawled on the next run.`);
    },
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  const counts = (data ?? []).reduce<Record<string, number>>((acc, c) => {
    if (c.status === "active") acc[c.platform] = (acc[c.platform] ?? 0) + 1;
    return acc;
  }, {});
  const dead = (data ?? []).filter((c) => c.status === "dead");
  return (
    <Card className="mt-4">
      <b>Company boards</b>
      <div className="mb-2 text-xs text-muted-foreground">
        Greenhouse, Lever, Ashby, Workable, Recruitee, Personio, SmartRecruiters and Workday boards, or any careers page with job markup.
        Jobs that link to a board add it here on their own.
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(counts).map(([p, n]) => (
          <Chip key={p}>
            {p} · {n}
          </Chip>
        ))}
        {dead.length > 0 && <Chip tone="bad">{dead.length} boards not found</Chip>}
      </div>
      <div className="mt-3 flex gap-2">
        <input
          className="flex-1"
          value={url}
          placeholder="boards.greenhouse.io/yourcompany or company.com/careers"
          onChange={(e) => (setUrl(e.target.value), setError(""))}
          onKeyDown={(e) => e.key === "Enter" && url.trim() && add.mutate()}
        />
        <Btn disabled={!url.trim() || add.isPending} onClick={() => add.mutate()}>
          Add
        </Btn>
      </div>
      <div className="min-h-4 text-xs text-bad">{error}</div>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        <Btn disabled={discover.data?.status === "running"} onClick={async () => setDiscoverTask((await apiSend<{ task_id: number }>("/companies/discover", "POST")).task_id)}>
          Find more companies (Common Crawl)
        </Btn>
        {discover.data && <Progress steps={discover.data.progress} />}
      </div>
    </Card>
  );
}

export function SourcesView() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isError } = useQuery({
    queryKey: ["sources"],
    queryFn: () => apiGet<{ sources: SourceRow[]; run_all_task_id: number | null }>("/sources"),
    refetchInterval: 10_000,
  });
  const { data: searches } = useQuery({ queryKey: ["searches"], queryFn: () => apiGet<SavedSearch[]>("/searches") });
  const [allTask, setAllTask] = useState<number | null>(null);
  const all = useTask(allTask ?? data?.run_all_task_id);
  const rows = data?.sources ?? [];

  async function pause(row: SourceRow) {
    await apiSend(`/sources/${row.name}/${row.paused ? "resume" : "pause"}`, "POST");
    qc.invalidateQueries({ queryKey: ["sources"] });
    toast(row.paused ? `Resumed ${row.label}` : `Paused ${row.label}`);
  }

  return (
    <section>
      <div className="mb-[18px] flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold">Sources</h1>
        <div className="flex-1" />
        <Btn
          disabled={all.data?.status === "running"}
          onClick={async () => {
            setAllTask((await apiSend<{ task_id: number }>("/sources/run-all", "POST")).task_id);
            toast("Started all sources. Scrapers wait 3–8 s between requests, so this takes a while.");
          }}
        >
          {all.data?.status === "running" ? "Running all…" : "Run all now"}
        </Btn>
      </div>
      {searches && !searches.length && (
        <Card className="mb-3 border-0 bg-warn-bg text-warn">
          Job-board scrapers (LinkedIn, Indeed, Glassdoor, Google, Naukri) and JobTech search for your saved searches.{" "}
          <Link href="/settings" className="font-semibold underline">
            Add one in Settings
          </Link>
          .
        </Card>
      )}
      {all.data?.status === "running" && (
        <Card className="mb-3">
          <b className="text-sm">Running every source</b>
          <Progress steps={all.data.progress.filter((p) => p.state !== "pending").slice(-4)} />
        </Card>
      )}
      {isError && <Card className="text-bad">Couldn&apos;t load sources. Is the API running?</Card>}
      <Card className="overflow-x-auto p-0">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-xs tracking-wide text-faint uppercase">
              {["Source", "Status", "Last run", "Found", "New", "Last 7 runs", "Budget today", ""].map((h) => (
                <th key={h} className="border-b border-border px-3 py-2.5 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const h = HEALTH[row.health];
              return (
                <tr key={row.name}>
                  <td className="border-b border-border px-3 py-2.5">
                    <b>{row.label}</b>
                    <div className="text-xs text-faint">{row.via}</div>
                    {row.detail && row.health !== "ok" && <div className="max-w-[360px] text-xs text-bad">{row.detail}</div>}
                  </td>
                  <td className="border-b border-border px-3 py-2.5">
                    <Chip tone={h.tone}>{h.label}</Chip>
                    {row.paused_until && <div className="text-xs text-faint">until {row.paused_until}</div>}
                  </td>
                  <td className="border-b border-border px-3 py-2.5 whitespace-nowrap text-muted-foreground">{ago(row.last_run_at)}</td>
                  <td className="border-b border-border px-3 py-2.5">{row.found?.toLocaleString() ?? "–"}</td>
                  <td className="border-b border-border px-3 py-2.5">{row.new ?? "–"}</td>
                  <td className="border-b border-border px-3 py-2.5">
                    <Sparkline values={row.history} />
                  </td>
                  <td className="border-b border-border px-3 py-2.5 text-muted-foreground">
                    {row.budget_used}/{row.budget}
                  </td>
                  <td className="border-b border-border px-3 py-2.5 whitespace-nowrap">
                    <RunButton row={row} /> <Btn variant="ghost" className="text-xs" onClick={() => pause(row)}>{row.paused ? "Resume" : "Pause"}</Btn>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <p className="text-xs text-faint">
        A source that suddenly returns 0 jobs usually means the site changed and its scraper needs fixing. A blocked source is paused, never
        forced.
      </p>
      <Companies />
    </section>
  );
}
