"""Salary text -> (min, max, currency, period), then annual amounts in the user's currency.

Rules from docs/PLAN.md: keep the original text; "negotiable", "competitive", "as per
company norms" and friends are not disclosed (None), never 0. When the pay period can't
be told from the text or the size of the number, the annual fields stay None.
"""

import re
from dataclasses import dataclass

PERIOD_FACTORS = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}

UNDISCLOSED = re.compile(
    r"negotiable|competitive|as per (company )?(norms|standards|industry)|not disclosed|"
    r"\bdoe\b|depending on experience|attractive|market rate|best in (the )?industry",
    re.I,
)

SYMBOLS = [
    ("NPR", "NPR"),
    ("NRS", "NPR"),
    ("RS.", "INR"),
    ("RS", "INR"),
    ("INR", "INR"),
    ("₹", "INR"),
    ("€", "EUR"),
    ("EUR", "EUR"),
    ("£", "GBP"),
    ("GBP", "GBP"),
    ("CHF", "CHF"),
    ("SEK", "SEK"),
    ("NOK", "NOK"),
    ("DKK", "DKK"),
    ("PLN", "PLN"),
    ("CA$", "CAD"),
    ("CAD", "CAD"),
    ("A$", "AUD"),
    ("AUD", "AUD"),
    ("SGD", "SGD"),
    ("S$", "SGD"),
    ("AED", "AED"),
    ("USD", "USD"),
    ("US$", "USD"),
    ("$", "USD"),
    ("KR", "SEK"),
]

PERIODS = [
    (r"\bLPA\b|lakhs? per annum", "year"),
    (r"per hour|an hour|/\s*h(ou)?r\b|hourly|\bph\b|p/h|stundenlohn", "hour"),
    (r"per day|a day|/\s*day|daily|day rate|tagessatz", "day"),
    (r"per week|a week|/\s*w(ee)?k\b|weekly", "week"),
    (r"per month|a month|/\s*mo(nth)?\b|monthly|\bp\.?m\.?\b|monatlich|per mensem", "month"),
    (r"per year|a year|/\s*y(ea)?r\b|yearly|annual|annum|\bp\.?a\.?\b|jährlich|\bpa\b", "year"),
]

NUMBER = re.compile(r"(\d+(?:[.,]\d+)*)\s*(k|m|mn|lpa|lakhs?|lacs?|l|cr|crores?)?(?![a-z])", re.I)


@dataclass
class Salary:
    min: float | None
    max: float | None
    currency: str | None
    period: str | None

    def annual(self) -> tuple[float | None, float | None]:
        if self.period is None:
            return None, None
        f = PERIOD_FACTORS[self.period]
        return (
            self.min * f if self.min is not None else None,
            self.max * f if self.max is not None else None,
        )


def _currency(text: str, hint: str | None) -> str | None:
    upper = text.upper()
    for token, code in SYMBOLS:
        if token.isalpha():
            if re.search(rf"(?<![A-Z]){re.escape(token)}(?![A-Z])", upper):
                return _nepal_rupee(code, hint)
        elif token in upper:
            return _nepal_rupee(code, hint)
    if re.search(r"lakh|lac|crore|\bLPA\b", text, re.I):
        return hint if hint in ("INR", "NPR") else "INR"
    return hint


def _nepal_rupee(code: str, hint: str | None) -> str:
    # "Rs" on a Nepali board means Nepali rupees.
    return "NPR" if code == "INR" and hint == "NPR" else code


def _amount(number: str, unit: str | None) -> float:
    # "80,000" and "80.000" are thousands separators; "4,5" is a decimal comma.
    thousands = re.fullmatch(r"\d{1,3}([.,]\d{3})+", number)
    n = re.sub(r"[.,]", "", number) if thousands else number.replace(",", ".")
    value = float(n)
    u = (unit or "").lower()
    if u == "k":
        value *= 1_000
    elif u in ("m", "mn"):
        value *= 1_000_000
    elif u in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
        value *= 100_000
    elif u in ("cr", "crore", "crores"):
        value *= 10_000_000
    return value


def parse_salary(text: str | None, currency_hint: str | None = None) -> Salary | None:
    if not text or not text.strip():
        return None
    if UNDISCLOSED.search(text) and not re.search(r"\d", text):
        return None
    period = next((p for pattern, p in PERIODS if re.search(pattern, text, re.I)), None)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", text)  # "80 000" -> "80000"
    matches = [m for m in NUMBER.finditer(cleaned) if m.group(1)]
    amounts: list[float] = []
    for m in matches:
        unit = m.group(2)
        value = _amount(m.group(1), unit)
        if value < 1:
            continue
        amounts.append(value)
    if not amounts:
        return None
    # "75k-95k" and "75-95k": a bare first number shares the second one's unit.
    if len(matches) >= 2 and not matches[0].group(2) and matches[1].group(2):
        first = _amount(matches[0].group(1), matches[1].group(2))
        if first <= amounts[1]:
            amounts[0] = first
    lo, hi = amounts[0], amounts[1] if len(amounts) > 1 else amounts[0]
    if hi < lo:
        lo, hi = hi, lo
    currency = _currency(text, currency_hint)
    if period is None:
        period = _period_from_size(hi, currency)
    return Salary(min=lo, max=hi, currency=currency, period=period)


def _period_from_size(amount: float, currency: str | None) -> str | None:
    """Only when the number leaves no doubt; otherwise unknown."""
    if currency in ("INR", "NPR"):
        return "year" if amount >= 500_000 else None
    if amount >= 10_000:
        return "year"
    if amount <= 300:
        return "hour"
    return None


def from_parts(
    lo: float | None, hi: float | None, currency: str | None, period: str | None
) -> Salary | None:
    """For sources that give structured numbers (JobSpy, Ashby, Jobicy...)."""
    if lo is None and hi is None:
        return None
    if lo is not None and lo <= 0:
        lo = None
    if hi is not None and hi <= 0:
        hi = None
    if lo is None and hi is None:
        return None
    p = PERIOD_ALIASES.get((period or "").lower())
    if p is None:
        p = _period_from_size(hi or lo, currency)
    return Salary(min=lo, max=hi, currency=(currency or None) and currency.upper(), period=p)


PERIOD_ALIASES = {
    "hourly": "hour",
    "hour": "hour",
    "daily": "day",
    "day": "day",
    "weekly": "week",
    "week": "week",
    "monthly": "month",
    "month": "month",
    "yearly": "year",
    "year": "year",
    "annual": "year",
    "annually": "year",
}
