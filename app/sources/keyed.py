"""Public job APIs that need a free sign-up key. Each searches the saved searches and stays
within its free tier through the daily budget. A source without a key is simply not set
up; it is skipped, not shown as broken."""

import base64

from app.normalize.classify import html_to_text
from app.normalize.geo import load_geo
from app.sources.ats import _dt
from app.sources.base import FetchContext, FetchResult, RawJob, Source


def _split(key: str, sep: str = ":") -> tuple[str, str]:
    left, _, right = key.partition(sep)
    if not left or not right:
        raise ValueError(f"API key must look like 'first{sep}second'")
    return left.strip(), right.strip()


def search_country(search: dict, fallback: list[str]) -> str | None:
    """Country of a saved search's place ("Python · Amsterdam" -> NL), else a target."""
    geo = load_geo()
    if search.get("location") and geo:
        res = geo.resolve(search["location"])
        for loc in res.locations:
            if loc.country_code:
                return loc.country_code
    return fallback[0] if fallback else None


class KeyedSource(Source):
    kind = "feed"
    group = "feeds"
    needs_searches = True
    daily_budget = 50


class Adzuna(KeyedSource):
    name = "adzuna"
    label = "Adzuna"
    via = "Public API (free key)"
    key_help = "developer.adzuna.com: paste as app_id:app_key"
    COUNTRIES = {"GB", "US", "AT", "AU", "BE", "BR", "CA", "CH", "DE", "ES", "FR", "IN", "IT",
                 "MX", "NL", "NZ", "PL", "SG", "ZA"}  # fmt: skip

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        app_id, app_key = _split(ctx.api_key or "")
        result = FetchResult()
        for search in ctx.searches:
            country = search_country(search, ctx.target_countries)
            if country not in self.COUNTRIES:
                result.errors.append(f"'{search['query']}': Adzuna doesn't cover {country}")
                continue
            params = {"app_id": app_id, "app_key": app_key, "what": search["query"],
                      "results_per_page": 50, "max_days_old": 14}  # fmt: skip
            if search.get("location"):
                params["where"] = search["location"]
            data = await ctx.http.get_json(
                f"https://api.adzuna.com/v1/api/jobs/{country.lower()}/search/1", params=params
            )
            for j in data.get("results", []):
                result.jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(j["id"]),
                        url=j["redirect_url"],
                        title=j["title"],
                        company=(j.get("company") or {}).get("display_name") or "Unknown",
                        description=html_to_text(j.get("description")),
                        locations=[(j.get("location") or {}).get("display_name") or ""],
                        job_type_raw=j.get("contract_time") or j.get("contract_type"),
                        # Adzuna marks estimated salaries "predicted"; only real ones count.
                        salary_min=(
                            None if j.get("salary_is_predicted") == "1" else j.get("salary_min")
                        ),
                        salary_max=(
                            None if j.get("salary_is_predicted") == "1" else j.get("salary_max")
                        ),
                        salary_period="year",
                        posted_at=_dt(j.get("created")),
                        country_hint=country,
                    )
                )
        result.requests = ctx.http.requests
        return result


class Jooble(KeyedSource):
    name = "jooble"
    label = "Jooble"
    via = "Public API (free key)"
    key_help = "jooble.org/api/about: paste the key"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = FetchResult()
        for search in ctx.searches:
            r = await ctx.http.request(
                "POST",
                f"https://jooble.org/api/{ctx.api_key}",
                json_body={"keywords": search["query"], "location": search.get("location") or ""},
            )
            for j in r.json().get("jobs", []):
                result.jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(j.get("id") or j["link"]),
                        url=j["link"],
                        title=html_to_text(j["title"]),
                        company=j.get("company") or "Unknown",
                        description=html_to_text(j.get("snippet")),
                        locations=[j.get("location") or ""],
                        job_type_raw=j.get("type"),
                        salary_text=j.get("salary") or None,
                        posted_at=_dt(j.get("updated")),
                    )
                )
        result.requests = ctx.http.requests
        return result


class Reed(KeyedSource):
    name = "reed"
    label = "Reed (UK)"
    via = "Public API (free key)"
    key_help = "reed.co.uk/developers: paste the key"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = FetchResult()
        token = base64.b64encode(f"{ctx.api_key}:".encode()).decode()
        headers = {"Authorization": f"Basic {token}"}  # the key is the username
        for search in ctx.searches:
            params = {"keywords": search["query"], "resultsToTake": 100}
            if search.get("location"):
                params["locationName"] = search["location"]
            data = await ctx.http.get_json(
                "https://www.reed.co.uk/api/1.0/search", params=params, headers=headers
            )
            for j in data.get("results", []):
                result.jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(j["jobId"]),
                        url=j["jobUrl"],
                        title=j["jobTitle"],
                        company=j.get("employerName") or "Unknown",
                        description=html_to_text(j.get("jobDescription")),
                        locations=[f"{j.get('locationName') or ''}, United Kingdom"],
                        salary_min=j.get("minimumSalary"),
                        salary_max=j.get("maximumSalary"),
                        salary_currency=j.get("currency") or "GBP",
                        salary_period="year",
                        posted_at=_reed_date(j.get("date")),
                        valid_through=_reed_date(j.get("expirationDate")),
                        country_hint="GB",
                    )
                )
        result.requests = ctx.http.requests
        return result


def _reed_date(value: str | None):
    """Reed dates are dd/mm/yyyy."""
    if not value or value.count("/") != 2:
        return None
    day, month, year = value.split("/")
    return _dt(f"{year}-{month}-{day}")


class USAJobs(KeyedSource):
    name = "usajobs"
    label = "USAJobs"
    via = "Public API (free key)"
    key_help = "developer.usajobs.gov: paste as your-email|key (the API asks for your email)"
    PERIODS = {"PA": "year", "PH": "hour", "PM": "month", "PD": "day", "BW": None}

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        email, key = _split(ctx.api_key or "", "|")
        headers = {"Authorization-Key": key, "User-Agent": email, "Host": "data.usajobs.gov"}
        result = FetchResult()
        for search in ctx.searches:
            params = {"Keyword": search["query"], "ResultsPerPage": 100}
            if search.get("location"):
                params["LocationName"] = search["location"]
            data = await ctx.http.get_json(
                "https://data.usajobs.gov/api/search", params=params, headers=headers
            )
            items = (data.get("SearchResult") or {}).get("SearchResultItems") or []
            for item in items:
                d = item.get("MatchedObjectDescriptor") or {}
                pay = (d.get("PositionRemuneration") or [{}])[0]
                summary = ((d.get("UserArea") or {}).get("Details") or {}).get("JobSummary")
                result.jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(d.get("PositionID") or item.get("MatchedObjectId")),
                        url=d.get("PositionURI") or "",
                        title=d.get("PositionTitle") or "",
                        company=d.get("OrganizationName") or "US Government",
                        description=summary or d.get("QualificationSummary") or "",
                        locations=[x.get("LocationName") or "" for x in
                                   d.get("PositionLocation") or []],  # fmt: skip
                        salary_min=_float(pay.get("MinimumRange")),
                        salary_max=_float(pay.get("MaximumRange")),
                        salary_currency="USD",
                        salary_period=self.PERIODS.get(pay.get("RateIntervalCode") or ""),
                        posted_at=_dt(d.get("PublicationStartDate")),
                        valid_through=_dt(d.get("ApplicationCloseDate")),
                        country_hint="US",
                    )
                )
        result.requests = ctx.http.requests
        return result


def _float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class FranceTravail(KeyedSource):
    name = "france_travail"
    label = "France Travail"
    via = "Public API (free key)"
    key_help = "francetravail.io (Offres d'emploi v2): paste as client_id:client_secret"
    TOKEN = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        client_id, secret = _split(ctx.api_key or "")
        token = (
            await ctx.http.request(
                "POST",
                self.TOKEN,
                form={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": secret,
                    "scope": "api_offresdemploiv2 o2dsoffre",
                },
                cache_ttl_s=0,
            )
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        result = FetchResult()
        for search in ctx.searches:
            data = await ctx.http.get_json(
                "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
                params={"motsCles": search["query"], "range": "0-99"},
                headers=headers,
            )
            for j in data.get("resultats", []):
                origin = (j.get("origineOffre") or {}).get("urlOrigine")
                result.jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(j["id"]),
                        url=origin
                        or f"https://candidat.francetravail.fr/offres/recherche/"
                        f"detail/{j['id']}",
                        title=j.get("intitule") or "",
                        company=(j.get("entreprise") or {}).get("nom") or "Unknown",
                        description=j.get("description") or "",
                        locations=[f"{(j.get('lieuTravail') or {}).get('libelle') or ''}, France"],
                        job_type_raw=j.get("typeContratLibelle") or j.get("typeContrat"),
                        salary_text=(j.get("salaire") or {}).get("libelle"),
                        salary_currency="EUR",
                        posted_at=_dt(j.get("dateCreation")),
                        country_hint="FR",
                        language_hint="fr",
                    )
                )
        result.requests = ctx.http.requests
        return result


KEYED_SOURCES = [Adzuna, Jooble, Reed, USAJobs, FranceTravail]
