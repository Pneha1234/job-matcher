"use client";

import { useState } from "react";

import { Btn, Card, Chip, Field } from "@/components/bits";
import type { Language, Profile, ProfileVersion } from "@/lib/api";

const SENIORITY = ["intern", "junior", "mid", "senior", "lead", "staff", "principal", "manager", "director"];
const LEVELS: Language["level"][] = ["native", "fluent", "professional", "basic", "none"];

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function ProfileEditor({ value, onChange }: { value: Profile; onChange: (p: Profile) => void }) {
  const [skill, setSkill] = useState("");
  const [years, setYears] = useState("");
  const [skillErr, setSkillErr] = useState("");
  const [domain, setDomain] = useState("");
  const [lang, setLang] = useState("");
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => onChange({ ...value, [k]: v });

  function addSkill() {
    const name = skill.trim();
    if (!name) return setSkillErr("Enter a skill name first.");
    if (value.skills.some((s) => s.name.toLowerCase() === name.toLowerCase())) return setSkillErr("That skill is already on your profile.");
    if (years && !/^\d+(\.\d)?$/.test(years)) return setSkillErr("Years must be a number, like 2 or 1.5.");
    set("skills", [...value.skills, { name, years: years ? Number(years) : null, last_used: null, sources: ["Added by you"] }]);
    setSkill("");
    setYears("");
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Field label="Current title">
          <input value={value.current_title ?? ""} onChange={(e) => set("current_title", e.target.value || null)} />
        </Field>
        <Field label="Seniority">
          <select value={value.seniority ?? ""} onChange={(e) => set("seniority", e.target.value || null)}>
            <option value="">Not stated</option>
            {SENIORITY.map((s) => (
              <option key={s} value={s}>
                {cap(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Total experience (years)">
          <input
            type="number"
            min={0}
            max={60}
            step={0.5}
            value={value.years_experience ?? ""}
            onChange={(e) => set("years_experience", e.target.value === "" ? null : Number(e.target.value))}
          />
        </Field>
      </div>

      <div className="mt-1 text-xs text-muted-foreground">Skills (hover to see where each came from)</div>
      <div className="mt-1.5 flex flex-wrap gap-1.5" data-testid="skills">
        {value.skills.map((s, i) => (
          <Chip key={s.name} tone={s.sources.includes("Model inferred") ? "warn" : "acc"} title={s.sources.join(" + ")}>
            {s.name}
            {s.years ? <span className="text-faint">· {s.years === 1 ? "1 yr" : `${s.years} yrs`}</span> : null}
            <button
              type="button"
              aria-label={`Remove ${s.name}`}
              className="opacity-70"
              onClick={() => set("skills", value.skills.filter((_, j) => j !== i))}
            >
              ✕
            </button>
          </Chip>
        ))}
        {!value.skills.length && <span className="text-xs text-faint">No skills yet. Add them below.</span>}
      </div>
      {value.skills.some((s) => s.sources.includes("Model inferred")) && (
        <div className="mt-1 text-xs text-warn">Yellow skills weren&apos;t found word-for-word in your files. Keep them only if they&apos;re true.</div>
      )}
      <div className="mt-2 flex gap-2">
        <input className="flex-1" value={skill} placeholder="Kubernetes" onChange={(e) => (setSkill(e.target.value), setSkillErr(""))} onKeyDown={(e) => e.key === "Enter" && addSkill()} />
        <input className="w-[90px]" value={years} placeholder="Years" onChange={(e) => (setYears(e.target.value), setSkillErr(""))} onKeyDown={(e) => e.key === "Enter" && addSkill()} />
        <Btn onClick={addSkill}>Add skill</Btn>
      </div>
      <div className="min-h-4 text-xs text-bad">{skillErr}</div>

      <div className="mt-1.5 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">Domains</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {value.domains.map((d) => (
              <Chip key={d} tone="acc">
                {d}
                <button type="button" aria-label={`Remove ${d}`} className="opacity-70" onClick={() => set("domains", value.domains.filter((x) => x !== d))}>
                  ✕
                </button>
              </Chip>
            ))}
          </div>
          <input
            className="mt-1.5 w-full"
            value={domain}
            placeholder="Add a domain, like Fintech, and press Enter"
            onChange={(e) => setDomain(e.target.value)}
            onKeyDown={(e) => {
              const d = domain.trim();
              if (e.key === "Enter" && d && !value.domains.some((x) => x.toLowerCase() === d.toLowerCase())) {
                set("domains", [...value.domains, d]);
                setDomain("");
              }
            }}
          />
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Languages you speak</div>
          <div className="mt-1 space-y-1">
            {value.languages.map((l, i) => (
              <div key={l.language} className="flex items-center gap-2">
                <span className="flex-1">{l.language}</span>
                <select
                  aria-label={`${l.language} level`}
                  value={l.level}
                  onChange={(e) =>
                    set(
                      "languages",
                      value.languages.map((x, j) => (j === i ? { ...x, level: e.target.value as Language["level"] } : x)),
                    )
                  }
                >
                  {LEVELS.map((lv) => (
                    <option key={lv} value={lv}>
                      {cap(lv)}
                    </option>
                  ))}
                </select>
                <button type="button" aria-label={`Remove ${l.language}`} className="text-faint" onClick={() => set("languages", value.languages.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </div>
            ))}
          </div>
          <input
            className="mt-1.5 w-full"
            value={lang}
            placeholder="Add a language and press Enter"
            onChange={(e) => setLang(e.target.value)}
            onKeyDown={(e) => {
              const l = lang.trim();
              if (e.key === "Enter" && l && !value.languages.some((x) => x.language.toLowerCase() === l.toLowerCase())) {
                set("languages", [...value.languages, { language: l, level: "fluent" }]);
                setLang("");
              }
            }}
          />
        </div>
      </div>
    </>
  );
}

export function DiffCard({ diff }: { diff: ProfileVersion["diff"] }) {
  if (!diff?.against) return null;
  const parts: React.ReactNode[] = [
    ...diff.added.map((s) => <span key={`a${s}`} className="text-ok">+ {s}</span>),
    ...diff.removed.map((s) => <span key={`r${s}`} className="text-bad">− {s}</span>),
    ...diff.changed.map((c) => (
      <span key={`c${c.field}`}>
        {c.field.replace("_", " ")} {String(c.from ?? "—")} → {String(c.to ?? "—")}
      </span>
    )),
  ];
  return (
    <Card className="mt-3.5 border-0 bg-muted">
      <b className="text-xs">Changes from {diff.against}</b>
      <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
        {parts.length ? parts.flatMap((p, i) => (i ? [<span key={`s${i}`}>·</span>, p] : [p])) : "No changes"}
      </div>
    </Card>
  );
}
