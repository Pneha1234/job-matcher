# Job Matcher

A local-first job search assistant: it reads your resume, gathers active postings from
free sources worldwide, and ranks them by how well they fit you, scored by a language
model running on your own machine.

## Features

- **Profile from your own files.** Upload a PDF or DOCX resume and optionally add GitHub,
  a portfolio page and LinkedIn's official data export. A local model extracts skills,
  seniority, domains and languages. You review every field, see where each skill came
  from, and save numbered versions.
- **Free sources only.** Company job boards (Greenhouse, Lever, Ashby, Workable,
  Recruitee, Personio, SmartRecruiters, Workday), public feeds (Remotive, RemoteOK,
  Arbeitnow, Himalayas, Jobicy, We Work Remotely, Hacker News "Who is hiring", JobTech),
  logged-out job boards via [JobSpy](https://github.com/speedyapply/JobSpy), and Nepali
  boards (Merojob, Kumarijob).
- **Normalisation.** Salaries are converted to annual amounts in your currency (including
  LPA, lakh and NPR). Locations are resolved offline with GeoNames, including remote
  eligibility, visa sponsorship, relocation and language requirements. Duplicates across
  boards and cities are merged.
- **Honest match scores.** Stage A uses embeddings and your hard filters. Stage B is an
  LLM assessment validated against a schema, with the percentage computed in code from
  your weights. If the model's answer doesn't validate, the job shows as unscored rather
  than getting a guessed number.
- **Only active jobs.** Postings that disappear from their source, pass their deadline or
  stop answering are expired with a reason, never deleted.
- **Application tracker.** A kanban board with drag and drop, follow-up reminders, notes
  and CSV export.
- **Polite by design.** Random delays, caching and a daily request budget per source. A
  source that meets a block or CAPTCHA is paused, not forced.

## Privacy

Everything runs on your computer. The LLM and the embedding model run in
[Ollama](https://ollama.com), and the database is a local SQLite file. Your resume and
profile are never sent to a cloud model or any third-party service. The app only makes
outgoing requests to public job sources and reference data (GeoNames, ECB exchange
rates), plus the public GitHub API and the portfolio page when you add those links.

## Architecture

```
Sources (ATS APIs, feeds, JobSpy, sitemaps)
      │  fetch(ctx) -> FetchResult(RawJob…, complete scopes)
      ▼
Normalise (salary + FX, GeoNames locations, remote/visa/type/language)
      ▼
Deduplicate (company + title) → jobs, job_sources, job_locations
      ▼
Lifecycle (missed listings, deadlines, URL checks, stale)
      ▼
Matching  A: bge-m3 embeddings (sqlite-vec) + hard filters → shortlist
          B: local LLM → validated JSON → weighted % in code
      ▼
FastAPI ──► Next.js UI: Jobs · Applications · Insights · Sources · Profile · Settings
```

Background work (parsing, source runs, scoring) runs as in-process tasks whose progress
the UI polls. An APScheduler tick runs each source group on its schedule.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic |
| Storage | SQLite with `sqlite-vec` |
| LLM and embeddings | Ollama: `qwen2.5:14b` (or `llama3.1:8b`), `bge-m3` |
| Ingestion | httpx, python-jobspy, selectolax, PyMuPDF, python-docx, trafilatura |
| Reference data | GeoNames `cities15000`, ECB daily rates |
| Frontend | Next.js, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query |

## Getting started

Prerequisites: macOS or Linux, Python 3.12 (via pyenv), Node.js 20+, and Ollama
installed natively. On a Mac, run Ollama outside Docker so it can use the GPU.

```bash
brew install ollama && brew services start ollama
ollama pull qwen2.5:14b
ollama pull bge-m3
```

Install dependencies and start the API (port 8000) and UI (port 3000):

```bash
make setup
make dev
```

Then open http://localhost:3000:

1. **Profile**: upload your resume, review the result and save it.
2. **Settings**: add a saved search such as "Python developer · Kathmandu" and set
   where you live and want to work.
3. **Sources**: click **Run all now**. New jobs are scored in the background and appear
   ranked on **Jobs**.

On first start the app downloads GeoNames (about 3 MB) and the ECB rates into `data/`,
which is git-ignored.

## Development

```bash
make check   # ruff, black, pytest, eslint, tsc
make smoke   # round-trip through the real local Ollama models
make fmt     # ruff --fix and black
```

The test suite uses a fake Ollama and a small GeoNames fixture, so it needs no network
and no models.

## Project status

| Phase | Scope | Status |
|---|---|---|
| 0 | Setup: FastAPI, Next.js shell, native Ollama | Done |
| 1 | Profile builder and setup wizard | Built; awaiting sign-off with a real resume |
| 2 | JobSpy source and basic normalisation | Built |
| 3 | ATS boards, feeds, Nepal boards, company discovery | Built; more sources planned |
| 4 | Salary, locations, remote eligibility, visa, dedup | Built |
| 5 | Matching engine | Built; awaiting a hand-judged ranking check |
| 6 | Lifecycle and expiry | Built |
| 7 | Product UI | Built; awaiting a week of daily use |
| 8 | Scheduling and monitoring | Built; awaiting a 3-day unattended run |
| 9 | Insights, cover letters, map, digest, desktop app | Insights and cover letters built |

[docs/PLAN.md](docs/PLAN.md) has the full plan, what isn't built yet and the decision log.
The UI reference mockup is [docs/mockups/job-matcher-mockup.html](docs/mockups/job-matcher-mockup.html).
