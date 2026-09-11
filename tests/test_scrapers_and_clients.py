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
from src.project_files.ats_page_enricher import enrich_ats_page
from src.project_files.ats_api_client import LeverClient
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


@pytest.mark.anyio
async def test_generic_ats_page_extracts_job_posting_metadata():
    html = """
    <html><head><script type="application/ld+json">
    {"@type":"JobPosting","title":"Backend Engineer","datePosted":"2026-09-01",
     "employmentType":"FULL_TIME","jobLocationType":"TELECOMMUTE",
     "hiringOrganization":{"name":"Example Corp"},
     "jobLocation":{"address":{"addressLocality":"Austin","addressRegion":"TX"}},
     "department":{"name":"Engineering"}}
    </script></head></html>
    """

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        job = await enrich_ats_page(
            url="https://jobs.example.com/backend-engineer",
            provider="example_ats",
            search_title="Backend Engineer",
            snippet="Backend Engineer",
            query_used="site:jobs.example.com Backend Engineer",
            client=client,
        )

    assert job.company == "Example Corp"
    assert job.location == "Austin, TX"
    assert job.employment_type == "full_time"
    assert job.work_model == "remote"
    assert job.department == "Engineering"
    assert job.posted_at is not None
    assert job.posted_at.date().isoformat() == "2026-09-01"


@pytest.mark.anyio
async def test_generic_ats_page_handles_graph_and_array_json_ld():
    html = """
    <script type="application/ld+json">[
      {"@graph":[{"@type":"JobPosting","title":"Platform Engineer",
       "datePosted":"2026-09-02","employmentType":"CONTRACT",
       "hiringOrganization":{"name":"Graph Corp"},
       "jobLocation":{"address":{"addressLocality":"London"}}} ]}
    ]</script>
    """

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        job = await enrich_ats_page(
            "https://jobs.example.com/platform",
            "example_ats",
            "Platform Engineer",
            "",
            "test",
            client,
        )

    assert job.company == "Graph Corp"
    assert job.employment_type == "contract"
    assert job.posted_at is not None


def test_human_readable_date_is_parsed():
    from src.project_files.field_normalizer import parse_datetime

    assert parse_datetime("Sep 9, 2026").date().isoformat() == "2026-09-09"


@pytest.mark.anyio
async def test_generic_ats_page_without_metadata_is_honest_snippet_fallback():
    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text="<html><body>JavaScript application shell</body></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        job = await enrich_ats_page(
            "https://jobs.example.com/unknown",
            "example_ats",
            "Backend Engineer",
            "A posting without structured metadata",
            "test",
            client,
        )

    assert job.data_source == "snippet"
    assert job.company == "Unknown"
    assert job.location is None
    assert job.posted_at is None


@pytest.mark.anyio
async def test_api_client_humanizes_company_slug_when_provider_omits_name():
    parsed = parse_ats_url("https://jobs.lever.co/acme-corp-2024/12345678-1234-1234-1234-123456789012")
    assert parsed is not None

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"text": "Backend Engineer", "categories": {"location": "Remote"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        job = await LeverClient().fetch(parsed, client)

    assert job is not None
    assert job.company == "Acme Corp 2024"
    assert job.company != parsed.company_slug


@pytest.mark.anyio
async def test_workable_markdown_extracts_structured_fields():
    parsed = parse_ats_url("https://apply.workable.com/treq/j/D94DBAF102")
    assert parsed is not None
    markdown = """# Software Engineer
> TreQ · Milton, United Kingdom · Full-time · Posted 2026-09-08
**Workplace:** on_site
**Department:** Engineering
"""

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text=markdown)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        job = await WorkableClient().fetch(parsed, client)

    assert job is not None
    assert job.data_source == "scrape"
    assert job.company == "TreQ"
    assert job.location == "Milton, United Kingdom"
    assert job.employment_type == "full_time"
    assert job.work_model == "in_person"
    assert job.department == "Engineering"
    assert job.posted_at is not None


@pytest.mark.anyio
async def test_nigerian_remote_state_comes_from_card_not_search_filter():
    html = """
    <article>
      <h2><a href="/listings/backend-engineer">Backend Engineer</a></h2>
      <p class="text-sm text-link-500">Example Ltd</p>
      <span class="location">Lagos</span>
      <span>Employment Type: Full time</span>
      <span>Location Type: On-site</span>
      <span>Department: Engineering</span>
      <time datetime="2026-09-03">Sep 3, 2026</time>
    </article>
    """

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        scraper = JobbermanScraper()
        results = await scraper.search(client, SearchParams(job_title="Backend Engineer", remote=True))

    assert len(results) == 1
    assert results[0].is_remote is False
    assert results[0].employment_type == "full_time"
    assert results[0].work_model == "in_person"
    assert results[0].department == "Engineering"
    assert results[0].posted_at is not None


@pytest.mark.anyio
async def test_jazzhr_share_page_resolves_and_extracts_all_fields():
    """JazzHR share page should resolve to the apply page and extract company,
    location, employment_type, work_model, and posted_at from the JSON-LD."""
    import pathlib

    fixture_path = pathlib.Path(__file__).resolve().parent / "fixtures" / "jazzhr_apply.html"
    if not fixture_path.exists():
        pytest.skip("JazzHR apply fixture not available")

    apply_html = fixture_path.read_text(encoding="utf-8", errors="replace")

    # The share page HTML that contains a link to the apply page
    share_html = """
    <html><body>
    <div class="focus-subheader-content">
        <h1><a href="/apply/kmnC9eIyPq/Senior-Software-Engineer-Product">Senior Software Engineer (Product)</a></h1>
    </div>
    <ul id="focus-subheader-content-info">
        <li><i class="fa fa-map-marker"></i> Austin, TX</li>
        <li><i class="fa fa-clock-o"></i> Full-time</li>
    </ul>
    <a href="/apply/kmnC9eIyPq/Senior-Software-Engineer-Product">Apply</a>
    </body></html>
    """

    call_count = 0

    def mock_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        url = str(request.url)
        if "/app/share/" in url:
            return httpx.Response(200, text=share_html)
        elif "/apply/" in url:
            return httpx.Response(200, text=apply_html)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        job = await enrich_ats_page(
            url="https://activeprospect.applytojob.com/app/share/kmnC9eIyPq",
            provider="jazzhr",
            search_title="Senior Software Engineer (Product)",
            snippet="",
            query_used="test",
            client=client,
        )

    # Should have fetched both the share page and the apply page
    assert call_count >= 2
    assert job.company == "ActiveProspect, Inc."
    assert "Austin" in (job.location or "")
    assert "TX" in (job.location or "")
    assert job.employment_type == "full_time"
    assert job.work_model == "remote"
    assert job.posted_at is not None
    assert job.posted_at.date().isoformat() == "2026-09-03"
