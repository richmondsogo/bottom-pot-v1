from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, computed_field

# ---------------------------------------------------------------------------
# Existing models — DO NOT MODIFY FIELD NAMES (CLI depends on these)
# ---------------------------------------------------------------------------


class SearchParams(BaseModel):
    """
    I created this class to hold all the parameters for a job search. You can think of it as a blueprint
    for what the user wants to search for. I use Pydantic so that I can validate the inputs easily.
    For example, job_title is required, but location is optional. I designed it this way because
    not every search needs a location, but every search needs a job title.
    """

    job_title: str  # This is the main thing we're searching for, like "Data Engineer"
    location: Optional[str] = None  # If you want to add a city or region, put it here. not here literally but use that data field.
    salary_min: Optional[int] = None  # Minimum salary in dollars, I add this to the query if provided. cant be working minimum wage lol.
    experience_level: Optional[str] = None  # Like "senior" or "entry", I map this to text
    exclude_keywords: Optional[list[str]] = []  # Words you don't want in results, I exclude them
    max_results: int = 100  # I cap the results at this number to avoid too much data
    remote: Optional[bool] = None  # True for remote only, False to exclude remote, None for both
    days_back: Optional[int] = 7  # How many days back to search, I use this for date filtering
    country_code: Optional[str] = None  # For Google geolocation, like "us" for US results
    # ── New fields (added for API layer — backward compat: have defaults) ─
    include_nigerian_sites: bool = True


class ATSConfig(BaseModel):
    """
    I defined this to represent each ATS platform. Each platform has a name, site operator for Google site: search,
    and a human-readable label. I use this to configure which platforms to search.
    """

    name: str  # Short name like "greenhouse"
    site_operator: str  # The domain part, like "greenhouse.io"
    label: str  # Friendly name, like "Greenhouse"


class RawSearchResults(BaseModel):
    """
    This is what I store for each search result. I included the URL, title, snippet, which ATS it came from,
    the query that found it, and when I scraped it. I use this to track everything.
    """

    url: str  # The job posting URL
    title: str  # The job title from the search result
    snippet: Optional[str]  # A preview text from Google
    ats_source: str  # Which platform, like "greenhouse"
    query_used: str  # The exact Google query I used
    scraped_at: datetime = datetime.now(timezone.utc)  # Timestamp when I got this result


# ---------------------------------------------------------------------------
# New models — added for the FastAPI layer
# ---------------------------------------------------------------------------


class JobListing(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────
    id: str
    # ATS jobs: "{provider}:{company_slug}:{job_id}"
    # Scraped jobs: "sha256(apply_url)[:16]"

    # ── Provider metadata ─────────────────────────────────────────────
    provider: str
    # One of: "greenhouse" | "lever" | "ashby" | "smartrecruiters"
    # "workable" | "bamboohr" | "recruitee"
    # "jobberman" | "myjobmag" | "ngcareers" | "hotnigerianJobs"

    data_source: Literal["api", "scrape", "snippet"]
    # "api"     → fetched from ATS JSON API (most complete)
    # "scrape"  → extracted from HTML (Nigerian sites)
    # "snippet" → fallback: Serper snippet only (least complete)

    # ── Job data ──────────────────────────────────────────────────────
    title: str
    company: str
    company_slug: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    employment_type: str | None = None
    # "full_time" | "contract" | "part_time" | None

    # ── Dates ─────────────────────────────────────────────────────────
    posted_at: datetime | None = None
    scraped_at: datetime

    # ── Links ─────────────────────────────────────────────────────────
    apply_url: str
    source_url: str  # original Serper URL — keep for debugging

    # ── Search context ────────────────────────────────────────────────
    query_used: str
    ats_source: str  # backward compat alias for provider

    # ── Computed ──────────────────────────────────────────────────────
    @computed_field
    @property
    def freshness_label(self) -> str:
        if not self.posted_at:
            return "Recently posted"
        days = (datetime.utcnow() - self.posted_at.replace(tzinfo=None)).days
        if days == 0:
            return "Today"
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 14:
            return "1 week ago"
        if days < 21:
            return "2 weeks ago"
        if days < 28:
            return "3 weeks ago"
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"


class SearchResponse(BaseModel):
    query: str
    total: int
    search_time_ms: int
    results: list[JobListing]
    providers_searched: list[str]
    providers_skipped: list[str]
    serper_queries_used: int
    cached: bool


class SubscribeRequest(BaseModel):
    email: EmailStr
    search_query: str | None = None


# ── SSE event payloads ────────────────────────────────────────────────


class ResultsBatch(BaseModel):
    batch: list[JobListing]
    total_so_far: int


class DoneEvent(BaseModel):
    total: int
    search_time_ms: int
    serper_queries_used: int
    providers_searched: list[str]
    providers_skipped: list[str]
    cached: bool


class ErrorEvent(BaseModel):
    message: str
    code: str
