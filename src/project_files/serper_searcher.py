import httpx
from typing import Optional
from loguru import logger

from src.project_files.config import (
    ATS_PLATFORMS,
    SERPER_API_KEY,
    SERPER_ENDPOINT,
    SERPER_MAX_PAGES,
)
from src.project_files.models import ATSConfig, RawSearchResults, SearchParams
from src.project_files.query_builder import QueryBuilder


class SerperSearcher:
    """
    I created this class to query Google Search via Serper.dev's JSON API.
    Each paginated request costs 1 Serper credit, so I budget carefully.
    With 2,500 free credits, I can do about 41 full runs across all platforms at 3 pages each.
    You use it like: searcher = SerperSearcher(); results = await searcher.run(SearchParams(job_title="Data Engineer"))
    """

    def __init__(self):
        # I check for the API key right away because I can't work without it.
        # If you forget to set SERPER_API_KEY in .env, It'll raise an error.
        if not SERPER_API_KEY:
            raise RuntimeError(
                "Serper API key not found. Please set SERPER_API_KEY in your .env file."
            )
        # I set up headers for the API calls. I included the API key and content type.
        self.headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        }

    async def _search_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        page: int,
        country_code: Optional[str],
        days_back: Optional[int],
    ) -> dict:
        """
        I made a single paginated Serper API request. Page is 1-indexed.
        I fixed num at 10 for more results per credit. I also added hl=en for English results and tbs for date filtering.
        I handle HTTP errors and log them. If the key is invalid or quota is exhausted, It'll raise a RuntimeError.
        """
        # I built the payload with query, page, num, etc.
        payload: dict = {
            "q": query,
            "page": page,
            "num": 10,
            "hl": "en",
            "tbs": f"qdr:d{days_back}" if days_back and days_back > 0 else "qdr:d7",
        }

        # If country code is present, add gl.
        if country_code:
            payload["gl"] = country_code

        # I made the POST request to Serper.
        try:
            response = await client.post(
                SERPER_ENDPOINT,
                json=payload,
                headers=self.headers,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            # If 403, it's invalid key or quota.
            if e.response.status_code == 403:
                raise RuntimeError("Serper API key is invalid or quota is exhausted.")
            # I log other errors here.
            logger.error(
                f"Serper HTTP {e.response.status_code} on page {page} for query: {query}"
            )
            return {}

    def _parse_response(
        self,
        data: dict,
        ats: ATSConfig,
        query_str: str,
    ) -> list[RawSearchResults]:
        """
        I extracted organic results from Serper response.
        Serper gives results under data["organic"] with link, title, snippet, date.
        Date is relative like "3 hours ago", useful for dedup later.
        """
        results: list[RawSearchResults] = []

        # I loop through organic results.
        for item in data.get("organic", []):
            url = item.get("link", "")
            title = item.get("title", "")

            # I skipped if no https or no title.
            if not url.startswith("https") or not title:
                continue

            # I created a RawSearchResults object.
            results.append(
                RawSearchResults(
                    url=url,
                    title=title,
                    snippet=item.get("snippet", "").strip() or None,
                    ats_source=ats.name,
                    query_used=query_str,
                )
            )

        return results

    async def search_ats_platform(
        self,
        client: httpx.AsyncClient,
        ats: ATSConfig,
        params: SearchParams,
        query_str: str,
    ) -> list[RawSearchResults]:
        """
        I search one ATS platform across all configured pages.
        I always run the full SERPER_MAX_PAGES because Google might surface different listings later.
        """
        all_results: list[RawSearchResults] = []

        # I looped through pages 1 to SERPER_MAX_PAGES.
        for page in range(1, SERPER_MAX_PAGES + 1):
            logger.debug(f"[{ats.label}] Fetching page {page} | query: {query_str}")

            # I got data from the page.
            data = await self._search_page(
                client,
                query_str,
                page,
                country_code=params.country_code,
                days_back=params.days_back,
            )

            # I parsed the results.
            page_results = self._parse_response(data, ats, query_str)
            all_results.extend(page_results)
            logger.info(
                f"[{ats.label}] Page {page}/{SERPER_MAX_PAGES} → {len(page_results)} results"
            )

        return all_results

    async def run(
        self,
        params: SearchParams,
        platforms: Optional[list[ATSConfig]] = None,
    ) -> list[RawSearchResults]:
        """
        I run the full search across all or selected ATS platforms.
        I cap results at params.max_results after all platforms.
        """
        all_results: list[RawSearchResults] = []
        target_platforms = platforms or ATS_PLATFORMS

        # I use an async client for all requests.
        async with httpx.AsyncClient(timeout=30.0) as client:
            # To search each platform.
            for ats in target_platforms:
                query_str = QueryBuilder(ats).build_query_string(params)
                logger.info(f"[{ats.label}] Starting search | query: {query_str}")

                platform_results = await self.search_ats_platform(
                    client, ats, params, query_str
                )
                all_results.extend(platform_results)

                logger.success(
                    f"[{ats.label}] Done — {len(platform_results)} results "
                    f"(running total: {len(all_results)})"
                )

        # I capped the results if max_results is set.
        if params.max_results:
            all_results = all_results[: params.max_results]
            logger.info(f"Results capped at max_results={params.max_results}")

        return all_results
