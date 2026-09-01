"""
Search Orchestrator, In-Memory Cache, and Global Deduplicator.

Coordinates concurrent searches across ATS platforms (via Serper + ATS APIs)
and Nigerian job boards (via direct HTML scrapers), streaming deduplicated
results progressively to the client.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import time
from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from src.config import settings
from src.project_files.ats_api_client import ATS_CLIENTS
from src.project_files.ats_url_parser import parse_ats_url
from src.project_files.exceptions import BotBlockError, RateLimitError
from src.project_files.models import (
    DoneEvent,
    ErrorEvent,
    JobListing,
    ResultsBatch,
    SearchParams,
)
from src.project_files.nigerian_scrapers import NIGERIAN_SCRAPERS, BaseScraper
from src.project_files.query_builder import ATS_DOMAINS, build_ats_queries

# ---------------------------------------------------------------------------
# Step 9 — In-Memory Cache
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    results: list[JobListing]
    providers_searched: list[str]
    serper_queries_used: int
    stored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: dict[str, CacheEntry] = {}


def _cache_key(params: SearchParams) -> str:
    payload = params.model_dump_json(exclude={"max_results"})
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _cache_get(key: str) -> CacheEntry | None:
    entry = _cache.get(key)
    if not entry:
        return None
    stored_time = entry.stored_at if entry.stored_at.tzinfo else entry.stored_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stored_time).total_seconds()
    if age > settings.cache_ttl_seconds:
        del _cache[key]
        return None
    return entry


def _cache_set(key: str, entry: CacheEntry) -> None:
    _cache[key] = entry


# ---------------------------------------------------------------------------
# Global Deduplicator
# ---------------------------------------------------------------------------

class GlobalDeduplicator:
    def __init__(self):
        self._seen: set[str] = set()

    def filter(self, listings: list[JobListing]) -> list[JobListing]:
        new = [l for l in listings if l.id not in self._seen]
        self._seen.update(l.id for l in new)
        return new


def _sort_by_posted_at(listings: list[JobListing]) -> list[JobListing]:
    """Sort listings by posted_at descending, nulls last."""
    def sort_key(item: JobListing):
        if not item.posted_at:
            return datetime.min.replace(tzinfo=timezone.utc)
        dt = item.posted_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    return sorted(listings, key=sort_key, reverse=True)


# ---------------------------------------------------------------------------
# Step 10 — Search Orchestrator
# ---------------------------------------------------------------------------

class SearchOrchestrator:
    """
    Orchestrates concurrent searches across ATS platforms and Nigerian sites.
    Yields events: ("results", ResultsBatch), ("done", DoneEvent), ("error", ErrorEvent).
    """

    async def _search_ats_serper(
        self,
        platform: str,
        query_str: str,
        params: SearchParams,
        client: httpx.AsyncClient,
    ) -> tuple[str, list[JobListing], bool]:
        """
        Executes Serper search for one ATS platform, parses URLs,
        and fetches structured listings from the ATS API.
        Returns (platform_name, listings, serper_query_used_bool).
        """
        listings: list[JobListing] = []
        serper_used = False

        payload = {
            "q": query_str,
            "page": 1,
            "num": 10,
            "hl": "en",
            "tbs": f"qdr:d{params.days_back}" if params.days_back and params.days_back > 0 else "qdr:d7",
        }
        if params.country_code:
            payload["gl"] = params.country_code.strip().lower()

        try:
            serper_used = True
            resp = await client.post(
                "https://google.serper.dev/search",
                json=payload,
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                timeout=settings.ats_request_timeout_seconds + 5.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"[{platform}] Serper search failed: {exc}")
            return (platform, listings, serper_used)

        organic = data.get("organic", [])
        for item in organic:
            url = item.get("link", "")
            snippet = item.get("snippet", "")
            if not url:
                continue

            parsed = parse_ats_url(url)
            if not parsed:
                # Silently discard non-job URLs
                continue

            ats_client = ATS_CLIENTS.get(parsed.ats)
            if not ats_client:
                continue

            try:
                job = await ats_client.fetch(
                    parsed=parsed,
                    client=client,
                    fallback_snippet=snippet,
                    query_used=query_str,
                )
                if job:
                    listings.append(job)
            except Exception as exc:
                logger.warning(f"[{platform}] Error fetching job from {url}: {exc}")

        return (platform, listings, serper_used)

    async def _search_nigerian_scraper(
        self,
        scraper: BaseScraper,
        params: SearchParams,
        client: httpx.AsyncClient,
    ) -> tuple[str, list[JobListing], bool]:
        """Executes a single Nigerian scraper. Returns (site_name, listings, False)."""
        try:
            listings = await scraper.search(client, params)
            return (scraper.site_name, listings, False)
        except Exception as exc:
            logger.warning(f"[{scraper.site_name}] Scraper failed: {exc}")
            return (scraper.site_name, [], False)

    async def run(
        self,
        params: SearchParams,
        platforms: list[str] | None = None,
    ) -> AsyncGenerator[tuple[str, ResultsBatch | DoneEvent | ErrorEvent], None]:
        start_time = time.monotonic()
        cache_key = _cache_key(params)
        cached_entry = _cache_get(cache_key)

        if cached_entry:
            logger.info(f"Cache hit for query: {params.job_title}")
            sorted_results = _sort_by_posted_at(cached_entry.results)
            yield ("results", ResultsBatch(batch=sorted_results, total_so_far=len(sorted_results)))
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            yield (
                "done",
                DoneEvent(
                    total=len(sorted_results),
                    search_time_ms=elapsed_ms,
                    serper_queries_used=0,
                    providers_searched=cached_entry.providers_searched,
                    providers_skipped=[],
                    cached=True,
                ),
            )
            return

        deduplicator = GlobalDeduplicator()
        all_collected: list[JobListing] = []
        providers_searched: list[str] = []
        providers_skipped: list[str] = []
        serper_queries_used = 0

        # Build list of provider tasks
        ats_queries = build_ats_queries(params, platforms)
        target_ats = list(ats_queries.keys())
        target_nigerian = [s.site_name for s in NIGERIAN_SCRAPERS] if params.include_nigerian_sites else []
        all_candidate_providers = target_ats + target_nigerian

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks: dict[asyncio.Task, str] = {}

            # Create ATS tasks
            for platform, query_str in ats_queries.items():
                t = asyncio.create_task(
                    self._search_ats_serper(platform, query_str, params, client)
                )
                tasks[t] = platform

            # Create Nigerian scraper tasks
            if params.include_nigerian_sites:
                for scraper in NIGERIAN_SCRAPERS:
                    t = asyncio.create_task(
                        self._search_nigerian_scraper(scraper, params, client)
                    )
                    tasks[t] = scraper.site_name

            deadline = time.monotonic() + settings.search_hard_timeout_seconds

            try:
                while tasks:
                    remaining_timeout = max(0.1, deadline - time.monotonic())
                    done, pending = await asyncio.wait(
                        tasks.keys(),
                        timeout=remaining_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if not done:
                        # Timeout reached
                        logger.warning("Search reached hard timeout limit")
                        break

                    for task in done:
                        provider_name = tasks.pop(task)
                        providers_searched.append(provider_name)
                        try:
                            p_name, listings, query_used = task.result()
                            if query_used:
                                serper_queries_used += 1

                            unique_new = deduplicator.filter(listings)
                            if unique_new:
                                all_collected.extend(unique_new)
                                yield (
                                    "results",
                                    ResultsBatch(
                                        batch=unique_new,
                                        total_so_far=len(all_collected),
                                    ),
                                )

                            # Check progressive stopper limit
                            if len(all_collected) >= settings.max_results:
                                logger.info(f"Reached max results limit ({settings.max_results}). Halting remaining tasks.")
                                for pending_task in tasks:
                                    pending_task.cancel()
                                providers_skipped.extend(tasks.values())
                                tasks.clear()
                                break
                        except Exception as exc:
                            logger.warning(f"Task for provider {provider_name} raised: {exc}")

            finally:
                # Cancel any remaining pending tasks
                for pending_task in tasks:
                    pending_task.cancel()
                providers_skipped.extend(tasks.values())

        # Final sort and cache
        final_sorted = _sort_by_posted_at(all_collected)
        if final_sorted:
            _cache_set(
                cache_key,
                CacheEntry(
                    results=final_sorted,
                    providers_searched=providers_searched,
                    serper_queries_used=serper_queries_used,
                ),
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        yield (
            "done",
            DoneEvent(
                total=len(final_sorted),
                search_time_ms=elapsed_ms,
                serper_queries_used=serper_queries_used,
                providers_searched=providers_searched,
                providers_skipped=providers_skipped,
                cached=False,
            ),
        )
