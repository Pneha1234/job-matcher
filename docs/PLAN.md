# Job Matcher — Plan

A personal, local-first app. You upload your resume and add your GitHub, portfolio
and LinkedIn export; the app gathers active job postings from free sources
worldwide, scores each one against your profile with a local LLM, and tracks
where you have applied. Nothing about you leaves your machine.

This is the single source of truth for scope and decisions. Update it in the same
change whenever a decision is made or reversed (see the decision log at the end).

## Principles

- **Local-first.** The LLM, embeddings, database and UI all run on this Mac.
  Your resume never goes to a cloud model.
- **Free sources only.** No paid APIs, proxies or subscriptions. Free sign-up keys
  and free tiers with daily limits are allowed; each source has a daily budget.
- **A proper UI.** Everything is done through the app's screens, never by calling
  the API by hand.
- **Never delete history.** Expired jobs, hidden jobs and old profile versions are
  status changes, not deletions, so application history survives.
- **Honest scores.** The match % is computed in code from validated sub-scores.
  If the LLM fails, the job shows as "unscored", never a guessed number.
- **Polite scraping.** Slow, batched, cached. Never scrape while logged in to
  your own accounts, never try to get around CAPTCHAs or bot blocks — a
  blocked source is paused, not forced.

## Architecture

```
 Sources (scrapers, public APIs, feeds)
        │  fetch() -> RawJob
        ▼
 Normalise (salary, location via GeoNames, job type, remote eligibility, visa)
        ▼
 Deduplicate (canonical key + embedding similarity) → jobs + job_sources
        ▼
 Lifecycle (first_seen / last_seen, expiry checks)
        ▼
 Matching: Stage A embeddings + hard filters → top ~150
           Stage B local LLM → JSON sub-scores → weighted % in code
        ▼
 FastAPI ──► Next.js UI (Jobs, Applications, Insights, Sources, Profile, Settings)
```

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic | Host has 3.10; install 3.12 via pyenv |
| DB | SQLite + `sqlite-vec` | Postgres + pgvector later only if needed |
| Scheduler | APScheduler | No Redis/Celery for a single user |
| LLM | Ollama, `qwen2.5:14b` (fallback `llama3.1:8b`) | Run **natively** on macOS, not in Docker — Docker on Mac has no Metal GPU access. 24 GB RAM fits 14B |
| Embeddings | `bge-m3` via Ollama | Multilingual (NL, DE, Hindi, Nepali postings) |
| Scraping | `python-jobspy`, `httpx`, `selectolax`, `extruct` | |
| Parsing | `pymupdf`, `python-docx`, `trafilatura` | |
| Locations | GeoNames dataset (offline) | City/region/country + lat/lon + aliases |
| FX rates | ECB daily reference rates (or Frankfurter) | Free |
| Frontend | Next.js + TypeScript, Tailwind, shadcn/ui, TanStack Query/Table, dnd-kit, Recharts | |
| Map | Leaflet + OpenStreetMap tiles (or Protomaps offline) | |
| Desktop (later) | Tauri wrapping the same UI | Native notifications |

## Sources (all free)

### Scraping — JobSpy (open source, no key)
LinkedIn (logged-out guest pages only), Indeed (per country), Glassdoor, Google
Jobs, ZipRecruiter, Naukri, Bayt, BDJobs.

### Company job boards (public endpoints, no key, all locations worldwide)
Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee (JSON);
Personio, Teamtailor (XML/RSS); Workday (JSON endpoint behind career sites);
any career page exposing schema.org `JobPosting` (via `extruct`).

India-specific platforms: Keka, Darwinbox, Zoho Recruit, Freshteam. Check each
for a JSON endpoint; otherwise parse HTML.

### Public APIs and feeds
| Source | Region | Key |
|---|---|---|
| Remotive, RemoteOK, Arbeitnow, Himalayas, Jobicy | Remote / EU | none (RemoteOK wants attribution) |
| We Work Remotely | Remote | RSS |
| HN "Who's Hiring" (Algolia HN API) | Global | none |
| Bundesagentur für Arbeit Jobsuche | Germany | public key |
| JobTech / Arbetsförmedlingen | Sweden | free key |
| NAV | Norway | free |
| France Travail | France | free signup |
| Job Bank | Canada | open data |
| USAJobs | US gov | free key |
| Reed | UK | free key |
| Adzuna, Jooble, Careerjet | ~20–70 countries | free key, daily limits |

### India
JobSpy already covers Naukri, Indeed India, LinkedIn, Glassdoor India and Google
Jobs. Extra scrapers: Foundit, Shine, TimesJobs (general); Instahyre, Hirist,
Cutshort, Wellfound (tech/startups); IIMJobs (senior); Internshala,
Freshersworld (freshers/internships); National Career Service (ncs.gov.in).
Large IT services companies (TCS, Infosys, Wipro, HCL…) only via custom
scrapers for the ones you care about, and never behind a login.

### Nepal
HTML scrapers for Merojob, JobsNepal, Kumarijob, Jobejee; Lok Sewa Aayog
(psc.gov.np) PDF notices read by the LLM. Nepali tech companies (Leapfrog,
F1Soft, Fusemachines, CloudFactory, Deerwalk, LogPoint, Cotiviti Nepal, Verisk
Nepal…) added to the company crawl list by hand. Facebook groups are out of
scope; use the "paste a job link or text" manual import instead.

### Company discovery (free)
Common Crawl index queries for every URL under the ATS domains; open-source
company lists on GitHub; and self-growth — any scraped job that links to a
company board adds that company to the crawl list.

### Explicitly excluded (cost money)
SerpAPI, ScraperAPI, Bright Data, any paid proxy, any paid job-data API.

### Source rules
- Each source is one plugin with the same interface: `fetch() -> list[RawJob]`.
- Each source has a daily request budget, random 3–8 s delays, cached responses.
- Small sites (Nepali boards) are crawled very gently: a few times a day.
- A source returning 0 jobs or a spike in errors shows red on the Sources page.

## Worldwide locations

- Every location string is resolved with GeoNames to city → region → country +
  lat/lon. Aliases handled: Bengaluru/Bangalore, Gurugram/Gurgaon,
  Mumbai/Bombay, München/Munich, Kathmandu/Lalitpur/Bhaktapur as "Kathmandu
  Valley", etc.
- A posting can have several locations; each is stored separately.
- Ambiguous cities (London UK vs London Ontario) are resolved using the
  posting's country and the company's known offices. Unresolvable → "Location
  unclear", never guessed.
- Remote is never just "remote": store allowed countries/regions and timezone
  constraints, so "Remote" only shows when you are eligible.
- Detect visa sponsorship ("sponsors" / "no sponsorship") and relocation support.
- Scrapers search only the target countries/regions you pick in Settings; ATS
  crawls bring in the rest of the world for free.

## Normalisation

- **Salary:** ranges, k/K, hourly/monthly/yearly, "12 LPA", "₹8–12 lakhs",
  "NPR 80,000/month" → annual in your currency (daily FX). Keep the original
  text. "Negotiable", "competitive", "as per company norms" → not disclosed
  (null), never 0.
- **Job type:** full-time, contract, freelance, part-time, internship.
- **India fields:** notice period, experience range, work from office/hybrid,
  immediate joiner.
- **Posting language** and language requirements (e.g. "Dutch required").

## Data model

- `profile_versions` — raw inputs, extracted profile JSON, embedding, is_active
- `jobs` — title, company, salary fields, description, posted_at,
  first_seen_at, last_seen_at, status (active/expired/stale), expired_reason,
  remote eligibility, visa, embedding
- `job_locations` — job_id, city, region, country, lat, lon
- `job_sources` — job_id, source, url, source_job_id (one job, many sources)
- `match_scores` — job_id, profile_version_id, sub-scores, final %, matched
  and missing skills, explanation, model, scored_at
- `applications` — job_id, status, applied_at, notes, status history
- `user_job_flags` — hidden, not-interested reason
- `companies` — name, platform, slug, last_crawled_at
- `scrape_runs` — source, timings, found, new, errors, budget used
- `saved_searches`, `settings`

## Matching

- **Profile builder:** resume (PDF/DOCX) → text → LLM extracts skills (years,
  last used), roles, seniority, domains, spoken languages, preferences. GitHub
  public API adds evidence (languages, repos, recency). Portfolio via
  `trafilatura`. LinkedIn via the official data-export ZIP — never scraped.
  You review and edit before saving; each save is a new profile version.
- **Stage A:** hard filters (location eligibility, type, min salary, active),
  then cosine similarity → top ~150.
- **Stage B:** LLM returns JSON (Pydantic-validated): required skills
  matched/partial/missing, nice-to-haves, seniority, domain, location and
  language fit, short explanation. Invalid JSON → one retry → "unscored".
- **Final %** in code. Default weights: required 50, nice-to-have 15,
  seniority 15, domain 10, location/language 10. Adjustable in Settings.
- Scores cached per (job, profile version); re-score only on change.

## Lifecycle (active jobs only)

- ATS/feed sources: missing from 2 consecutive runs → expired (removed).
- Scraped jobs older than 7 days: daily URL check; 404/410, redirect to a
  generic careers page, or "no longer accepting" text → expired.
- Past `validThrough` or an "Apply before" deadline (common on Nepali boards)
  → expired.
- No confirmation for 45 days → stale (hidden by default).

## UI

Reference mockup: [`docs/mockups/job-matcher-mockup.html`](mockups/job-matcher-mockup.html)
(open it in a browser; it is a static clickable prototype with fake data).

- **Jobs:** filter sidebar (match %, location, type, salary, posted, status),
  saved views as tabs, search, sort, cards with match %, salary, sources and
  skill chips; detail drawer with score breakdown, all sources, cover-letter
  draft; Save / Mark applied / Hide with undo toast; keyboard j/k/s/a/x.
  "New jobs — show" banner instead of shifting the list.
- **Location controls (to add to the mockup):** autocomplete picker (country
  or city + radius), region shortcuts (EU, DACH, Nordics, UK & Ireland, North
  America, GCC, APAC, India metros, Kathmandu Valley, South Asia, Anywhere),
  "remote I'm eligible for", visa/relocation filters, timezone overlap,
  map view with clusters.
- **India/Nepal controls:** INR/NPR with lakh formatting, notice period,
  experience range, immediate joiner, freshers/internships type.
- **Applications:** kanban Saved → Applied → Interviewing → Offer → Rejected /
  Withdrawn, drag and drop, "follow up?" after 14 days, expired-posting badge;
  table view with CSV export.
- **Insights:** headline stats, missing-skills chart, funnel, matches per day,
  salary by location, best sources.
- **Sources:** health per source, 7-run sparkline, budget used, run now / pause.
- **Profile:** setup wizard (resume upload, links, LinkedIn export, parsing
  progress, editable profile with skill provenance, diff vs previous version).
- **Settings:** match weights with live re-rank preview, saved searches,
  target countries, schedules, model, currency, notifications.
- **Manual import:** paste a job URL or text; the LLM extracts it.

## Phases

| # | Phase | Done when |
|---|---|---|
| 0 | Setup: repo layout, Python 3.12 + FastAPI skeleton, Next.js shell, native Ollama with models pulled, one `make dev` command | `make dev` starts API + UI; a test prompt returns valid JSON from Ollama |
| 1 | Profile builder + setup wizard UI | Your real resume produces a profile you sign off on with minor edits |
| 2 | First source (JobSpy) + normalisation basics | One run stores ≥500 normalised jobs |
| 3 | Wider coverage: ATS adapters, company discovery, JSON-LD crawler, free APIs, India + Nepal boards | ≥10k active jobs; every source logs runs |
| 4 | Normalisation and dedup: salary (incl. LPA/NPR), GeoNames locations, remote eligibility, visa | Spot check of 50 jobs is clean |
| 5 | Matching engine | Ranking of 20 hand-judged jobs roughly matches your gut |
| 6 | Lifecycle / expiry | Default views show only active jobs, with reasons on expired |
| 7 | UI: Jobs, drawer, Applications, Sources, Settings (port the mockup) | You use it daily for a week instead of LinkedIn |
| 8 | Scheduling + monitoring | Runs unattended 3 days, all sources healthy |
| 9 | Extras: Insights, map view, digest, gap analysis, cover letters, feedback weights, Tauri | As desired |

## Edge cases to keep covered

- Same job on several boards or in several cities → one job, many sources/locations.
- Company re-posts with a new ID → dedup keeps the original first_seen.
- Salary missing or non-numeric → null; filters treat it as "not shown".
- "Remote (US only)" etc. when you are elsewhere → not eligible.
- Posting requires a language you do not speak → location/language score drops.
- Scraper silently returns 0 → flagged red.
- LLM timeout / invalid JSON → unscored with retry button.
- New resume → new profile version, old scores labelled, background re-score.
- Free-tier API limit reached → source paused until the next day, shown on Sources.
- Machine too slow for 14B → switch to 8B and shrink the Stage A shortlist.

## Risks

- LinkedIn and Glassdoor forbid scraping even logged out; blocks are possible.
  Personal use only, never with your own logged-in account.
- Naukri changes bot detection often; expect it to break and pause it when it does.
- Free-tier limits cap volume on some APIs.
- Scrapers break when sites change; the Sources page is the early warning.

## Decision log

- 2026-10-22 — Project started. Local LLM via Ollama; free sources only (paid
  APIs and proxies excluded); proper UI, not API-driven; worldwide coverage
  including India and Nepal; LinkedIn via data export, never scraped logged in.
- 2026-10-22 — Ollama runs natively on macOS (no Metal GPU in Docker).
