"""Shared normalization for job fields from ATS and scraper sources."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

LABELS = ("Location", "Employment Type", "Job Type", "Location Type", "Department")


def humanize_slug(value: str | None) -> str | None:
    """Turn an ATS slug into a readable fallback company name."""
    if not value:
        return None
    words = re.sub(r"[-_]+", " ", value).split()
    if not words:
        return None
    return " ".join(word.title() for word in words)


def normalize_job_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).lower().replace("-", " ").replace("_", " ")
    if "intern" in text:
        return "internship"
    if "part" in text:
        return "part_time"
    if "contract" in text or "temporary" in text:
        return "contract"
    if "full" in text or "permanent" in text:
        return "full_time"
    return None


def normalize_work_model(value: Any, is_remote: bool | None = None) -> str | None:
    if is_remote is True:
        return "remote"
    if is_remote is False:
        return "in_person"
    if value is None:
        return None
    text = str(value).lower().replace("-", " ").replace("_", " ")
    if "hybrid" in text:
        return "hybrid"
    if "telecommute" in text or "remote" in text or "work from home" in text:
        return "remote"
    if "office" in text or "on site" in text or "onsite" in text or "in person" in text:
        return "in_person"
    return None


def extract_labeled_fields(text: str | None) -> dict[str, str]:
    """Extract explicit metadata labels from a title/snippet without guessing."""
    if not text:
        return {}
    pattern = re.compile(
        rf"(?P<label>{'|'.join(re.escape(label) for label in LABELS)})\s*[.:]\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    fields: dict[str, str] = {}
    key_map = {
        "location": "location",
        "employment type": "employment_type",
        "job type": "employment_type",
        "location type": "work_model",
        "department": "department",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = re.sub(r"\.{3,}$", "", text[match.end():end])
        value = re.sub(r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}$", "", value, flags=re.IGNORECASE)
        value = value.strip(" .|-")
        if value:
            fields[key_map[match.group("label").lower()]] = value
    return fields


def clean_title(title: str | None, snippet: str | None = None) -> str:
    """Remove explicit metadata suffixes from a search title."""
    value = (title or snippet or "Untitled role").strip()
    match = re.search(
        r"\s+(?:Location|Employment Type|Job Type|Location Type|Department)\s*[.:]",
        value,
        re.IGNORECASE,
    )
    return value[:match.start()].strip(" .") if match else value


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_fields(
    *,
    title: str | None,
    snippet: str | None = None,
    location: Any = None,
    employment_type: Any = None,
    work_model: Any = None,
    is_remote: bool | None = None,
    department: Any = None,
) -> dict[str, Any]:
    """Apply shared field cleanup to structured or unstructured source values."""
    labeled = extract_labeled_fields(" ".join(part for part in (title, snippet) if part))
    resolved_location = location or labeled.get("location")
    resolved_type = normalize_job_type(employment_type or labeled.get("employment_type"))
    resolved_model = normalize_work_model(work_model or labeled.get("work_model") or resolved_location, is_remote)
    resolved_remote = is_remote if is_remote is not None else resolved_model == "remote" if resolved_model else None
    return {
        "title": clean_title(title, snippet),
        "location": str(resolved_location).strip() if resolved_location else None,
        "employment_type": resolved_type,
        "work_model": resolved_model,
        "is_remote": resolved_remote,
        "department": str(department).strip() if department else labeled.get("department"),
    }
