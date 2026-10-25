"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Btn, Card, Chip, Empty } from "@/components/bits";
import { useToast } from "@/components/toast";
import { apiGet, apiSend, type Application, type AppStatus } from "@/lib/api";
import { scoreTone, STATUS_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

const COLUMNS: { key: AppStatus[]; label: string; drop: AppStatus }[] = [
  { key: ["saved"], label: "Saved", drop: "saved" },
  { key: ["applied"], label: "Applied", drop: "applied" },
  { key: ["interviewing"], label: "Interviewing", drop: "interviewing" },
  { key: ["offer"], label: "Offer", drop: "offer" },
  { key: ["rejected", "withdrawn"], label: "Rejected / Withdrawn", drop: "rejected" },
];
const MOVES: AppStatus[] = ["saved", "applied", "interviewing", "offer", "rejected", "withdrawn", "archived"];

function useMove() {
  const qc = useQueryClient();
  const toast = useToast();
  return async (a: Application, status: AppStatus) => {
    if (a.status === status) return;
    const r = await apiSend<Application & { previous_status: AppStatus }>(`/applications/${a.id}`, "PATCH", { status });
    qc.invalidateQueries();
    toast(status === "archived" ? `Removed ${a.company} from the board` : `Moved ${a.company} to ${STATUS_LABEL[status]}`, async () => {
      await apiSend(`/applications/${a.id}`, "PATCH", { status: r.previous_status });
      qc.invalidateQueries();
    });
  };
}

function KanbanCard({ a, onMove }: { a: Application; onMove: (s: AppStatus) => void }) {
  const tone = scoreTone(a.match_pct);
  return (
    <div
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(a.id))}
      className="mb-2 cursor-grab rounded-[10px] border border-border bg-card p-2.5 active:cursor-grabbing"
    >
      <div className="text-[13px] font-semibold">{a.company}</div>
      <div className="text-xs text-muted-foreground">{a.title}</div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {a.match_pct !== null && <Chip tone={tone === "hi" ? "ok" : tone === "mid" ? "warn" : "plain"}>{Math.round(a.match_pct)}%</Chip>}
        {a.status === "applied" && a.days_since_applied !== null && (
          <Chip>{a.days_since_applied === 0 ? "Applied today" : `${a.days_since_applied}d ago`}</Chip>
        )}
        {a.follow_up && <Chip tone="warn">Follow up?</Chip>}
        {a.posting_expired && <Chip tone="bad" title={a.expired_reason ?? undefined}>Posting expired</Chip>}
        {a.status === "withdrawn" && <Chip>Withdrawn</Chip>}
      </div>
      {a.notes && <div className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">{a.notes}</div>}
      <div className="mt-1.5 flex items-center gap-2">
        <select aria-label={`Move ${a.company}`} className="min-w-0 flex-1 py-0.5 text-xs" value={a.status} onChange={(e) => onMove(e.target.value as AppStatus)}>
          {MOVES.map((s) => (
            <option key={s} value={s}>
              {s === "archived" ? "Remove from board" : STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        {a.url && (
          <a href={a.url} target="_blank" rel="noreferrer" className="flex-none text-xs text-primary" title="Open the posting">
            ↗
          </a>
        )}
      </div>
    </div>
  );
}

function Notes({ a }: { a: Application }) {
  const [value, setValue] = useState(a.notes);
  const qc = useQueryClient();
  return (
    <input
      className="w-full py-0.5 text-xs"
      value={value}
      placeholder="Add a note"
      onChange={(e) => setValue(e.target.value)}
      onBlur={async () => {
        if (value !== a.notes) {
          await apiSend(`/applications/${a.id}`, "PATCH", { notes: value });
          qc.invalidateQueries({ queryKey: ["applications"] });
        }
      }}
    />
  );
}

export function ApplicationsView() {
  const { data, isError } = useQuery({ queryKey: ["applications"], queryFn: () => apiGet<Application[]>("/applications") });
  const [mode, setMode] = useState<"board" | "table">("board");
  const [over, setOver] = useState<string | null>(null);
  const move = useMove();
  const apps = data ?? [];

  return (
    <section>
      <div className="mb-[18px] flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold">Applications</h1>
        <div className="flex-1" />
        <span className="text-xs text-faint">{mode === "board" ? "Drag cards between stages" : `${apps.length} applications`}</span>
        <div className="flex overflow-hidden rounded-lg border border-input">
          {(["board", "table"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)} className={cn("px-3 py-1 text-[13px]", mode === m ? "bg-primary text-primary-foreground" : "bg-card")}>
              {m === "board" ? "Board" : "Table"}
            </button>
          ))}
        </div>
        <a href="/api/applications/export.csv" className="rounded-lg border border-input bg-card px-3 py-1.5 text-sm hover:bg-muted">
          Export CSV
        </a>
      </div>
      {isError && <Empty title="Couldn't load applications">Is the API running? Start everything with make dev.</Empty>}
      {data && !apps.length && (
        <Empty title="Nothing tracked yet">
          <p>Save or mark jobs as applied on the Jobs page and they show up here.</p>
          <Link href="/jobs" className="font-semibold text-primary">
            Go to Jobs →
          </Link>
        </Empty>
      )}
      {!!apps.length && mode === "board" && (
        <div className="grid grid-cols-[repeat(5,minmax(200px,1fr))] gap-3 overflow-x-auto pb-2">
          {COLUMNS.map((col) => {
            const items = apps.filter((a) => col.key.includes(a.status));
            return (
              <div
                key={col.label}
                onDragOver={(e) => (e.preventDefault(), setOver(col.label))}
                onDragLeave={() => setOver(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setOver(null);
                  const a = apps.find((x) => x.id === Number(e.dataTransfer.getData("text/plain")));
                  if (a && !col.key.includes(a.status)) move(a, col.drop);
                }}
                className={cn("min-h-[340px] rounded-xl bg-muted p-2.5", over === col.label && "outline-2 -outline-offset-4 outline-primary outline-dashed")}
              >
                <h3 className="mx-1 mt-0.5 mb-2.5 flex justify-between text-[13px] font-semibold">
                  {col.label}
                  <span className="text-faint">{items.length}</span>
                </h3>
                {items.map((a) => (
                  <KanbanCard key={a.id} a={a} onMove={(s) => move(a, s)} />
                ))}
                {!items.length && <div className="px-1 py-2.5 text-xs text-faint">Drop a card here</div>}
              </div>
            );
          })}
        </div>
      )}
      {!!apps.length && mode === "table" && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs tracking-wide text-faint uppercase">
                {["Company", "Role", "Status", "Match", "Applied", "Posting", "Notes"].map((h) => (
                  <th key={h} className="border-b border-border px-3 py-2.5 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {apps.map((a) => (
                <tr key={a.id}>
                  <td className="border-b border-border px-3 py-2.5 font-semibold">{a.company}</td>
                  <td className="border-b border-border px-3 py-2.5">{a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a> : a.title}</td>
                  <td className="border-b border-border px-3 py-2.5">
                    <select aria-label={`Status for ${a.company}`} className="py-0.5 text-xs" value={a.status} onChange={(e) => move(a, e.target.value as AppStatus)}>
                      {MOVES.map((s) => (
                        <option key={s} value={s}>
                          {s === "archived" ? "Remove from board" : STATUS_LABEL[s]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="border-b border-border px-3 py-2.5">{a.match_pct !== null ? `${Math.round(a.match_pct)}%` : "–"}</td>
                  <td className="border-b border-border px-3 py-2.5 text-muted-foreground">
                    {a.applied_at ? new Date(a.applied_at).toLocaleDateString() : "–"}
                    {a.follow_up && <Chip tone="warn" className="ml-1.5">Follow up?</Chip>}
                  </td>
                  <td className="border-b border-border px-3 py-2.5">{a.posting_expired ? <Chip tone="bad">Expired</Chip> : <Chip tone="ok">Active</Chip>}</td>
                  <td className="min-w-[180px] border-b border-border px-3 py-2.5">
                    <Notes a={a} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <div className="mt-3 flex justify-end">
        <Btn variant="ghost" onClick={() => setMode(mode === "board" ? "table" : "board")}>
          {mode === "board" ? "Edit notes in the table view" : "Back to the board"}
        </Btn>
      </div>
    </section>
  );
}
