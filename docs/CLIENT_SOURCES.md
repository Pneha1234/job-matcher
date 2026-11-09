# Client Matcher: opportunities a company can apply for

The Client Matcher looks for work a consultancy can apply for **as a company**: a
tender, a call for proposals, a broker's assignment, a subcontract. It does not look for
jobs for a person. This page lists where those opportunities are published in Europe
(the EU, the EEA and the UK), which are free to read, and how each one fits the pipeline
in [ARCHITECTURE.md](ARCHITECTURE.md). Nothing here is built. Researched on 2026-11-09.

The same rules as Job Matcher apply. Free sources only, so paid tender alert services,
paid wrappers and scrapers sold on Apify are out. Free sign-up keys are fine, with a
daily budget. Only public pages are read: a platform whose assignments sit behind a
login is never scraped, and its assignments come in through the existing "paste a link
or text" import instead. The app never submits a bid or an application; you do.

## The four kinds of opportunity

| Kind | What you apply for | Where it comes from |
|---|---|---|
| **Project** | One tender, one lot of a tender, or one call for proposals | TED, national tender portals, the EU Funding & Tenders portal |
| **Framework or DPS** | A place on a buyer's supplier list, then mini-competitions inside it | The same tender portals; in Finland, Hansel's dynamic purchasing systems |
| **Partner network** | Assignments a consultant broker publishes for companies and freelancers | Broker marketplaces such as Brainville |
| **Subcontract** | Work under a larger supplier that won a contract | Contract award notices on TED, which name the winners |

A **direct client**, a company that hires engineers today and might buy a project from
you, stays the fifth, slower route. It comes from the job data Job Matcher already
collects, and it is covered at the end of this page.

## 1. Public tenders: TED first

TED (Tenders Electronic Daily) publishes every EU public tender above the EU thresholds,
from all member states. It is the single best source for this mode.

- **Access.** The Search API needs no key: "The Search API does not require a key." The
  endpoint is `https://api.ted.europa.eu/v3/notices/search`. An optional free key raises
  the limits. Checked on the official docs.
- **Filtering.** CPV codes select the work: 72000000 covers IT services (consulting,
  software development, internet and support), with narrower codes under it. Notice
  types separate open calls from award notices.
- **Subcontracting fields.** eForms records per lot whether subcontracting is allowed or
  required (OPT-150, BT-65). That tells you whether a small company can join through a
  larger bidder.
- **One catch.** The search works on whole notices, not lots. A notice can match because
  of a different lot than the one you care about, so lots are filtered in code after
  fetching, which suits the "code decides" rule anyway.

National portals carry the smaller tenders below the EU thresholds. In Finland that is
Hilma, with a free key (the `avp-read` product on its developer portal); current Finnish
tenders above the threshold come from TED anyway. Other countries' portals, such as the
UK's Find a Tender, Norway's Doffin and Germany's federal portals, are not researched yet.

## 2. Frameworks and dynamic purchasing systems

Many public buyers don't tender each IT job separately. They set up a framework or a
dynamic purchasing system (DPS) first, and then run quick mini-competitions among the
suppliers on it. For a small consultancy, getting onto the right DPS is often worth more
than any single tender.

- A DPS is open to every supplier that meets its criteria for its whole lifetime, so you
  can apply at any time, not only in a short window.
- Suppliers aren't compared when they join; the competition happens later, per
  assignment.
- In Finland, Hansel is the central government's joint procurement unit. Its IT
  consulting DPS for 2023 to 2028 is in force, and it has newer ICT expert services
  procurements. The
  notices appear on TED and Hilma, so the tender sources above already find them; the
  Client Matcher only needs to label them "join once, then bid".

## 3. Broker marketplaces (partner networks)

Consultant brokers publish assignments from their clients, and a consultancy can usually
answer as a company.

- **Brainville** calls itself the largest independent marketplace for freelancers and
  consultants in the Nordics, and most Nordic brokers post there, Emagine among them.
  Its assignment (requisition) pages are public, and its robots.txt does not block them,
  with a sitemap available. Its terms of use still need reading before any crawler is
  written.
- **Ework (Verama)** asks you to create a profile to apply. Assume its assignments are
  behind a login, so it is a manual-import source unless that turns out wrong.
- **freelancermap and GULP** (Germany) have no public API. Third-party scrapers exist,
  which says nothing about their terms. Treat them as manual import until their terms
  are checked.

Finnish broker platforms are not researched yet.

## 4. Subcontracts: follow the winners

Contract award notices on TED name who won. Finnish IT award notices name suppliers such
as Tietoevry, Accenture, Digia and Innofactor, and smaller ones such as Nitor and
Reaktor, and some notices state that the work is likely to be subcontracted. Each winner becomes a subcontracting-partner lead, with the award as its
reason: "won a 4-year IT framework with the state, subcontracting expected". This needs
no new source, only award notices from the same TED API.

## 5. EU funding calls

The EU Funding & Tenders portal publishes calls for proposals (Horizon Europe, Digital
Europe and others) where companies apply, often as one partner in a consortium. Third
parties describe a public search API behind the portal that needs no account; one code
sample passes a public key value. This needs checking against the Commission's own API
page before building. Calls are slow to win and paperwork-heavy, so they rank below
tenders and assignments unless you ask for them.

## How it fits the pipeline

- **Ingest.** Tender notices, assignments and calls become one kind of record: an
  opportunity with a buyer, a country, a deadline, a value when given, CPV codes or
  skills, lots and subcontracting terms. Polite fetching, budgets, deduplication (the
  same tender on TED and Hilma) and lifecycle (past the deadline means expired) are all
  reused from Job Matcher.
- **Retrieve.** Opportunities are embedded and compared with your company profile: your
  services, stack, references and team size.
- **Reason.** The local LLM classifies each one: requirements matched, partial or
  missing; whether you qualify (turnover, references, certifications, language); whether
  you can bid alone, need a partner or should go in as a subcontractor.
- **Rank.** Code computes the fit % from those classes with your weights, plus hard
  filters such as "deadline at least 10 days away" and "country I can deliver in".
- **Track.** A bid pipeline replaces the application board: found → qualifying → bid or
  join → submitted → won / lost, with the same event history.

## The slower route: direct clients

A company hiring backend or AI engineers may also buy a project from a consultancy.
Job Matcher already collects those job posts, so this route costs no new source. The
company behind the post is enriched from its national business register: a name, an ID
and an industry code. Some registers are free and keyless with search (Finland's PRH,
Norway's Brønnøysund, France's Recherche d'entreprises, Czechia's ARES, the UK's
Companies House with a free key, Estonia's bulk files). Others need a sign-up or work only
by company number (Sweden, Belgium, Denmark, the Netherlands, Poland). Germany has no
free official API. Industry codes (NACE) also help tell a consultancy, which may become a
partner, from a product company, which may become a client. The register stores
companies, never people.

## Suggested order

1. TED tenders and award notices, filtered to IT CPV codes and the countries you can
   deliver in. This alone gives projects, frameworks, DPS entries and subcontracting
   leads.
2. Brainville assignments, after checking its terms.
3. Hilma and other national portals for smaller tenders.
4. EU funding calls, after checking the official API.
5. Direct clients from job posts plus register enrichment.

## Open questions

- Brainville's terms of use; whether Ework, freelancermap or GULP show any assignments
  without a login.
- The exact TED search field names for CPV codes, lots and SME suitability (check the
  Expert Search field list).
- What your company profile needs for qualification checks: turnover, references,
  certifications, languages, team size.
- Finnish and other national broker platforms, and national tender portals beyond Hilma.

## Sources

- [TED API documentation](https://docs.ted.europa.eu/api/latest/index.html) and [TED Search API](https://docs.ted.europa.eu/api/endpoints/ted-europa-eu.html)
- [eForms subcontracting at lot level, OPT-150](https://docs.ted.europa.eu/eforms/1.13/reference/business-terms/OPT-150.html) and [BT-65](https://docs.ted.europa.eu/eforms/1.8/reference/business-terms/BT-65.html)
- [TED reusers Q&A: search works on notices, not lots](https://op.europa.eu/en/web/ted-reusers-workshops/questions_and_answers_2024_04_17)
- [Hansel ICT services and software, presentation 2025](https://www.hansel.fi/media/filer_public/eb/b7/ebb7bcde-a13a-4db4-bd55-b656ab5cb5ea/ict-palvelut_ja_ohjelmistot_2025_778_esittelymateriaali.pdf)
- [Hansel IT consulting DPS 2023–2028 (KPMG supplier page)](https://kpmg.com/fi/fi/toimialat/julkishallinto/kpmg-julkishallinnon-sopimustoimittajana.html)
- [Hilma API (third-party MCP README)](https://crossaitools.com/mcp/aimiten/hilma-mcp)
- [Brainville](https://www.brainville.com/en/) and [its broker directory](https://www.brainville.com/PublicPage/Brokers?lang=en)
- [Ework: applying for assignments on Verama](https://www.eworkgroup.com/eworkplus/how-to-create-a-great-profile-on-eworks-verama-and-apply-for-assignments)
- [freelancermap has no public API (third-party)](https://apify.com/solidcode/freelancermap-scraper.md)
- [EU Funding & Tenders portal API guide (EMDESK)](https://www.emdesk.com/horizon-2020-horizon-europe-basics-guide/eu-funding-tenders-portal-api-guide)
- [Finnish IT tender example on TED](https://ted.europa.eu/en/notice/587755-2023/pdf)
- [Implementing Regulation (EU) 2023/138, high-value datasets](https://www.lexisnexis.com/en-gb/legal/news/new-high-value-datasets-rules-start-applying-in-eu)
- [PRH open data](https://avoindata.prh.fi/en), [Brønnøysund](https://data.norge.no/en/datasets/b022f14a-689a-3f71-ae6c-0266c220b331/the-register-of-business-enterprises), [Estonian open data](https://avaandmed.ariregister.rik.ee/en/downloading-open-data), [Companies House rate limits](https://developer-specs.company-information.service.gov.uk/guides/rateLimiting), [KVK open dataset API](https://developers.kvk.nl/documentation/open-dataset-basis-bedrijfsgegevens-api)
