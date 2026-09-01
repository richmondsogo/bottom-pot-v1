"""
Tests for rate limiting on /search endpoint.
"""

from fastapi.testclient import TestClient
from datetime import datetime, timezone

from src.api.main import app, limiter
from src.config import settings
from src.project_files.models import JobListing, SearchParams
from src.project_files.search_pipeline import CacheEntry, _cache, _cache_key, _cache_set

client = TestClient(app)


def test_rate_limiting_exceeded():
    # Reset limiter storage so other tests don't pollute this count
    limiter.reset()

    # Cache dummy results so /search returns immediately without external network calls
    params = SearchParams(
        job_title="RateLimitTest",
        location=None,
        remote=None,
        days_back=7,
        include_nigerian_sites=True,
    )
    key = _cache_key(params)
    dummy_job = JobListing(
        id="greenhouse:test:1",
        provider="greenhouse",
        data_source="api",
        title="RateLimitTest",
        company="Test",
        company_slug="test",
        scraped_at=datetime.now(timezone.utc),
        apply_url="https://boards.greenhouse.io/test/jobs/1",
        source_url="https://boards.greenhouse.io/test/jobs/1",
        query_used="test",
        ats_source="greenhouse",
    )
    _cache_set(
        key,
        CacheEntry(
            results=[dummy_job],
            providers_searched=["greenhouse"],
            serper_queries_used=0,
        ),
    )

    # Exactly 20 requests under 20/hour limit
    limit = settings.rate_limit_per_hour
    for i in range(limit):
        res = client.get("/search?q=RateLimitTest")
        assert res.status_code == 200, f"Request {i+1} failed with status {res.status_code}"

    # The 21st request from same IP must be HTTP 429
    exceeded_res = client.get("/search?q=RateLimitTest")
    assert exceeded_res.status_code == 429
