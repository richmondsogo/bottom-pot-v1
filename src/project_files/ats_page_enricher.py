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
from src.project_files.http_headers import browser_headers
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
    match = re.search(r"(?:\s+(?:at|@)|^Careers at\s+)(.+?)(?:\s+[|·-]\s+|$)", title, re.IGNORECASE)
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
    resolved_apply_url = url

    try:
        response = await client.get(url, headers=browser_headers(url), timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        page_text = " ".join(soup.stripped_strings)
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

        # SAP and other server-rendered career pages expose labeled token rows without JSON-LD.
        page_fields = extract_labeled_fields(page_text)
        if "jobs.sap.com" in url:
            company = company if company != "Unknown" else "SAP"
            for token in soup.select(".joblayouttoken"):
                label_node = token.select_one(".joblayouttoken-label")
                if not label_node:
                    continue
                label = label_node.get_text(" ", strip=True).lower().rstrip(":")
                value = token.get_text(" ", strip=True)
                value = re.sub(rf"^{re.escape(label)}\s*:\s*", "", value, flags=re.IGNORECASE).strip()
                if label == "location":
                    page_fields["location"] = value
                elif label == "employment type":
                    page_fields["employment_type"] = value
                elif label == "posted date":
                    posted_at = parse_datetime(value)
                elif label in {"work area", "department"}:
                    page_fields["department"] = value
            if "office attendance" in page_text.lower():
                page_fields["work_model"] = "in_person"
        location = location or page_fields.get("location")
        job_type = job_type or normalize_job_type(page_fields.get("employment_type"))
        work_model = work_model or normalize_work_model(page_fields.get("work_model") or location)
        department = department or page_fields.get("department")
        structured_source_found = structured_source_found or bool(location or job_type or work_model or department)

        if "taleo.net" in url:
            for panel in soup.select(".contentlinepanel"):
                label = panel.select_one("h2, .subtitle")
                value = panel.select_one(".text")
                if not label or not value:
                    continue
                label_text = label.get_text(" ", strip=True).lower()
                value_text = value.get_text(" ", strip=True)
                if "location" in label_text and not location:
                    location = value_text
                elif "organization" in label_text and company == "Unknown":
                    company = value_text
            structured_source_found = structured_source_found or bool(location)

        if "applytojob.com/app/share" in url:
            title_node = soup.select_one(".focus-subheader h1, .focus-subheader-content h1, h1")
            title = title_node.get_text(" ", strip=True) if title_node else title
            share_link = soup.select_one("a[href*='/apply/']")
            if share_link and share_link.get("href"):
                resolved_apply_url = share_link.get("href")
            if title.lower().startswith("share job"):
                summary = soup.select_one(".focus-subheader-content-info, .focus-subheader")
                summary_text = summary.get_text(" ", strip=True) if summary else ""
                match = re.search(r"Share Job\s+(.+?)\s+(?:Remote|Hybrid|Full Time|Part Time|Contract|Internship)\b", summary_text, re.IGNORECASE)
                if match:
                    title = match.group(1).strip()
            attributes = [node.get_text(" ", strip=True) for node in soup.select("#focus-subheader-content-info li, .focus-subheader-content-info li")]
            job_type = job_type or normalize_job_type(next((item for item in attributes if normalize_job_type(item)), None))
            work_model = work_model or normalize_work_model(" ".join(attributes))
            structured_source_found = structured_source_found or bool(title_node or attributes)
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
        company=company or "Unknown",
        location=fields["location"],
        is_remote=fields["is_remote"],
        employment_type=fields["employment_type"],
        work_model=fields["work_model"],
        department=fields["department"],
        posted_at=posted_at,
        scraped_at=datetime.now(timezone.utc),
        apply_url=resolved_apply_url,
        source_url=url,
        query_used=query_used,
        ats_source=provider,
    )
