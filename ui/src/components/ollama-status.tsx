"use client";

import { useQuery } from "@tanstack/react-query";

import { apiGet, type Health } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "bad" | "idle";

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  idle: "bg-faint animate-pulse",
};

function describe(data: Health | undefined, failed: boolean): { tone: Tone; label: string; detail?: string } {
  if (failed) return { tone: "bad", label: "API offline", detail: "Start it with make dev" };
  if (!data) return { tone: "idle", label: "Checking Ollama…" };
  const { ollama, db } = data;
  if (!db.ok) return { tone: "bad", label: "Database error", detail: db.error ?? undefined };
  if (!ollama.ok) return { tone: "bad", label: "Ollama offline", detail: ollama.error ?? undefined };
  if (!ollama.llm_model_ready || !ollama.scoring_model_ready || !ollama.embed_model_ready) {
    return { tone: "warn", label: `Ollama · ${ollama.llm_model}`, detail: ollama.error ?? undefined };
  }
  const models = ollama.scoring_model && ollama.scoring_model !== ollama.llm_model ? `${ollama.llm_model} + ${ollama.scoring_model}` : ollama.llm_model;
  return { tone: "ok", label: `Ollama · ${models}`, detail: `v${ollama.version}` };
}

export function OllamaStatus() {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<Health>("/health"),
    refetchInterval: 15_000,
  });
  const { tone, label, detail } = describe(data, isError);

  return (
    <div title={detail} data-testid="ollama-status" data-tone={tone}>
      <div className="flex items-center">
        <span className={cn("mr-1.5 inline-block size-2 rounded-full", DOT[tone])} />
        {label}
      </div>
      {detail && tone !== "ok" && <div className="truncate text-bad">{detail}</div>}
    </div>
  );
}
