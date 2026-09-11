"""Generic extraction for ATS job pages that do not have a dedicated API client."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.project_files.models import JobListing
from src.project_files.http_headers import browser_headers
from src.project_files.field_normalizer import (
    clean_title,
    extract_labeled_fields,
    normalize_fields,
    normalize_job_type,
    normalize_job_type_from_text,
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


def _clean_html_text(value: Any) -> str | None:
    """Decode HTML entities and strip tags from a description body."""
    if value is None:
        return None
    cleaned = html.unescape(str(value))
    if "<" in cleaned:
        try:
            cleaned = BeautifulSoup(cleaned, "lxml").get_text(" ", strip=True)
        except Exception:
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or None


def _meta_content(soup: BeautifulSoup, attr: str, name: str) -> str | None:
    node = soup.find("meta", attrs={attr: name})
    if node is None:
        return None
    content = node.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _jazzhr_share_attributes(soup: BeautifulSoup) -> dict[str, str | None]:
    """Read the labelled attribute rows JazzHR renders on its share pages."""
    result: dict[str, str | None] = {"location": None, "job_type": None, "experience": None}
    for node in soup.select("#focus-subheader-content-info li, .focus-subheader-content-info li"):
        text = node.get_text(" ", strip=True)
        icon = node.select_one("i, span.fa, .fa")
        icon_classes = " ".join(icon.get("class", [])) if icon else ""
        if "map-marker" in icon_classes:
            result["location"] = text or None
        elif "clock" in icon_classes:
            result["job_type"] = text or None
        elif "graduation" in icon_classes:
            result["experience"] = text or None
    return result


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
    description: str | None = None
    page_fields: dict[str, str] = {}

    try:
        response = await client.get(url, headers=browser_headers(url), timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        page_text = " ".join(soup.stripped_strings)
        document = next((item for item in _json_ld_documents(soup) if item.get("@type") == "JobPosting"), {})
        structured_source_found = bool(document)
        title = _text(document.get("title")) or _meta_content(soup, "property", "og:title") or title
        organization = document.get("hiringOrganization")
        company = _text(organization) or _company_from_title(title) or company
        location = _text(document.get("jobLocation")) or location
        job_type = normalize_job_type(_text(document.get("employmentType"))) or normalize_job_type(job_type)
        description = _clean_html_text(_text(document.get("description"))) or description
        work_model = normalize_work_model(
            _text(document.get("jobLocationType")),
            location=location,
            title=title,
            description=description,
            snippet=snippet,
        ) or work_model
        posted_at = parse_datetime(document.get("datePosted"))
        if posted_at is None:
            date_meta = soup.find("meta", attrs={"property": "datePosted"}) or soup.find("meta", attrs={"name": "datePosted"})
            posted_at = parse_datetime(date_meta.get("content") if date_meta else None)
            structured_source_found = structured_source_found or posted_at is not None
        department = _text(document.get("occupationalCategory")) or _text(document.get("department"))

        # SAP SuccessFactors career pages expose labeled token rows plus a full
        # description; the work model is carried by a dedicated label or lives
        # in the title/description text (e.g. "#LI-Hybrid", "hybrid role").
        if "jobs.sap.com" in url:
            company = company if company != "Unknown" else "SAP"
            for token in soup.select(".joblayouttoken"):
                label_node = token.select_one(".joblayouttoken-label")
                if not label_node:
                    continue
                label = label_node.get_text(" ", strip=True).lower().rstrip(":")
                value = token.get_text(" ", strip=True)
                value = re.sub(rf"^{re.escape(label)}\s*:\s*", "", value, flags=re.IGNORECASE).strip()
                if not value:
                    continue
                if label == "location":
                    page_fields["location"] = value
                elif label == "employment type":
                    page_fields["employment_type"] = value
                elif label == "posted date":
                    posted_at = parse_datetime(value)
                elif label == "office attendance":
                    page_fields["work_model"] = value
                elif label in {"work area", "department"}:
                    page_fields["department"] = value
            sap_description = soup.select_one('[data-careersite-propertyid="description"], [itemprop="description"]')
            if sap_description:
                description = sap_description.get_text(" ", strip=True)
        else:
            page_fields.update(extract_labeled_fields(page_text))

        location = location or page_fields.get("location")
        job_type = job_type or normalize_job_type(page_fields.get("employment_type"))
        work_model = work_model or normalize_work_model(
            page_fields.get("work_model"),
            location=location,
            title=title,
            description=description,
            snippet=snippet,
        )
        department = department or page_fields.get("department")
        if job_type is None:
            type_scan_text = " ".join(
                part for part in (title, snippet, page_fields.get("employment_type", ""), description or "", location or "") if part
            )
            job_type = normalize_job_type_from_text(type_scan_text)
        structured_source_found = structured_source_found or bool(location or job_type or work_model or department or posted_at)

        if "taleo.net" in url:
            for panel in soup.select(".contentlinepanel"):
                label = panel.select_one("h2, .subtitle, .title")
                if not label:
                    continue
                label_text = label.get_text(" ", strip=True).lower()
                value = panel.select_one(".text")
                value_text = value.get_text(" ", strip=True) if value else ""
                if not value_text or value_text.lower() == label_text:
                    continue
                if "location" in label_text and not location:
                    location = value_text
                elif "organization" in label_text and company == "Unknown":
                    company = value_text
                elif ("job type" in label_text or "employment" in label_text) and not page_fields.get("employment_type"):
                    page_fields["employment_type"] = value_text
                elif "posting date" in label_text or "posted date" in label_text:
                    posted_at = posted_at or parse_datetime(value_text)
            if description is None and page_text:
                description = page_text[:6000]

        # Personio job pages render a Next.js app but embed a JSON blob exposing
        # the office/location, schedule (employment type) and department.
        if "jobs.personio.com" in url:
            raw_html = response.text
            office_match = re.search(r'"main_office"\s*:\s*"([^"]+)"', raw_html)
            schedule_match = re.search(r'"schedule"\s*:\s*"([^"]+)"', raw_html)
            employment_like = re.search(r'"employment_type"\s*:\s*"([^"]+)"', raw_html)
            department_match = re.search(r'"department"\s*:\s*"([^"]+)"', raw_html)
            subcompany_match = re.search(r'"subcompany"\s*:\s*"([^"]+)"', raw_html)
            location = location or (office_match.group(1) if office_match else None)
            if not page_fields.get("employment_type"):
                matched_type = (employment_like or schedule_match)
                if matched_type:
                    page_fields["employment_type"] = matched_type.group(1)
            department = department or (department_match.group(1) if department_match else None)
            if company == "Unknown":
                if subcompany_match:
                    company = subcompany_match.group(1)
                else:
                    og_title = _meta_content(soup, "property", "og:title")
                    if og_title:
                        org_match = re.search(r"\s*\|\s*Jobs? at Work for\s+(.+)$", og_title, re.IGNORECASE)
                        if org_match:
                            company = org_match.group(1).strip()
            job_type = job_type or normalize_job_type(page_fields.get("employment_type"))
            work_model = work_model or normalize_work_model(
                None,
                location=location,
                title=title,
                description=description,
                snippet=snippet,
            )
            structured_source_found = structured_source_found or bool(location or job_type or work_model or department)

        # JazzHR: the /app/share/ page points at the real /apply/ page, which
        # publishes a full JSON-LD JobPosting (company, location, employment
        # type, posted date, work model).
        if "applytojob.com/app/share" in url:
            title_node = soup.select_one(".focus-subheader-content h1 a, .focus-subheader h1, h1")
            if title_node:
                title = title_node.get_text(" ", strip=True) or title
            share_link = soup.select_one("a[href*='/apply/']")
            if share_link and share_link.get("href"):
                resolved_apply_url = urljoin(url, share_link.get("href"))
            share_attrs = _jazzhr_share_attributes(soup)
            location = location or share_attrs.get("location")
            job_type = job_type or normalize_job_type(share_attrs.get("job_type"))
            work_model = work_model or normalize_work_model(
                None,
                location=location or share_attrs.get("location"),
                title=title,
            )
            structured_source_found = structured_source_found or bool(title_node or any(share_attrs.values()))
            if company == "Unknown":
                og_title = _meta_content(soup, "property", "og:title")
                if og_title:
                    org_match = re.search(r"\s-\s(.+?)\s+-\s+Career\s+Page\s*$", og_title, re.IGNORECASE)
                    if org_match:
                        company = org_match.group(1).strip()
            if resolved_apply_url and resolved_apply_url != url:
                try:
                    apply_response = await client.get(
                        resolved_apply_url,
                        headers=browser_headers(resolved_apply_url),
                        timeout=12.0,
                        follow_redirects=True,
                    )
                    apply_response.raise_for_status()
                    apply_soup = BeautifulSoup(apply_response.text, "lxml")
                    apply_doc = next((item for item in _json_ld_documents(apply_soup) if item.get("@type") == "JobPosting"), {})
                    if apply_doc:
                        structured_source_found = True
                        description = _clean_html_text(_text(apply_doc.get("description"))) or description
                        title = _text(apply_doc.get("title")) or title
                        org = _text(apply_doc.get("hiringOrganization"))
                        if org:
                            company = org if company == "Unknown" else company
                        apply_location = _text(apply_doc.get("jobLocation"))
                        location = apply_location or location
                        job_type = job_type or normalize_job_type(_text(apply_doc.get("employmentType")))
                        posted_at = posted_at or parse_datetime(apply_doc.get("datePosted"))
                        work_model = normalize_work_model(
                            _text(apply_doc.get("jobLocationType")),
                            location=location,
                            title=title,
                            description=description,
                            snippet=snippet,
                        ) or work_model
                except (httpx.HTTPError, ValueError):
                    pass
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
