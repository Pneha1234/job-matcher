# Architecture

Job Matcher is a pipeline: **Ingest → Retrieve → Reason → Rank → Track**. This page shows
what it does today and how the same pipeline becomes a second mode, the Client Matcher,
which is proposed and not built yet. Scope and decisions live in [PLAN.md](PLAN.md).

## The approach

One rule shapes the design: **LLM for perception, code for judgement.** The local model
reads messy text and classifies it. Code makes every decision that produces a number.

- **Ingest.** Turn many messy sources into one clean, deduplicated set of records.
- **Retrieve.** Cheap vector search narrows thousands of records to a shortlist.
- **Reason.** The local LLM reads each shortlisted record and classifies the fit, as
  schema-validated JSON.
- **Rank.** Deterministic code turns those classes into a percentage with your weights.
- **Track.** A small state machine follows what you did with each match.

Retrieval is cheap and the LLM is expensive, so the LLM only runs on the shortlist. That
is what lets the whole thing run on a laptop.

## 1. Job Matcher today

```mermaid
flowchart LR
    subgraph IN["Ingest"]
        direction TB
        S1["Job boards and feeds<br/>JobSpy, Remotive, HN, ..."]
        S2["Company career pages<br/>Greenhouse, Lever, Workday, ...<br/>JSON-LD crawl"]
        S3["Free-key APIs<br/>Adzuna, Reed, ..."]
        N["Normalise<br/>salary + FX, GeoNames,<br/>remote, visa, language"]
        D["Entity resolution<br/>canonical key +<br/>embedding similarity"]
        S1 --> N
        S2 --> N
        S3 --> N
        N --> D
    end

    subgraph P["Your profile"]
        direction TB
        CV["CV (PDF / DOCX)"]
        GH["GitHub"]
        LI["LinkedIn export"]
        PX["Profile extraction<br/>qwen2.5:14b"]
        CV --> PX
        GH --> PX
        LI --> PX
    end

    R["Retrieve<br/>bge-m3 embeddings<br/>kNN + hard filters<br/>thousands → 150"]
    RE["Reason<br/>qwen2.5:7b, local<br/>matched / partial / missing"]
    RK["Rank<br/>weighted % in code"]
    UI["Matches and gaps<br/>explanation, missing skills"]
    T["Application tracker<br/>saved → applied → interview → offer"]
    L["Lifecycle<br/>active → expired / stale"]

    D --> R
    PX --> R
    R --> RE --> RK --> UI --> T
    D --> L
```

**Ingest.** 35 source plugins: job boards and feeds, company career pages on nine ATS
platforms, a schema.org JSON-LD crawler for other career sites, and free-key APIs. New
companies are found through Common Crawl and from links inside postings. Salaries become
annual amounts in your currency, locations resolve offline with GeoNames, and remote
scope, visa and language requirements are extracted. One posting on five boards becomes
one job with five sources.

**Your profile.** Built from your CV, your public GitHub, your portfolio and your
LinkedIn data export. LinkedIn is never scraped. You review the result before it is used,
and every save is a new version.

**Retrieve.** Jobs and your profile are embedded with `bge-m3`. A k-nearest-neighbour
search in `sqlite-vec` takes the closest jobs, hard filters remove the ones you can't
take (location eligibility, job type, minimum salary, inactive), and the best 150 go on.

**Reason.** For each shortlisted job, `qwen2.5:7b` classifies the required and
nice-to-have skills as matched, partial or missing, and rates seniority, domain and
location fit. The output must match a schema. An answer that doesn't validate is retried
once, then the job shows as "unscored".

**Rank.** Code maps those classes to numbers and takes a weighted average with your
weights. A part the posting gives no basis for drops out instead of counting as zero.
Changing a weight recomputes every percentage at once, with no LLM call.

**Track and lifecycle.** You save and move jobs across a board, and every status change is
kept. A job that disappears from its source twice, passes its deadline or stops answering
is marked expired with a reason. Nothing is deleted.

## The local AI

Everything runs on your own machine through Ollama. Your CV and profile never go to a
cloud model or to any API.

| Model | Job | Why this one |
|---|---|---|
| `qwen2.5:14b` | Reads your CV, pasted postings, cover-letter drafts | Runs rarely, so it can be the careful one |
| `qwen2.5:7b` | Scores every shortlisted job | Runs thousands of times, so it has to be fast |
| `bge-m3` | Embeddings for retrieval and dedup | Multilingual, so Dutch, German, Hindi and Nepali postings compare fairly |

Speed on a normal laptop came from three changes: a smaller model for scoring, capped
answers (on a laptop, answer length is most of the time), and three jobs scored in
parallel. Scoring went from about 35 seconds a job to about 5. The measurements are in the
PLAN.md decision log (2026-10-26).

Scoring and CV reading need no internet once the models are pulled. Only fetching new
jobs does.

## 2. Client Matcher (proposed)

Same pipeline, different question. Instead of "which job fits me?", it asks "which
opportunity can my company apply for and win?". The opportunities are ones a company
applies for, not jobs for a person: public tenders, places on frameworks and dynamic
purchasing systems, broker assignments, subcontracts and EU funding calls, across Europe.
The colours show what is reused as it is, what is extended, and what is new.

```mermaid
flowchart LR
    subgraph IN["Ingest"]
        direction TB
        F1["Public tenders (TED, Hilma)<br/>projects, frameworks, DPS"]
        F2["Award notices<br/>winners = subcontract leads"]
        F3["Broker assignments<br/>public pages or pasted links"]
        F4["EU funding calls"]
        N["Polite fetching, normalise,<br/>dedup, deadline lifecycle"]
        F1 --> N
        F2 --> N
        F3 --> N
        F4 --> N
    end

    subgraph P["Your company"]
        direction TB
        CV["CVs, GitHub, references"]
        SV["Services, stack, turnover,<br/>certifications, languages"]
        PX["Company profile"]
        CV --> PX
        SV --> PX
    end

    R["Retrieve<br/>opportunity ↔ company similarity<br/>kNN + hard filters"]
    C["Classify<br/>project · framework / DPS ·<br/>broker assignment · subcontract"]
    RE["Reason<br/>local LLM: requirements met?<br/>qualify? bid alone or partner?"]
    RK["Rank<br/>bid fit % in code"]
    UI["Fit and gaps<br/>why this one, what's missing"]
    T["Bid pipeline<br/>found → qualifying → bid →<br/>submitted → won / lost"]

    N --> R
    PX --> R
    R --> C --> RE --> RK --> UI --> T

    classDef reused fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef extended fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef new fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    class N,CV,R,RE,RK reused
    class F3,PX,UI,T extended
    class F1,F2,F4,SV,C new
```

**Legend:** green is reused as it is, amber is extended, blue is new.

| Stage | Job Matcher | Client Matcher | Reuse |
|---|---|---|---|
| Ingest | Job postings from 35 sources | Tenders, award notices, broker assignments and EU calls | Polite fetching, budgets, dedup and deadline expiry reused; the "paste a link" import covers broker sites behind a login; opportunity sources new |
| Profile | You as a candidate | Your company: services, stack, references, turnover, certifications | Extended |
| Retrieve | Job ↔ profile similarity | Opportunity ↔ company similarity | Reused |
| Classify | Not needed | Project, framework or DPS, broker assignment, subcontract | New |
| Reason | Skill match per job | Requirements met, qualification, bid alone or with a partner | Same pattern: the LLM classifies, output is schema-validated |
| Rank | Match % | Bid fit % | Same weighted code, new weights |
| Track | Application board | Bid pipeline | Same state machine and event history, new stages |

**The four kinds of opportunity.** A project is one tender, one lot or one call. A
framework or DPS is a place on a buyer's supplier list, joined once, with
mini-competitions after. A broker assignment comes from a consultant broker's
marketplace. A subcontract is work under a larger supplier, found through award notices
that name the winner. Companies that hire engineers stay a slower fifth route, from the
job data Job Matcher already collects.

**Data model, roughly.** An `opportunities` table holds buyer, country, deadline, value,
CPV codes, lots and subcontracting terms, with sources and lifecycle like `jobs`. A
company profile sits beside the personal one. Bid fit scores follow `match_scores`, and
bids with their events follow `applications` and `application_events`.

**The same rules hold.** Free sources only, the local LLM only, polite fetching, public
pages only (never a logged-in session), nothing hard deleted, and an "unscored" result
rather than a guessed number. The app never submits a bid or sends a message; you do.

### Open questions

- Sources are researched in [CLIENT_SOURCES.md](CLIENT_SOURCES.md), with a suggested
  order: TED first, then broker assignments, national portals, EU calls and direct
  clients. Rows based on third-party guides still need checking against official docs.
- Brainville's terms of use, and whether other brokers show any assignments without a
  login.
- What the company profile needs for qualification checks, and the bid fit weights.
