"""Offline location resolution with the GeoNames dataset (cities15000, CC BY 4.0).

``make geonames`` (or the API on first start) downloads three files into data/geonames.
Resolution never guesses: an ambiguous city with no country hint, no known company office
and no clearly dominant candidate stays "Location unclear".
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import get_settings
from app.normalize.regions import REGION_WORDS, WORLDWIDE_WORDS
from app.util import ascii_fold

BASE = "https://download.geonames.org/export/dump/"
FILES = ("cities15000.zip", "admin1CodesASCII.txt", "countryInfo.txt")
# A candidate this many times bigger than the runner-up counts as unambiguous
# (London UK vs London, Ontario). See the decision log.
DOMINANCE = 20

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}  # fmt: skip

COUNTRY_ALIASES = {
    "usa": "US", "us": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US",
    "america": "US", "uk": "GB", "u.k.": "GB", "great britain": "GB", "britain": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "holland": "NL", "the netherlands": "NL", "nederland": "NL", "deutschland": "DE",
    "uae": "AE", "emirates": "AE", "south korea": "KR", "korea": "KR", "czechia": "CZ",
    "czech republic": "CZ", "turkiye": "TR", "russia": "RU", "vietnam": "VN",
    "schweiz": "CH", "suisse": "CH", "osterreich": "AT", "espana": "ES", "sverige": "SE",
    "norge": "NO", "danmark": "DK", "suomi": "FI", "polska": "PL", "italia": "IT",
    "bharat": "IN", "hong kong sar": "HK", "ksa": "SA",
}  # fmt: skip

# Province/state abbreviations whose GeoNames admin1 codes are numeric.
SUBDIVISIONS = {
    "CA": {"AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NS": "07", "ON": "08",
           "PE": "09", "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14"},
    "AU": {"ACT": "01", "NSW": "02", "NT": "03", "QLD": "04", "SA": "05", "TAS": "06",
           "VIC": "07", "WA": "08"},
}  # fmt: skip

WORK_MODE_WORDS = re.compile(
    r"\b(hybrid|on[- ]?site|in[- ]office|office[- ]based|work from office|wfo|flexible)\b", re.I
)
SCOPE_NOISE = re.compile(r"\b(only|based|residents?|citizens?|time ?zones?|hours?)\b", re.I)

CITY_ALIASES = {"kathmandu valley": "kathmandu", "ktm": "kathmandu", "patan": "lalitpur"}

REMOTE_WORDS = re.compile(
    r"\b(remote|anywhere|worldwide|work from home|wfh|telecommute|distributed|home[- ]?based)\b",
    re.I,
)


@dataclass
class City:
    geonames_id: int
    name: str
    country: str
    admin1: str
    lat: float
    lon: float
    population: int
    timezone: str = ""


@dataclass
class Location:
    raw: str
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    geonames_id: int | None = None
    resolved: bool = False
    timezone: str | None = None


@dataclass
class Resolution:
    locations: list[Location] = field(default_factory=list)
    remote: bool = False
    remote_countries: set[str] = field(default_factory=set)
    remote_regions: set[str] = field(default_factory=set)
    worldwide: bool = False


def data_dir() -> Path:
    return Path(get_settings().db_path).parent / "geonames"


def is_downloaded(folder: Path | None = None) -> bool:
    folder = folder or data_dir()
    return all((folder / f.replace(".zip", ".txt")).exists() for f in FILES)


async def download(folder: Path | None = None, transport=None) -> None:
    folder = folder or data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, transport=transport) as client:
        for name in FILES:
            r = await client.get(BASE + name)
            r.raise_for_status()
            if name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    (folder / name.replace(".zip", ".txt")).write_bytes(
                        zf.read(name.replace(".zip", ".txt"))
                    )
            else:
                (folder / name).write_bytes(r.content)
    load_geo.cache_clear()


class Geo:
    def __init__(self, folder: Path):
        self.countries: dict[str, str] = {}  # code -> name
        self.country_keys: dict[str, str] = dict(COUNTRY_ALIASES)  # folded name -> code
        self.continent: dict[str, str] = {}
        self.admin1: dict[str, str] = {}  # "US.CA" -> "California"
        self.admin1_keys: dict[tuple[str, str], str] = {}  # (cc, folded name) -> admin code
        self.admin1_names: dict[str, list[tuple[str, str]]] = {}  # folded name -> [(cc, code)]
        self.cities: dict[str, list[City]] = {}
        self.by_id: dict[int, City] = {}
        self._load(folder)

    def _load(self, folder: Path) -> None:
        for line in (folder / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split("\t")
            code, iso3, name, continent = cols[0], cols[1], cols[4], cols[8]
            self.countries[code] = name
            self.continent[code] = continent
            self.country_keys[ascii_fold(name)] = code
            self.country_keys[iso3.lower()] = code
        for line in (folder / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            key, name = cols[0], cols[1]
            self.admin1[key] = name
            cc, code = key.split(".", 1)
            self.admin1_keys[(cc, ascii_fold(name))] = code
            self.admin1_names.setdefault(ascii_fold(name), []).append((cc, code))
            if len(cols) > 2:
                self.admin1_keys[(cc, ascii_fold(cols[2]))] = code
        for line in (folder / "cities15000.txt").read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if len(cols) < 15:
                continue
            city = City(
                geonames_id=int(cols[0]),
                name=cols[1],
                country=cols[8],
                admin1=cols[10],
                lat=float(cols[4]),
                lon=float(cols[5]),
                population=int(cols[14] or 0),
                timezone=cols[17] if len(cols) > 17 else "",
            )
            self.by_id[city.geonames_id] = city
            names = {cols[1], cols[2]}
            # Latin-script aliases only; other scripts fold to nothing and are skipped.
            names.update(a for a in cols[3].split(",") if a and len(a) <= 40)
            for name in names:
                key = ascii_fold(name)
                if key:
                    self.cities.setdefault(key, []).append(city)

    def country_code(self, text: str) -> str | None:
        t = ascii_fold(text).strip(" .")
        for key in (t, t.removeprefix("the "), f"the {t}"):
            if key in self.country_keys:
                return self.country_keys[key]
        if len(text.strip()) == 2 and text.strip().isupper() and text.strip() in self.countries:
            return text.strip()
        return None

    def search(self, text: str, limit: int = 8) -> list[City]:
        """Cities whose name starts with ``text``, biggest first, for the "near" picker."""
        prefix = ascii_fold(text)
        if len(prefix) < 2:
            return []
        found = {
            c.geonames_id: c
            for key, cities in self.cities.items()
            if key.startswith(prefix)
            for c in cities
        }
        return sorted(found.values(), key=lambda c: c.population, reverse=True)[:limit]

    def country_name(self, code: str | None) -> str | None:
        return self.countries.get(code) if code else None

    def resolve(
        self, raw: str, country_hint: str | None = None, offices: set[str] | None = None
    ) -> Resolution:
        """Resolve one posted location string, which may hold several places."""
        out = Resolution()
        for part in re.split(r"\s*(?:;|\||/| or |\n| & )\s*", raw or ""):
            if part.strip():
                self._resolve_one(part.strip(), country_hint, offices or set(), out)
        return out

    def _resolve_one(self, text: str, hint: str | None, offices: set[str], out: Resolution):
        scope_text = text
        if REMOTE_WORDS.search(text):
            out.remote = True
        inner = " ".join(re.findall(r"\(([^)]*)\)", text))
        text_wo = re.sub(r"\([^)]*\)", " ", text)
        text_wo = WORK_MODE_WORDS.sub(" ", REMOTE_WORDS.sub(" ", text_wo))
        text_wo = re.sub(r"^[\s,:\-–—]+|[\s,:\-–—]+$", "", text_wo)
        if out.remote:
            self._remote_scope(inner + ", " + scope_text, out)
            if not text_wo or self._is_scope_only(text_wo):
                return
        if self._is_scope_only(text_wo):
            if not out.remote:
                # "EMEA" or "Worldwide" on its own isn't a place; keep it as scope.
                self._remote_scope(text_wo, out)
            return
        loc = self._place(text_wo or scope_text, hint, offices)
        if out.remote and not loc.country_code:
            return  # leftover words in a remote line ("anywhere in the world")
        out.locations.append(loc)
        if out.remote and loc.country_code and not loc.city:
            out.remote_countries.add(loc.country_code)

    def _is_scope_only(self, text: str) -> bool:
        t = ascii_fold(text).strip(" .")
        return t in REGION_WORDS or t in WORLDWIDE_WORDS or t == ""

    def _remote_scope(self, text: str, out: Resolution) -> None:
        folded = ascii_fold(text)
        for word in WORLDWIDE_WORDS:
            if re.search(rf"\b{word}\b", folded):
                out.worldwide = True
        for word, region in REGION_WORDS.items():
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", folded):
                out.remote_regions.add(region)
        for token in re.split(r"[,/;()]| and |-|–", SCOPE_NOISE.sub(" ", text)):
            token = token.strip(" .")
            if not token:
                continue
            code = self.country_code(token)
            if code:
                out.remote_countries.add(code)
            elif token.upper() in US_STATES and len(token) == 2:
                out.remote_countries.add("US")

    def _place(self, text: str, hint: str | None, offices: set[str]) -> Location:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts:
            return Location(raw=text)
        # A trailing "DE" can be Germany or Delaware: try each reading, keep the one that
        # finds the city.
        best: Location | None = None
        for cc, admin, rest in self._readings(parts):
            loc = self._locate(text, rest, cc, admin, hint, offices)
            if loc.city or (cc and not rest):
                return loc  # a city, or a string that is only a country ("Ireland")
            if best is None or (loc.country_code and not best.country_code):
                best = loc
        return best or Location(raw=text)

    def _readings(self, parts: list[str]) -> list[tuple[str | None, str | None, list[str]]]:
        last = parts[-1]
        out: list[tuple[str | None, str | None, list[str]]] = []
        sub = last.strip().upper().replace(".", "")
        if len(parts) > 1:
            if sub in US_STATES:
                out.append(("US", sub, parts[:-1]))
            for country, mapping in SUBDIVISIONS.items():
                if sub in mapping:
                    out.append((country, mapping[sub], parts[:-1]))
        if code := self.country_code(last):
            rest = parts[:-1]
            admin = None
            if len(rest) > 1:
                admin = self.admin1_keys.get((code, ascii_fold(rest[-1])))
                if admin:
                    rest = rest[:-1]
            out.append((code, admin, rest))
        if len(parts) > 1:  # "Mumbai, Maharashtra": a region with no country
            for cc, admin in self.admin1_names.get(ascii_fold(last), []):
                out.append((cc, admin, parts[:-1]))
        out.append((None, None, parts))
        return out

    def _locate(self, raw, parts, cc, admin, hint, offices) -> Location:
        loc = Location(raw=raw)
        if not parts:
            if cc:
                loc.country_code, loc.resolved = cc, True
                if admin:
                    loc.region = self.admin1.get(f"{cc}.{admin}")
            return loc
        if len(parts) > 1 and not cc:
            # A trailing part we couldn't read ("London, XY") means we don't know enough.
            return loc
        name = ascii_fold(parts[0])
        name = CITY_ALIASES.get(name, name)
        candidates = self.cities.get(name, [])
        if not candidates and len(parts) == 1 and not cc:
            if code := self.country_code(parts[0]):
                loc.country_code, loc.resolved = code, True
            return loc
        if cc:
            candidates = [c for c in candidates if c.country == cc]
        if admin:
            candidates = [c for c in candidates if c.admin1 == admin]
        city = self._pick(candidates, name, hint if not cc else None, offices if not cc else set())
        if city:
            loc.city = city.name
            loc.region = self.admin1.get(f"{city.country}.{city.admin1}")
            loc.country_code = city.country
            loc.lat, loc.lon, loc.geonames_id = city.lat, city.lon, city.geonames_id
            loc.timezone = city.timezone or None
            loc.resolved = True
        elif cc:
            loc.country_code = cc  # the country is certain even if the city is not
            region = admin or self.admin1_keys.get((cc, ascii_fold(parts[-1])))
            if region and len(parts) == 1 and not admin:
                # "Florida, United States": a region, not a city
                loc.region, loc.resolved = self.admin1.get(f"{cc}.{region}"), True
            elif admin:
                loc.region = self.admin1.get(f"{cc}.{admin}")
        return loc

    def _pick(
        self, candidates: list[City], name: str, hint: str | None, offices: set[str]
    ) -> City | None:
        unique = list({c.geonames_id: c for c in candidates}.values())
        if not unique:
            return None
        for narrowing in (hint and {hint}, offices):
            if narrowing:
                subset = [c for c in unique if c.country in narrowing]
                if subset:
                    unique = subset
                    break
        # Prefer cities whose main name is the text over ones that only list it as an alias,
        # unless an alias-only city is bigger ("Lalitpur" is also Patan, Nepal).
        exact = [c for c in unique if ascii_fold(c.name) == name]
        alias_only = [c for c in unique if c not in exact]
        if exact and max(c.population for c in exact) >= max(
            (c.population for c in alias_only), default=0
        ):
            unique = exact
        unique.sort(key=lambda c: c.population, reverse=True)
        if len(unique) == 1:
            return unique[0]
        same_place = all(c.country == unique[0].country for c in unique[:2])
        top, runner_up = unique[0].population, max(unique[1].population, 1)
        if top >= DOMINANCE * runner_up or (same_place and top >= 5 * runner_up):
            return unique[0]
        return None


def utc_offset_minutes(timezone: str | None) -> int | None:
    """Current UTC offset of an IANA zone; DST shifts by an hour are tolerable here."""
    if not timezone:
        return None
    try:
        offset = datetime.now(ZoneInfo(timezone)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return int(offset.total_seconds() // 60) if offset is not None else None


@lru_cache(maxsize=4)
def load_geo(folder: str | None = None) -> Geo | None:
    path = Path(folder) if folder else data_dir()
    if not is_downloaded(path):
        return None
    return Geo(path)
