"""Generic extraction for ATS job pages that do not have a dedicated API client."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.project_files.models import JobListing
from src.project_files.field_normalizer import (
    clean_title,
    extract_labeled_fields,
    normalize_fields,
    normalize_job_type,
    normalize_work_model,
    parse_datetime,
)


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


def _json_ld_documents(soup: BeautifulSoup) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for item in values:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                documents.extend(node for node in graph if isinstance(node, dict))
            else:
                documents.append(item)
    return documents


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
    labeled = extract_labeled_fields(f"{title} {snippet}")
    location = labeled.get("location")
    job_type = labeled.get("employment_type")
    work_model = labeled.get("work_model")
    posted_at = None
    department = None
    structured_source_found = False

    try:
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        document = next((item for item in _json_ld_documents(soup) if item.get("@type") == "JobPosting"), {})
        structured_source_found = bool(document)
        title = _text(document.get("title")) or _text(soup.find("meta", attrs={"property": "og:title"}).get("content") if soup.find("meta", attrs={"property": "og:title"}) else None) or title
        organization = document.get("hiringOrganization")
        company = _text(organization) or _company_from_title(title) or company
        location = _text(document.get("jobLocation")) or location
        job_type = normalize_job_type(_text(document.get("employmentType"))) or normalize_job_type(job_type)
        work_model = normalize_work_model(_text(document.get("jobLocationType")) or location or work_model)
        posted_at = parse_datetime(document.get("datePosted"))
        if posted_at is None:
            date_meta = soup.find("meta", attrs={"property": "datePosted"}) or soup.find("meta", attrs={"name": "datePosted"})
            posted_at = parse_datetime(date_meta.get("content") if date_meta else None)
            structured_source_found = structured_source_found or posted_at is not None
        department = _text(document.get("occupationalCategory")) or _text(document.get("department"))
    except (httpx.HTTPError, ValueError):
        pass

    host_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    fields = normalize_fields(
        title=title,
        snippet=snippet,
        location=location,
        employment_type=job_type,
        work_model=work_model,
        department=department,
    )
    has_structured_data = structured_source_found
    return JobListing(
        id=f"{provider}:{host_id}",
        provider=provider,
        data_source="scrape" if has_structured_data else "snippet",
        title=fields["title"] or clean_title(title, snippet),
        company=company,
        location=fields["location"],
        is_remote=fields["is_remote"],
        employment_type=fields["employment_type"],
        work_model=fields["work_model"],
        department=fields["department"],
        posted_at=posted_at,
        scraped_at=datetime.now(timezone.utc),
        apply_url=url,
        source_url=url,
        query_used=query_used,
        ats_source=provider,
    )
