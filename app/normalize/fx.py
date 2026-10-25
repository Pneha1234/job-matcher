"""Daily FX from the ECB reference rates (free). NPR is pegged to INR at 1.6."""

import sqlite3
import xml.etree.ElementTree as ET
from datetime import date

import httpx

from app.settings_store import get_value, set_value

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
NPR_PER_INR = 1.6
KEY = "fx_rates"


def parse_ecb(xml: str) -> dict[str, float]:
    """Units of each currency per 1 EUR."""
    root = ET.fromstring(xml)
    rates = {"EUR": 1.0}
    for el in root.iter():
        if el.get("currency") and el.get("rate"):
            rates[el.get("currency")] = float(el.get("rate"))
    if "INR" in rates:
        rates["NPR"] = rates["INR"] * NPR_PER_INR
    return rates


async def refresh(conn: sqlite3.Connection, transport=None) -> dict[str, float]:
    async with httpx.AsyncClient(timeout=20, transport=transport) as client:
        r = await client.get(ECB_URL)
        r.raise_for_status()
    rates = parse_ecb(r.text)
    set_value(conn, KEY, {"date": date.today().isoformat(), "rates": rates})
    return rates


def rates(conn: sqlite3.Connection) -> dict[str, float]:
    stored = get_value(conn, KEY)
    return stored["rates"] if stored else {}


def is_stale(conn: sqlite3.Connection) -> bool:
    stored = get_value(conn, KEY)
    return not stored or stored["date"] != date.today().isoformat()


def convert(amount: float | None, src: str | None, dst: str, table: dict[str, float]):
    if amount is None or not src:
        return None
    if src == dst:
        return amount
    if src not in table or dst not in table:
        return None
    return amount / table[src] * table[dst]
