"use client";

import { useEffect } from "react";

import type { TaskStep } from "@/lib/api";
import { scoreTone } from "@/lib/format";
import { cn } from "@/lib/utils";

type ChipTone = "plain" | "ok" | "bad" | "warn" | "acc";
const CHIP: Record<ChipTone, string> = {
  plain: "bg-muted text-muted-foreground",
  ok: "bg-ok-bg text-ok",
  bad: "bg-bad-bg text-bad",
  warn: "bg-warn-bg text-warn",
  acc: "bg-brand-soft text-brand-soft-foreground",
};

export function Chip({
  tone = "plain",
  className,
  children,
  ...rest
}: { tone?: ChipTone } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs whitespace-nowrap", CHIP[tone], className)}
      {...rest}
    >
      {children}
    </span>
  );
}

const SCORE: Record<string, string> = {
  hi: "bg-ok-bg text-ok",
  mid: "bg-warn-bg text-warn",
  lo: "bg-muted text-muted-foreground",
};

export function ScoreBadge({ pct, status, size = 58 }: { pct: number | null; status?: string; size?: number }) {
  const label = pct !== null ? `${Math.round(pct)}%` : status === "unscored" ? "—" : "…";
  return (
    <div
      className={cn("grid flex-none place-items-center rounded-xl font-bold", SCORE[scoreTone(pct)])}
      style={{ width: size, height: size, fontSize: size > 40 ? 17 : 12 }}
      title={pct === null ? (status === "unscored" ? "Unscored" : "Not scored yet") : `${pct}% match`}
    >
      {label}
    </div>
  );
}

export function Btn({
  variant = "default",
  className,
  ...rest
}: { variant?: "default" | "primary" | "ghost" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variant === "default" && "border-input bg-card hover:bg-muted",
        variant === "primary" && "border-primary bg-primary text-primary-foreground hover:brightness-110",
        variant === "ghost" && "border-transparent bg-transparent hover:bg-muted",
        variant === "danger" && "border-input bg-card text-bad hover:bg-bad-bg",
        className,
      )}
      {...rest}
    />
  );
}

export function Card({ className, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border border-border bg-card p-4", className)} {...rest} />;
}

export function Field({ label, error, children, className }: { label: string; error?: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
      <span className="min-h-4 text-xs text-bad">{error}</span>
    </label>
  );
}

export function FilterGroup({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 flex justify-between text-xs font-semibold tracking-wide text-faint uppercase">
        {title}
        {aside && <span className="text-foreground normal-case">{aside}</span>}
      </h4>
      {children}
    </div>
  );
}

export function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-0.5">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

export function Progress({ steps }: { steps: TaskStep[] }) {
  return (
    <ul className="mt-2.5 space-y-1.5">
      {steps.map((s, i) => (
        <li key={i} className="flex items-start gap-2">
          <span className="w-4 flex-none text-center">
            {s.state === "done" && <span className="text-ok">✓</span>}
            {s.state === "error" && <span className="text-bad">✕</span>}
            {s.state === "running" && <span className="inline-block size-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
            {s.state === "pending" && <span className="text-faint">○</span>}
          </span>
          <span className="min-w-0">
            <span className={s.state === "pending" ? "text-faint" : undefined}>{s.step}</span>
            {s.detail && <span className={cn("block text-xs", s.state === "error" ? "text-bad" : "text-faint")}>{s.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <Card className="px-5 py-10 text-center text-muted-foreground">
      <div className="text-base font-semibold text-foreground">{title}</div>
      {children && <div className="mt-2 space-y-3">{children}</div>}
    </Card>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <span className="rounded border border-b-2 border-input px-1 font-mono text-[11px] text-muted-foreground">{children}</span>;
}

export function Drawer({ open, onClose, label, children }: { open: boolean; onClose: () => void; label: string; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <>
      <div className={cn("fixed inset-0 z-20 bg-black/35", open ? "block" : "hidden")} onClick={onClose} />
      <aside
        aria-label={label}
        aria-hidden={!open}
        className={cn(
          "fixed top-0 right-0 z-21 h-screen w-[min(560px,100vw)] overflow-auto border-l border-border bg-card p-[22px] shadow-2xl transition-transform duration-200",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        {open && children}
      </aside>
    </>
  );
}

export function Sparkline({ values }: { values: number[] }) {
  if (!values.length) return <span className="text-xs text-faint">No runs yet</span>;
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? 84 / (values.length - 1) : 0;
  return (
    <svg width="90" height="24" viewBox="0 0 90 24" aria-hidden="true" className="inline-block align-middle">
      <polyline
        fill="none"
        stroke="var(--primary)"
        strokeWidth="2"
        points={values.map((v, i) => `${3 + i * step},${21 - (v / max) * 18}`).join(" ")}
      />
      {values.length === 1 && <circle cx="3" cy={21 - (values[0] / max) * 18} r="2.5" fill="var(--primary)" />}
    </svg>
  );
}

export function Bar({ value, tone = "primary" }: { value: number; tone?: "primary" | "bad" | "ok" }) {
  const color = tone === "bad" ? "var(--bad)" : tone === "ok" ? "var(--ok)" : "var(--primary)";
  return (
    <div className="h-2 overflow-hidden rounded bg-muted">
      <span className="block h-full rounded" style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }} />
    </div>
  );
}
