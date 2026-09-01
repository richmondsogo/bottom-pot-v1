from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from src.project_files.models import ATSConfig, SearchParams

GOOGLE_BASE_URL = "https://www.google.com/search"

# ---------------------------------------------------------------------------
# ATS Domain Registry for Step 7 API Query Building
# ---------------------------------------------------------------------------
ATS_DOMAINS: dict[str, str] = {
    "greenhouse": "boards.greenhouse.io",
    "lever": "jobs.lever.co",
    "ashby": "jobs.ashbyhq.com",
    "smartrecruiters": "jobs.smartrecruiters.com",
    "workable": "apply.workable.com",
    "bamboohr": "bamboohr.com/careers",
    "recruitee": "recruitee.com",
}


def build_ats_query(domain: str, params: SearchParams) -> str:
    """
    Build a site-scoped Google query for an ATS domain according to Step 7 rules:
    Pattern: site:{domain} "{job_title}" {remote_token} {location_token} {excludes}
    """
    parts: list[str] = [f"site:{domain}", f'"{params.job_title.strip()}"']

    if params.remote is True:
        parts.append('"remote"')
    elif params.remote is False:
        parts.append('-"remote"')

    if params.location:
        loc = params.location.strip()
        if loc:
            parts.append(f'"{loc}"' if " " in loc else loc)

    if params.exclude_keywords:
        for kw in params.exclude_keywords:
            cleaned = kw.strip()
            if cleaned:
                parts.append(f'-"{cleaned}"')

    return " ".join(parts)


def build_ats_queries(params: SearchParams, platforms: list[str] | None = None) -> dict[str, str]:
    """
    Generate query strings for all requested ATS platforms (defaulting to all 7).
    Returns a mapping of platform_name -> query_string.
    """
    target_domains = (
        {k: v for k, v in ATS_DOMAINS.items() if k in platforms}
        if platforms
        else ATS_DOMAINS
    )
    return {
        platform: build_ats_query(domain, params)
        for platform, domain in target_domains.items()
    }


# ---------------------------------------------------------------------------
# Existing QueryBuilder class preserved for CLI / backward compatibility
# ---------------------------------------------------------------------------

class QueryBuilder:
    """
    Constructs Google search queries tailored for ATS platforms.
    Preserved for CLI compatibility.
    """

    EXPERIENCE_MAPPING = {
        "entry": "entry level",
        "mid": "mid level",
        "senior": "senior",
        "lead": "lead",
    }

    def __init__(self, ats: ATSConfig):
        self.ats = ats

    def build_query_string(self, params: SearchParams) -> str:
        parts: list[str] = [f"site:{self.ats.site_operator}"]
        title = params.job_title.strip()
        parts.append(title)

        if params.location:
            location = params.location.strip()
            if location:
                parts.append(f'"{location}"' if " " in location else location)

        if params.remote is True:
            parts.append('"remote"')
        elif params.remote is False:
            parts.append('-"remote"')

        if params.salary_min is not None:
            parts.append(f"${params.salary_min}")

        if params.experience_level:
            experience_text = self.EXPERIENCE_MAPPING.get(
                params.experience_level,
                params.experience_level,
            )
            parts.append(f'"{experience_text}"')

        if params.days_back is not None and params.days_back > 0:
            cutoff_date = (
                datetime.now(timezone.utc) - timedelta(days=params.days_back)
            ).date()
            parts.append(f"after:{cutoff_date.isoformat()}")

        for keyword in params.exclude_keywords or []:
            cleaned = keyword.strip()
            if not cleaned:
                continue
            if " " in cleaned:
                parts.append(f'-"{cleaned}"')
            else:
                parts.append(f"-{cleaned}")

        return " ".join(parts)

    def build_serper_payload(
        self,
        params: SearchParams,
        page: int = 1,
        num: int = 10,
    ) -> dict:
        payload = {
            "q": self.build_query_string(params),
            "page": page,
            "num": num,
            "hl": "en",
        }
        if params.country_code:
            payload["gl"] = self.normalize_country_code(params.country_code)
        return payload

    @staticmethod
    def normalize_country_code(country_code: Optional[str]) -> Optional[str]:
        if not country_code:
            return None
        return country_code.strip().lower()

    def build_debug_url(self, params: SearchParams, page: int = 0) -> str:
        query_string = self.build_query_string(params)
        url_params = {
            "q": query_string,
            "start": page * 10,
            "num": 10,
        }
        if params.country_code:
            url_params["gl"] = self.normalize_country_code(params.country_code)
        return f"{GOOGLE_BASE_URL}?{urlencode(url_params)}"
