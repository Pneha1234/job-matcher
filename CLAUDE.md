# Job Matcher

Personal, local-first job matcher. Read [docs/PLAN.md](docs/PLAN.md) first — it
is the source of truth for scope, sources, stack and phases.

## Rules

- **Keep the plan current.** Any decision made or reversed goes into
  `docs/PLAN.md` (and its decision log) in the same change.
- **Free sources only.** Never add a paid API, paid proxy or paid scraping
  service. Free sign-up keys and free tiers are fine; give each a daily budget.
- **Local LLM only.** Resume and profile data never go to a cloud model.
- **Scrape politely.** Delays, small batches, caching. Never scrape with the
  user's logged-in accounts. Never bypass CAPTCHAs or bot detection — pause the
  source instead.
- **Never hard delete** jobs, applications or profile versions; use status fields.
- **LLM output is validated** with Pydantic; failures become "unscored", never a
  made-up number.
- **The UI is the product.** Every feature must be usable from the screens; the
  mockup in `docs/mockups/` is the visual reference.
- Don't commit or push unless asked.
