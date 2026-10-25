export function PageHeader({ title, aside }: { title: string; aside?: React.ReactNode }) {
  return (
    <div className="mb-[18px] flex flex-wrap items-center gap-3">
      <h1 className="text-[22px] font-semibold">{title}</h1>
      <div className="flex-1" />
      {aside && <span className="text-xs text-faint">{aside}</span>}
    </div>
  );
}

export function ComingSoon({ phase, children }: { phase: number; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card px-5 py-10 text-center text-muted-foreground">
      <p>{children}</p>
      <p className="mt-2 text-xs text-faint">Arrives in phase {phase} of docs/PLAN.md.</p>
    </div>
  );
}
