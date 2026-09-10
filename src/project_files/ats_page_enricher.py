"""Generic extraction for ATS job pages that do not have a dedicated API client."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.project_files.models import JobListing


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, dict):
        if any(key in value for key in ("addressLocality", "addressRegion", "addressCountry")):
            parts = [value.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
            return ", ".join(str(part).strip() for part in parts if part)
        for key in ("name", "value", "text", "address", "addressLocality", "addressRegion", "addressCountry"):
            result = _text(value.get(key))
            if result:
                return result
    if isinstance(value, list):
        values = [_text(item) for item in value]
        values = [item for item in values if item]
        return ", ".join(values) if values else None
    return None


def _normalize_job_type(value: str | None) -> str | None:
    if not value:
        return None
    value = value.lower().replace("-", " ").replace("_", " ")
    if "intern" in value:
        return "internship"
    if "part" in value:
        return "part_time"
    if "contract" in value or "temporary" in value:
        return "contract"
    if "full" in value or "permanent" in value:
        return "full_time"
    return None


def _normalize_work_model(value: str | None) -> str | None:
    if not value:
        return None
    value = value.lower().replace("-", " ").replace("_", " ")
    if "hybrid" in value:
        return "hybrid"
    if "telecommute" in value or "remote" in value or "work from home" in value:
        return "remote"
    if "office" in value or "on site" in value or "onsite" in value or "in person" in value:
        return "in_person"
    return None


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _json_ld_documents(soup: BeautifulSoup) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        documents.extend(item for item in values if isinstance(item, dict))
    return documents


def _snippet_value(text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[.:]\s*([^.|]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _candidate_title(title: str, snippet: str) -> str:
    value = title or snippet or "Untitled role"
    return re.split(r"\s+(?:Location|Employment Type|Job Type|Location Type)\s*[.:]", value, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .")


def _company_from_title(title: str) -> str | None:
    match = re.search(r"\s+(?:at|@)\s+(.+?)(?:\s+[|·-]\s+|$)", title, re.IGNORECASE)
    return match.group(1).strip(" .") if match else None


async def enrich_ats_page(
    url: str,
    provider: str,
    search_title: str,
    snippet: str,
    query_used: str,
    client: httpx.AsyncClient,
) -> JobListing:
    """Fetch a generic ATS page and map JobPosting metadata into JobListing."""
    title = search_title or snippet or url
    company = _company_from_title(title) or "Unknown"
    location = _snippet_value(f"{title} {snippet}", ("Location",))
    job_type = _snippet_value(f"{title} {snippet}", ("Employment Type", "Job Type"))
    work_model = _normalize_work_model(_snippet_value(f"{title} {snippet}", ("Location Type",)) or location or f"{title} {snippet}")
    posted_at = None
    department = None

    try:
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        document = next((item for item in _json_ld_documents(soup) if item.get("@type") == "JobPosting"), {})
        title = _text(document.get("title")) or _text(soup.find("meta", attrs={"property": "og:title"}).get("content") if soup.find("meta", attrs={"property": "og:title"}) else None) or title
        organization = document.get("hiringOrganization")
        company = _text(organization) or _company_from_title(title) or company
        location = _text(document.get("jobLocation")) or location
        job_type = _normalize_job_type(_text(document.get("employmentType"))) or _normalize_job_type(job_type)
        work_model = _normalize_work_model(_text(document.get("jobLocationType")) or location or work_model)
        posted_at = _date(document.get("datePosted"))
        if posted_at is None:
            date_meta = soup.find("meta", attrs={"property": "datePosted"}) or soup.find("meta", attrs={"name": "datePosted"})
            posted_at = _date(date_meta.get("content") if date_meta else None)
        department = _text(document.get("occupationalCategory")) or _text(document.get("department"))
    except (httpx.HTTPError, ValueError):
        pass

    host_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return JobListing(
        id=f"{provider}:{host_id}",
        provider=provider,
        data_source="scrape" if posted_at or company != "Unknown" else "snippet",
        title=_candidate_title(title, snippet),
        company=company,
        location=location,
        is_remote=work_model == "remote" if work_model else None,
        employment_type=job_type,
        work_model=work_model,
        department=department,
        posted_at=posted_at,
        scraped_at=datetime.now(timezone.utc),
        apply_url=url,
        source_url=url,
        query_used=query_used,
        ats_source=provider,
    )
