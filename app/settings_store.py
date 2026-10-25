"""User settings kept in the ``settings`` table as one JSON document.

Defaults live here; the stored document only overrides what the user changed.
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.util import dumps, loads, now_iso

KEY = "app"

JobType = Literal["full-time", "contract", "freelance", "part-time", "internship"]


class Weights(BaseModel):
    """Plan defaults: required 50, nice-to-have 15, seniority 15, domain 10, location 10."""

    required: int = Field(50, ge=0, le=100)
    nice: int = Field(15, ge=0, le=100)
    seniority: int = Field(15, ge=0, le=100)
    domain: int = Field(10, ge=0, le=100)
    location: int = Field(10, ge=0, le=100)


class Schedules(BaseModel):
    """Hours between runs per source group; 0 turns a group's schedule off."""

    jobspy: int = Field(6, ge=0, le=168)
    ats: int = Field(12, ge=0, le=168)
    feeds: int = Field(6, ge=0, le=168)
    gentle: int = Field(8, ge=0, le=168)  # small sites such as Nepali boards


class AppSettings(BaseModel):
    weights: Weights = Weights()
    currency: Literal["EUR", "USD", "GBP", "INR", "NPR", "CHF", "SEK", "NOK", "CAD", "AUD"] = "EUR"
    home_country: str | None = None  # ISO 3166-1 alpha-2; drives remote eligibility
    home_city: str | None = None
    target_countries: list[str] = []  # empty = no location hard filter
    open_to_relocation: bool = False
    needs_visa: bool = False
    job_types: list[JobType] = []  # empty = all types
    min_salary: int | None = Field(None, ge=0)  # annual, in ``currency``
    llm_model: str | None = None  # None = JM_LLM_MODEL
    scoring_model: str | None = None  # None = JM_SCORING_MODEL
    shortlist_size: int = Field(150, ge=10, le=1000)
    notify_threshold: int = Field(85, ge=0, le=100)
    notify: bool = True
    schedules: Schedules = Schedules()
    scheduler_enabled: bool = True

    @field_validator("home_country")
    @classmethod
    def _upper_country(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if len(v) != 2 or not v.isalpha():
            raise ValueError("use a two-letter country code, like NP or NL")
        return v.upper()

    @field_validator("target_countries")
    @classmethod
    def _upper_targets(cls, v: list[str]) -> list[str]:
        out = []
        for code in v:
            if len(code) != 2 or not code.isalpha():
                raise ValueError(f"'{code}' is not a two-letter country code")
            if code.upper() not in out:
                out.append(code.upper())
        return out

    def model_name(self) -> str:
        """The model that reads resumes, pasted postings and writes cover letters."""
        return self.llm_model or get_settings().llm_model

    def scoring_model_name(self) -> str:
        """The model that assesses each shortlisted job."""
        return self.scoring_model or get_settings().scoring_model


def load(conn: sqlite3.Connection) -> AppSettings:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
    return AppSettings.model_validate(loads(row["value"], {})) if row else AppSettings()


def save(conn: sqlite3.Connection, settings: AppSettings) -> AppSettings:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (KEY, dumps(settings.model_dump()), now_iso()),
        )
    return settings


def get_value(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return loads(row["value"], default) if row else default


def set_value(conn: sqlite3.Connection, key: str, value) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, dumps(value), now_iso()),
        )
