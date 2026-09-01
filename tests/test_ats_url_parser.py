"""
Tests for src/project_files/ats_url_parser.py

Covers:
- All 7 ATS platforms with valid URLs
- URL variants (e.g., boards.greenhouse.io vs job-boards.greenhouse.io)
- Rejection of homepages, search pages, blog posts, partial paths
- Edge cases: None, empty string, malformed URL
"""

import pytest

from src.project_files.ats_url_parser import ParsedATSUrl, parse_ats_url


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

class TestGreenhouse:
    def test_boards_greenhouse_io(self):
        url = "https://boards.greenhouse.io/stripe/jobs/4567890"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "greenhouse"
        assert result.company_slug == "stripe"
        assert result.job_id == "4567890"
        assert result.raw_url == url

    def test_job_boards_greenhouse_io(self):
        url = "https://job-boards.greenhouse.io/openai/jobs/1234567"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "greenhouse"
        assert result.company_slug == "openai"
        assert result.job_id == "1234567"

    def test_greenhouse_homepage_rejected(self):
        assert parse_ats_url("https://boards.greenhouse.io/stripe") is None

    def test_greenhouse_jobs_root_rejected(self):
        # /jobs without a numeric ID at the end
        assert parse_ats_url("https://boards.greenhouse.io/stripe/jobs") is None

    def test_greenhouse_non_numeric_job_id_rejected(self):
        # The spec requires a numeric job ID for Greenhouse
        assert parse_ats_url("https://boards.greenhouse.io/stripe/jobs/abc-def") is None

    def test_greenhouse_trailing_slash(self):
        url = "https://boards.greenhouse.io/stripe/jobs/9999999/"
        result = parse_ats_url(url)
        assert result is not None
        assert result.job_id == "9999999"

    def test_greenhouse_with_query_string(self):
        # Query strings should be stripped; core path must still match
        url = "https://boards.greenhouse.io/stripe/jobs/4567890?utm_source=linkedin"
        result = parse_ats_url(url)
        assert result is not None
        assert result.job_id == "4567890"


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

class TestLever:
    VALID = "https://jobs.lever.co/anthropic/d1e9b6e2-4c1a-4f7e-b3e9-1a2b3c4d5e6f"

    def test_valid_lever_url(self):
        result = parse_ats_url(self.VALID)
        assert result is not None
        assert result.ats == "lever"
        assert result.company_slug == "anthropic"
        assert result.job_id == "d1e9b6e2-4c1a-4f7e-b3e9-1a2b3c4d5e6f"

    def test_lever_homepage_rejected(self):
        assert parse_ats_url("https://jobs.lever.co/anthropic") is None

    def test_lever_non_uuid_rejected(self):
        assert parse_ats_url("https://jobs.lever.co/anthropic/software-engineer") is None

    def test_lever_trailing_slash(self):
        url = self.VALID + "/"
        result = parse_ats_url(url)
        assert result is not None


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

class TestAshby:
    VALID = "https://jobs.ashbyhq.com/figma/a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_valid_ashby_url(self):
        result = parse_ats_url(self.VALID)
        assert result is not None
        assert result.ats == "ashby"
        assert result.company_slug == "figma"

    def test_ashby_homepage_rejected(self):
        assert parse_ats_url("https://jobs.ashbyhq.com/figma") is None

    def test_ashby_non_uuid_rejected(self):
        assert parse_ats_url("https://jobs.ashbyhq.com/figma/design-engineer") is None


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------

class TestSmartRecruiters:
    VALID = "https://jobs.smartrecruiters.com/Spotify/743999800573774"

    def test_valid_smartrecruiters_url(self):
        result = parse_ats_url(self.VALID)
        assert result is not None
        assert result.ats == "smartrecruiters"
        assert result.company_slug == "Spotify"
        assert result.job_id == "743999800573774"

    def test_smartrecruiters_homepage_rejected(self):
        assert parse_ats_url("https://jobs.smartrecruiters.com/Spotify") is None

    def test_smartrecruiters_non_numeric_job_id_rejected(self):
        assert parse_ats_url("https://jobs.smartrecruiters.com/Spotify/data-engineer") is None


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------

class TestWorkable:
    def test_subdomain_variant(self):
        url = "https://acme.workable.com/jobs/ABC123"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "workable"
        assert result.company_slug == "acme"
        assert result.job_id == "ABC123"

    def test_apply_variant(self):
        url = "https://apply.workable.com/acme/j/DEF456"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "workable"
        assert result.company_slug == "acme"
        assert result.job_id == "DEF456"

    def test_workable_homepage_rejected(self):
        assert parse_ats_url("https://acme.workable.com") is None

    def test_workable_apply_homepage_rejected(self):
        assert parse_ats_url("https://apply.workable.com/acme") is None


# ---------------------------------------------------------------------------
# BambooHR
# ---------------------------------------------------------------------------

class TestBambooHR:
    def test_valid_bamboohr_url(self):
        url = "https://techcorp.bamboohr.com/careers/42"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "bamboohr"
        assert result.company_slug == "techcorp"
        assert result.job_id == "42"

    def test_bamboohr_homepage_rejected(self):
        assert parse_ats_url("https://techcorp.bamboohr.com") is None

    def test_bamboohr_careers_root_rejected(self):
        assert parse_ats_url("https://techcorp.bamboohr.com/careers") is None


# ---------------------------------------------------------------------------
# Recruitee
# ---------------------------------------------------------------------------

class TestRecruitee:
    def test_valid_recruitee_url(self):
        url = "https://mycompany.recruitee.com/o/1234567-senior-python-engineer"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "recruitee"
        assert result.company_slug == "mycompany"
        assert result.job_id == "1234567"

    def test_recruitee_homepage_rejected(self):
        assert parse_ats_url("https://mycompany.recruitee.com") is None

    def test_recruitee_no_numeric_id_rejected(self):
        # No numeric prefix before the dash
        assert parse_ats_url("https://mycompany.recruitee.com/o/senior-python-engineer") is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_none_input(self):
        assert parse_ats_url(None) is None  # type: ignore[arg-type]

    def test_empty_string(self):
        assert parse_ats_url("") is None

    def test_totally_unrelated_url(self):
        assert parse_ats_url("https://www.linkedin.com/jobs/view/12345") is None

    def test_http_scheme_also_works(self):
        url = "http://boards.greenhouse.io/stripe/jobs/4567890"
        result = parse_ats_url(url)
        assert result is not None
        assert result.ats == "greenhouse"

    def test_malformed_url_does_not_raise(self):
        # Should return None, not raise
        result = parse_ats_url("not-a-url-at-all-:::###")
        assert result is None
