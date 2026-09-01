"""
Tests for ATS API clients and Nigerian scrapers resilience.
"""

import pytest
import httpx

from src.project_files.ats_api_client import (
    GreenhouseClient,
    LeverClient,
    AshbyClient,
    SmartRecruitersClient,
    WorkableClient,
    BambooHRClient,
    RecruiteeClient,
)
from src.project_files.ats_url_parser import parse_ats_url
from src.project_files.nigerian_scrapers import (
    JobbermanScraper,
    MyJobMagScraper,
    NgCareersScraper,
    HotNigerianJobsScraper,
)
from src.project_files.models import SearchParams


@pytest.mark.anyio
async def test_greenhouse_client_success():
    parsed = parse_ats_url("https://boards.greenhouse.io/stripe/jobs/12345")
    assert parsed is not None

    def mock_handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "title": "Staff Engineer",
                "company_name": "Stripe",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345",
                "updated_at": "2024-03-01T12:00:00.000Z",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        gh = GreenhouseClient()
        job = await gh.fetch(parsed, client)
        assert job is not None
        assert job.title == "Staff Engineer"
        assert job.provider == "greenhouse"
        assert job.data_source == "api"
        assert job.company == "Stripe"


@pytest.mark.anyio
async def test_greenhouse_client_404_returns_none():
    parsed = parse_ats_url("https://boards.greenhouse.io/stripe/jobs/99999")
    assert parsed is not None

    def mock_handler(request: httpx.Request):
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        gh = GreenhouseClient()
        job = await gh.fetch(parsed, client)
        assert job is None


@pytest.mark.anyio
async def test_nigerian_scraper_bot_block():
    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text="<html><body>Access Denied - Robot detected captcha</body></html>")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = JobbermanScraper()
        params = SearchParams(job_title="Data Engineer")
        results = await scraper.search(client, params)
        # Should catch BotBlockError internally and return empty list
        assert results == []
