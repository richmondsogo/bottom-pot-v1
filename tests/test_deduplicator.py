"""
Tests for GlobalDeduplicator and In-Memory Cache.
"""

from datetime import datetime, timezone

from src.project_files.models import JobListing, SearchParams
from src.project_files.search_pipeline import (
    CacheEntry,
    GlobalDeduplicator,
    _cache,
    _cache_get,
    _cache_key,
    _cache_set,
)


def _sample_listing(id_: str, provider: str = "greenhouse") -> JobListing:
    return JobListing(
        id=id_,
        provider=provider,
        data_source="api",
        title="Software Engineer",
        company="Stripe",
        company_slug="stripe",
        scraped_at=datetime.now(timezone.utc),
        apply_url=f"https://boards.greenhouse.io/stripe/jobs/{id_}",
        source_url=f"https://boards.greenhouse.io/stripe/jobs/{id_}",
        query_used="test",
        ats_source=provider,
    )


def test_deduplicator_filters_duplicates():
    dedup = GlobalDeduplicator()

    batch1 = [_sample_listing("1"), _sample_listing("2")]
    res1 = dedup.filter(batch1)
    assert len(res1) == 2

    # Batch 2 contains item 2 again and item 3
    batch2 = [_sample_listing("2"), _sample_listing("3")]
    res2 = dedup.filter(batch2)
    assert len(res2) == 1
    assert res2[0].id == "3"

    # Batch 3 with only seen items returns empty list
    batch3 = [_sample_listing("1"), _sample_listing("3")]
    res3 = dedup.filter(batch3)
    assert len(res3) == 0


def test_cache_set_and_get():
    _cache.clear()
    params = SearchParams(job_title="Product Manager")
    key = _cache_key(params)

    assert _cache_get(key) is None

    entry = CacheEntry(
        results=[_sample_listing("100")],
        providers_searched=["greenhouse"],
        serper_queries_used=1,
    )
    _cache_set(key, entry)

    retrieved = _cache_get(key)
    assert retrieved is not None
    assert len(retrieved.results) == 1
    assert retrieved.results[0].id == "100"
