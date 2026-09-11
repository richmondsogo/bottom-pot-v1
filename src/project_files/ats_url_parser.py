"""
ATS URL parser — takes a raw URL from Serper and returns a structured object
with the company slug and job ID needed to call the ATS API directly.

Returns None for anything that is not a real job page URL:
  - Blog posts
  - Company homepages
  - Search result pages
  - Partial path matches

Never raises. All errors are swallowed and return None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class ParsedATSUrl:
    ats: str            # e.g. "greenhouse", "lever", "ashby"
    company_slug: str   # e.g. "stripe", "openai"
    job_id: str         # e.g. "4567890" or a UUID
    raw_url: str        # original URL, kept for debugging


# ---------------------------------------------------------------------------
# Compiled regex patterns (one per URL variant)
# ---------------------------------------------------------------------------

# Greenhouse — two host variants:
#   https://boards.greenhouse.io/{slug}/jobs/{numeric_id}
#   https://job-boards.greenhouse.io/{slug}/jobs/{numeric_id}
_GH_BOARDS = re.compile(
    r"^https?://boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)/?$",
    re.IGNORECASE,
)
_GH_JOB_BOARDS = re.compile(
    r"^https?://job-boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)/?$",
    re.IGNORECASE,
)

# Lever:
#   https://jobs.lever.co/{slug}/{uuid}
_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_LEVER = re.compile(
    rf"^https?://jobs\.lever\.co/([^/?#]+)/({_UUID_RE})/?$",
    re.IGNORECASE,
)

# Ashby:
#   https://jobs.ashbyhq.com/{slug}/{uuid}
_ASHBY = re.compile(
    rf"^https?://jobs\.ashby(?:hq)?\.com/([^/?#]+)/({_UUID_RE})/?$",
    re.IGNORECASE,
)

# SmartRecruiters:
#   https://jobs.smartrecruiters.com/{CompanyName}/{job_id}
#   job_id is a long numeric string (not UUID)
_SMARTREC = re.compile(
    r"^https?://jobs\.smartrecruiters\.com/([^/?#]+)/(\d+)(?:-[^/?#]+)?/?$",
    re.IGNORECASE,
)

# Workable — two variants:
#   https://{slug}.workable.com/jobs/{job_id}
#   https://apply.workable.com/{slug}/j/{job_id}
_WORKABLE_SUBDOMAIN = re.compile(
    r"^https?://([^./?#]+)\.workable\.com/jobs/([^/?#]+)/?$",
    re.IGNORECASE,
)
_WORKABLE_APPLY = re.compile(
    r"^https?://apply\.workable\.com/([^/?#]+)/j/([^/?#]+)/?$",
    re.IGNORECASE,
)

# BambooHR:
#   https://{slug}.bamboohr.com/careers/{job_id}
#   job_id may be numeric or alphanumeric
_BAMBOOHR = re.compile(
    r"^https?://([^./?#]+)\.bamboohr\.com/careers/(\w+)/?$",
    re.IGNORECASE,
)

# Recruitee:
#   https://{slug}.recruitee.com/o/{job_id}-{anything}
#   The job_id is numeric; the slug after the hyphen is the human-readable title
_RECRUITEE = re.compile(
    r"^https?://([^./?#]+)\.recruitee\.com/o/(\d+)-[^/?#]+/?$",
    re.IGNORECASE,
)

_JOBVITE = re.compile(r"^https?://jobs\.jobvite\.com/([^/?#]+)/job/([^/?#]+)/?$", re.IGNORECASE)
_TEAMTAILOR = re.compile(r"^https?://([^./?#]+)\.teamtailor\.com/jobs/(\d+)-[^/?#]+/?$", re.IGNORECASE)
_PERSONIO = re.compile(r"^https?://jobs\.personio\.(?:com|de)/job/([^/?#]+?)(?:-(\d+))?/?$", re.IGNORECASE)
_ICIMS = re.compile(r"^https?://jobs\.icims\.com/jobs/(\d+)/[^/?#]+/?$", re.IGNORECASE)
_BREEZY = re.compile(r"^https?://apply\.breezy\.hr/p/([^/?#]+)/[^/?#]+/?$", re.IGNORECASE)
_JAZZHR = re.compile(r"^https?://applytojob\.com/apply/([^/?#]+)/?$", re.IGNORECASE)
_JAZZHR_SHARE = re.compile(r"^https?://([^./?#]+)\.applytojob\.com/app/share/([^/?#]+)/?$", re.IGNORECASE)
_JOBADDER = re.compile(r"^https?://apply\.jobadder\.com/[^/?#]+/[^/?#]+/([^/?#]+)/?$", re.IGNORECASE)
_TALEO = re.compile(r"^https?://[^/?#]+\.taleo\.net/careersection/[^/?#]+/jobdetail\.ftl\?job=(\d+).*$", re.IGNORECASE)
_AVATURE = re.compile(r"^https?://[^/?#]+\.avature\.net/[^/?#]+/job/(\d+)/[^/?#]+/?$", re.IGNORECASE)
_WORKDAY = re.compile(r"^https?://[^/?#]+\.myworkdayjobs\.com/[^?#]+/job/[^/?#]+/([^/?#]+)/?$", re.IGNORECASE)
_SUCCESSFACTORS = re.compile(r"^https?://jobs\.sap\.com/job/([^/?#]+)/[^/?#]+/?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ats_url(url: str) -> ParsedATSUrl | None:
    """
    Parse a raw Serper URL into a structured ATS reference.

    Returns None if the URL does not cleanly match any known ATS job-page pattern.
    Never raises.
    """
    if not url:
        return None

    try:
        # Strip query strings and fragments before matching — we want clean paths
        parsed = urlparse(url)
        # Reconstruct without query/fragment for cleaner matching
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # ── Greenhouse ────────────────────────────────────────────────────────
        m = _GH_BOARDS.match(clean_url)
        if m:
            return ParsedATSUrl(ats="greenhouse", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _GH_JOB_BOARDS.match(clean_url)
        if m:
            return ParsedATSUrl(ats="greenhouse", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── Lever ─────────────────────────────────────────────────────────────
        m = _LEVER.match(clean_url)
        if m:
            return ParsedATSUrl(ats="lever", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── Ashby ─────────────────────────────────────────────────────────────
        m = _ASHBY.match(clean_url)
        if m:
            return ParsedATSUrl(ats="ashby", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── SmartRecruiters ───────────────────────────────────────────────────
        m = _SMARTREC.match(clean_url)
        if m:
            return ParsedATSUrl(ats="smartrecruiters", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── Workable ──────────────────────────────────────────────────────────
        m = _WORKABLE_SUBDOMAIN.match(clean_url)
        if m:
            return ParsedATSUrl(ats="workable", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _WORKABLE_APPLY.match(clean_url)
        if m:
            return ParsedATSUrl(ats="workable", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── BambooHR ──────────────────────────────────────────────────────────
        m = _BAMBOOHR.match(clean_url)
        if m:
            return ParsedATSUrl(ats="bamboohr", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        # ── Recruitee ─────────────────────────────────────────────────────────
        m = _RECRUITEE.match(clean_url)
        if m:
            return ParsedATSUrl(ats="recruitee", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _JOBVITE.match(clean_url)
        if m:
            return ParsedATSUrl(ats="jobvite", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _TEAMTAILOR.match(clean_url)
        if m:
            return ParsedATSUrl(ats="teamtailor", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _PERSONIO.match(clean_url)
        if m:
            return ParsedATSUrl(ats="personio", company_slug="personio", job_id=m.group(2) or m.group(1), raw_url=url)

        m = _ICIMS.match(clean_url)
        if m:
            return ParsedATSUrl(ats="icims", company_slug="icims", job_id=m.group(1), raw_url=url)

        m = _BREEZY.match(clean_url)
        if m:
            return ParsedATSUrl(ats="breezy", company_slug="breezy", job_id=m.group(1), raw_url=url)

        m = _JAZZHR.match(clean_url)
        if m:
            return ParsedATSUrl(ats="jazzhr", company_slug="jazzhr", job_id=m.group(1), raw_url=url)

        m = _JAZZHR_SHARE.match(clean_url)
        if m:
            return ParsedATSUrl(ats="jazzhr", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _JOBADDER.match(clean_url)
        if m:
            return ParsedATSUrl(ats="jobadder", company_slug="jobadder", job_id=m.group(1), raw_url=url)

        m = _TALEO.match(url)
        if m:
            return ParsedATSUrl(ats="taleo", company_slug=parsed.netloc, job_id=m.group(1), raw_url=url)

        m = _AVATURE.match(clean_url)
        if m:
            return ParsedATSUrl(ats="avature", company_slug=m.group(1), job_id=m.group(2), raw_url=url)

        m = _WORKDAY.match(clean_url)
        if m:
            return ParsedATSUrl(ats="workday", company_slug=parsed.netloc, job_id=m.group(1), raw_url=url)

        m = _SUCCESSFACTORS.match(clean_url)
        if m:
            return ParsedATSUrl(ats="successfactors", company_slug="sap", job_id=m.group(1), raw_url=url)

    except Exception:
        # Malformed URL — return None silently
        return None

    return None
