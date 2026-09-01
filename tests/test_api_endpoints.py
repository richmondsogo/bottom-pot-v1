"""
Tests for FastAPI application endpoints.
"""

import csv
import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings
from src.project_files.models import JobListing
from src.project_files.search_pipeline import CacheEntry, _cache, _cache_key, _cache_set
from datetime import datetime, timezone

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"


def test_subscribe_endpoint(tmp_path):
    sub_file = str(tmp_path / "test_subs.csv")
    settings.subscriptions_file = sub_file

    payload = {"email": "user@example.com", "search_query": "Data Scientist"}
    response = client.post("/subscribe", json=payload)
    assert response.status_code == 201
    assert response.json() == {"subscribed": True}

    assert os.path.exists(sub_file)
    with open(sub_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 2  # header + 1 row
        assert reader[0] == ["email", "search_query", "subscribed_at"]
        assert reader[1][0] == "user@example.com"
        assert reader[1][1] == "Data Scientist"


def test_search_endpoint_cached_stream():
    # Prime cache with a dummy entry
    from src.project_files.models import SearchParams
    params = SearchParams(
        job_title="DevOps Lead",
        location=None,
        remote=None,
        days_back=7,
        include_nigerian_sites=True,
    )
    key = _cache_key(params)
    dummy_job = JobListing(
        id="greenhouse:acme:123",
        provider="greenhouse",
        data_source="api",
        title="DevOps Lead",
        company="Acme",
        company_slug="acme",
        scraped_at=datetime.now(timezone.utc),
        apply_url="https://boards.greenhouse.io/acme/jobs/123",
        source_url="https://boards.greenhouse.io/acme/jobs/123",
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

    response = client.get("/search?q=DevOps+Lead")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    content = response.text
    assert "event: results" in content
    assert "DevOps Lead" in content
    assert "event: done" in content
    assert '"cached":true' in content
