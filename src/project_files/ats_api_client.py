"""
ATS API clients — one class per platform.

All endpoints are public, unauthenticated GET requests.
The orchestrator owns the httpx.AsyncClient lifecycle and passes it in.

Return values:
  - None         → 404 dead listing (silently discard)
  - JobListing   → data_source="api" on success
  - JobListing   → data_source="snippet" on timeout/unexpected error (uses fallback_snippet)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger

from src.config import settings
from src.project_files.ats_url_parser import ParsedATSUrl
from src.project_files.exceptions import ParseError, SearchProviderError
from src.project_files.models import JobListing
from src.project_files.retry import with_retry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMEOUT = httpx.Timeout(settings.ats_request_timeout_seconds)


def _make_id(provider: str, company_slug: str, job_id: str) -> str:
    return f"{provider}:{company_slug}:{job_id}"


def _normalize_employment(raw: str | None) -> str | None:
    """Map freeform ATS strings to the canonical set."""
    if not raw:
        return None
    low = raw.lower().replace(" ", "_").replace("-", "_")
    if "full" in low:
        return "full_time"
    if "contract" in low or "contractor" in low:
        return "contract"
    if "part" in low:
        return "part_time"
    return None


def _fallback(
    parsed: ParsedATSUrl,
    fallback_snippet: str | None,
    query_used: str,
) -> JobListing:
    """Build a minimal snippet-based JobListing when the ATS API fails."""
    return JobListing(
        id=_make_id(parsed.ats, parsed.company_slug, parsed.job_id),
        provider=parsed.ats,
        data_source="snippet",
        title=fallback_snippet or parsed.raw_url,
        company=parsed.company_slug,
        company_slug=parsed.company_slug,
        scraped_at=datetime.now(timezone.utc),
        apply_url=parsed.raw_url,
        source_url=parsed.raw_url,
        query_used=query_used,
        ats_source=parsed.ats,
    )


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

class GreenhouseClient:
    """
    GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}
    Fields: title, location.name, updated_at, absolute_url, company_name
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/"
            f"{parsed.company_slug}/jobs/{parsed.job_id}"
        )
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[greenhouse] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[greenhouse] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            title = data.get("title", "")
            location = (data.get("location") or {}).get("name")
            apply_url = data.get("absolute_url") or parsed.raw_url
            company = data.get("company_name") or parsed.company_slug

            # updated_at is ISO8601 e.g. "2024-01-15T09:00:00.000Z"
            posted_at: datetime | None = None
            raw_date = data.get("updated_at")
            if raw_date:
                try:
                    posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return JobListing(
                id=_make_id("greenhouse", parsed.company_slug, parsed.job_id),
                provider="greenhouse",
                data_source="api",
                title=title,
                company=company,
                company_slug=parsed.company_slug,
                location=location,
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="greenhouse",
            )
        except Exception as exc:
            logger.warning(f"[greenhouse] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

class LeverClient:
    """
    GET https://api.lever.co/v0/postings/{slug}/{job_id}
    Fields: text, categories.location, categories.commitment, createdAt (ms), applyUrl
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = f"https://api.lever.co/v0/postings/{parsed.company_slug}/{parsed.job_id}"
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[lever] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[lever] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            categories = data.get("categories") or {}
            title = data.get("text", "")
            location = categories.get("location")
            commitment = categories.get("commitment")  # e.g. "Full-time"
            apply_url = data.get("applyUrl") or parsed.raw_url

            # createdAt is Unix milliseconds
            posted_at: datetime | None = None
            created_ms = data.get("createdAt")
            if created_ms:
                try:
                    posted_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
                except (ValueError, OSError):
                    pass

            return JobListing(
                id=_make_id("lever", parsed.company_slug, parsed.job_id),
                provider="lever",
                data_source="api",
                title=title,
                company=parsed.company_slug,
                company_slug=parsed.company_slug,
                location=location,
                employment_type=_normalize_employment(commitment),
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="lever",
            )
        except Exception as exc:
            logger.warning(f"[lever] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

class AshbyClient:
    """
    GET https://api.ashbyhq.com/posting-api/job-posting/{job_id}
    Fields: title, locationName, employmentType, publishedAt, jobUrl
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = f"https://api.ashbyhq.com/posting-api/job-posting/{parsed.job_id}"
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[ashby] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[ashby] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            title = data.get("title", "")
            location = data.get("locationName")
            apply_url = data.get("jobUrl") or parsed.raw_url
            employment_raw = data.get("employmentType")  # e.g. "FullTime"

            posted_at: datetime | None = None
            raw_date = data.get("publishedAt")
            if raw_date:
                try:
                    posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Ashby uses company slug from the URL
            company = parsed.company_slug

            return JobListing(
                id=_make_id("ashby", parsed.company_slug, parsed.job_id),
                provider="ashby",
                data_source="api",
                title=title,
                company=company,
                company_slug=parsed.company_slug,
                location=location,
                employment_type=_normalize_employment(employment_raw),
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="ashby",
            )
        except Exception as exc:
            logger.warning(f"[ashby] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------

class SmartRecruitersClient:
    """
    GET https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}
    Fields: name, location.city, location.remote, releasedDate, ref
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/"
            f"{parsed.company_slug}/postings/{parsed.job_id}"
        )
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[smartrecruiters] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[smartrecruiters] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            title = data.get("name", "")
            loc_data = data.get("location") or {}
            location = loc_data.get("city")
            is_remote = loc_data.get("remote")  # bool or None
            apply_url = data.get("ref") or parsed.raw_url

            posted_at: datetime | None = None
            raw_date = data.get("releasedDate")
            if raw_date:
                try:
                    posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return JobListing(
                id=_make_id("smartrecruiters", parsed.company_slug, parsed.job_id),
                provider="smartrecruiters",
                data_source="api",
                title=title,
                company=parsed.company_slug,
                company_slug=parsed.company_slug,
                location=location,
                is_remote=is_remote if isinstance(is_remote, bool) else None,
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="smartrecruiters",
            )
        except Exception as exc:
            logger.warning(f"[smartrecruiters] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------

class WorkableClient:
    """
    GET https://{slug}.workable.com/j/{job_id}.json
    Fields: title, location.location_str, remote, created_at, url
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = f"https://{parsed.company_slug}.workable.com/j/{parsed.job_id}.json"
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[workable] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[workable] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            title = data.get("title", "")
            loc_data = data.get("location") or {}
            location = loc_data.get("location_str") or loc_data.get("city")
            is_remote = data.get("remote")
            apply_url = data.get("url") or parsed.raw_url

            posted_at: datetime | None = None
            raw_date = data.get("created_at")
            if raw_date:
                try:
                    posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return JobListing(
                id=_make_id("workable", parsed.company_slug, parsed.job_id),
                provider="workable",
                data_source="api",
                title=title,
                company=parsed.company_slug,
                company_slug=parsed.company_slug,
                location=location,
                is_remote=is_remote if isinstance(is_remote, bool) else None,
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="workable",
            )
        except Exception as exc:
            logger.warning(f"[workable] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# BambooHR
# ---------------------------------------------------------------------------

class BambooHRClient:
    """
    GET https://{slug}.bamboohr.com/careers/list
    Returns JSON array of all open roles. Filter by id field to find the target job.
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = f"https://{parsed.company_slug}.bamboohr.com/careers/list"
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[bamboohr] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[bamboohr] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            # data is typically {"result": [...jobs...]} or a list directly
            jobs: list[dict] = []
            if isinstance(data, list):
                jobs = data
            elif isinstance(data, dict):
                # Some slugs return {"result": [...]}
                jobs = data.get("result", []) or data.get("jobs", [])

            # Find the matching job by ID
            target = str(parsed.job_id)
            matched: dict | None = None
            for job in jobs:
                if str(job.get("id", "")) == target:
                    matched = job
                    break

            if matched is None:
                # Job not found in current listings → treat as 404
                return None

            title = matched.get("title", "") or matched.get("jobTitle", "")
            location = matched.get("location", {}).get("city") if isinstance(matched.get("location"), dict) else matched.get("location")
            apply_url = (
                f"https://{parsed.company_slug}.bamboohr.com/careers/{parsed.job_id}"
            )

            return JobListing(
                id=_make_id("bamboohr", parsed.company_slug, parsed.job_id),
                provider="bamboohr",
                data_source="api",
                title=title,
                company=parsed.company_slug,
                company_slug=parsed.company_slug,
                location=location,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="bamboohr",
            )
        except Exception as exc:
            logger.warning(f"[bamboohr] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# Recruitee
# ---------------------------------------------------------------------------

class RecruiteeClient:
    """
    GET https://api.recruitee.com/c/{slug}/offers/{job_id}
    Fields: title, location, remote, created_at, careers_url
    """

    @with_retry(max_attempts=3, base_delay=1.0)
    async def _do_fetch(self, url: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def fetch(
        self,
        parsed: ParsedATSUrl,
        client: httpx.AsyncClient,
        fallback_snippet: str | None = None,
        query_used: str = "",
    ) -> JobListing | None:
        url = f"https://api.recruitee.com/c/{parsed.company_slug}/offers/{parsed.job_id}"
        try:
            data = await self._do_fetch(url, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            logger.warning(f"[recruitee] API error {exc.response.status_code} for {url}")
            return _fallback(parsed, fallback_snippet, query_used)
        except Exception as exc:
            logger.warning(f"[recruitee] Unexpected error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)

        try:
            # Recruitee wraps the offer under an "offer" key
            offer = data.get("offer") or data
            title = offer.get("title", "") or offer.get("position", "")
            location = offer.get("location") or offer.get("city")
            is_remote = offer.get("remote")
            apply_url = offer.get("careers_url") or parsed.raw_url

            posted_at: datetime | None = None
            raw_date = offer.get("created_at")
            if raw_date:
                try:
                    posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return JobListing(
                id=_make_id("recruitee", parsed.company_slug, parsed.job_id),
                provider="recruitee",
                data_source="api",
                title=title,
                company=parsed.company_slug,
                company_slug=parsed.company_slug,
                location=location,
                is_remote=is_remote if isinstance(is_remote, bool) else None,
                posted_at=posted_at,
                scraped_at=datetime.now(timezone.utc),
                apply_url=apply_url,
                source_url=parsed.raw_url,
                query_used=query_used,
                ats_source="recruitee",
            )
        except Exception as exc:
            logger.warning(f"[recruitee] Parse error for {url}: {exc}")
            return _fallback(parsed, fallback_snippet, query_used)


# ---------------------------------------------------------------------------
# Registry — maps ats name → client instance
# ---------------------------------------------------------------------------

ATS_CLIENTS: dict[str, object] = {
    "greenhouse": GreenhouseClient(),
    "lever": LeverClient(),
    "ashby": AshbyClient(),
    "smartrecruiters": SmartRecruitersClient(),
    "workable": WorkableClient(),
    "bamboohr": BambooHRClient(),
    "recruitee": RecruiteeClient(),
}
