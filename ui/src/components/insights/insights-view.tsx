"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Bar, Card, Empty } from "@/components/bits";
import { apiGet, type Insights } from "@/lib/api";
import { money, sourceLabel } from "@/lib/format";

export function InsightsView() {
  const { data } = useQuery({ queryKey: ["insights"], queryFn: () => apiGet<Insights>("/insights") });
  if (!data) return <Card className="text-muted-foreground">Loading…</Card>;
  const maxDay = Math.max(1, ...data.per_day.map((d) => d.count));
  const sal = data.salary_by_place;
  const lo = Math.min(...sal.map((s) => s.low), Infinity);
  const hi = Math.max(...sal.map((s) => s.high), 0);
  const span = Math.max(1, hi - lo);
  const funnelMax = Math.max(1, ...data.funnel.map((f) => f.value));
  const stats: [string, string][] = [
    ["Active matches (60%+)", data.stats.active_matches.toLocaleString()],
    ["80%+ matches", data.stats.matches_80.toLocaleString()],
    ["Applied (30d)", String(data.stats.applied_30d)],
    ["Response rate", data.stats.response_rate === null ? "–" : `${data.stats.response_rate}%`],
  ];
  return (
    <section>
      <div className="mb-[18px] flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold">Insights</h1>
        <div className="flex-1" />
        <span className="text-xs text-faint">Based on your top {data.top_count} active matches</span>
      </div>
      {!data.has_profile && (
        <Empty title="No profile yet">
          <Link href="/profile" className="font-semibold text-primary">
            Set up your profile →
          </Link>
        </Empty>
      )}
      <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        {stats.map(([label, value]) => (
          <Card key={label} className="p-3.5">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="text-2xl font-bold">{value}</div>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        <Card>
          <b>Skills you&apos;re missing most often</b>
          <div className="mb-2 text-xs text-muted-foreground">Share of top matches that ask for it</div>
          {data.missing_skills.length ? (
            data.missing_skills.map((g) => (
              <div key={g.skill} className="my-2 grid grid-cols-[110px_1fr_44px] items-center gap-2.5 text-[13px]">
                <span className="truncate">{g.skill}</span>
                <Bar value={g.share} tone="bad" />
                <span className="text-right text-muted-foreground">{g.share}%</span>
              </div>
            ))
          ) : (
            <div className="text-xs text-faint">Shows up once jobs are scored.</div>
          )}
        </Card>
        <Card>
          <b>Your funnel</b>
          <div className="mb-2 text-xs text-muted-foreground">Last 30 days</div>
          {data.funnel.map((f, i) => (
            <div
              key={f.label}
              className="my-1.5 flex h-[30px] items-center rounded-md bg-primary px-2.5 text-[13px] whitespace-nowrap text-primary-foreground"
              style={{ width: `${Math.max(28, (f.value / funnelMax) * 100)}%`, opacity: 1 - i * 0.12 }}
            >
              {f.label} · {f.value}
            </div>
          ))}
        </Card>
        <Card>
          <b>New matching jobs per day</b>
          <div className="text-xs text-muted-foreground">80%+ match, last 14 days</div>
          <svg viewBox="0 0 280 120" width="100%" role="img" aria-label="Bar chart of new matching jobs per day">
            {data.per_day.map((d, i) => (
              <rect key={d.day} x={i * 20 + 2} y={110 - (d.count / maxDay) * 95} width={14} height={(d.count / maxDay) * 95} rx={2} fill="var(--primary)">
                <title>
                  {d.day}: {d.count} jobs
                </title>
              </rect>
            ))}
            <line x1={0} y1={110} x2={280} y2={110} stroke="var(--input)" />
          </svg>
          <div className="flex justify-between text-xs text-faint">
            <span>{data.per_day[0]?.day.slice(5)}</span>
            <span>Today</span>
          </div>
        </Card>
        <Card>
          <b>Salary range by location</b>
          <div className="mb-2 text-xs text-muted-foreground">Median of jobs that show salary, annual {data.currency}</div>
          {sal.length ? (
            sal.map((s) => (
              <div key={s.place} className="my-2 grid grid-cols-[110px_1fr_88px] items-center gap-2.5 text-[13px]">
                <span className="truncate" title={`${s.jobs} jobs`}>
                  {s.place}
                </span>
                <div className="relative h-2 rounded bg-muted">
                  <span
                    className="absolute h-full rounded bg-ok"
                    style={{ left: `${((s.low - lo) / span) * 100}%`, width: `${Math.max(2, ((s.high - s.low) / span) * 100)}%` }}
                  />
                </div>
                <span className="text-right text-[11px] text-muted-foreground">
                  {money(s.low, data.currency)}–{money(s.high, data.currency)}
                </span>
              </div>
            ))
          ) : (
            <div className="text-xs text-faint">No salaries yet.</div>
          )}
        </Card>
        <Card>
          <b>Best sources</b>
          <div className="mb-2 text-xs text-muted-foreground">Where your 80%+ matches come from</div>
          {data.best_sources.length ? (
            data.best_sources.map((s) => (
              <div key={s.source} className="flex justify-between border-b border-border py-1.5 text-[13px]">
                <span>{sourceLabel(s.source)}</span>
                <span className="text-muted-foreground">{s.jobs}</span>
              </div>
            ))
          ) : (
            <div className="text-xs text-faint">Shows up once jobs are scored.</div>
          )}
        </Card>
      </div>
    </section>
  );
}
