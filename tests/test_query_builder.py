"""
Tests for Query Builder (Step 7).
"""

from src.project_files.models import SearchParams
from src.project_files.query_builder import ATS_DOMAINS, build_ats_queries, build_ats_query


def test_ats_domains_defined():
    assert "greenhouse" in ATS_DOMAINS
    assert "lever" in ATS_DOMAINS
    assert "ashby" in ATS_DOMAINS
    assert "smartrecruiters" in ATS_DOMAINS
    assert "workable" in ATS_DOMAINS
    assert "bamboohr" in ATS_DOMAINS
    assert "recruitee" in ATS_DOMAINS


def test_basic_query():
    params = SearchParams(job_title="Data Analyst")
    q = build_ats_query("boards.greenhouse.io", params)
    assert q == 'site:boards.greenhouse.io "Data Analyst"'


def test_remote_true_query():
    params = SearchParams(job_title="Backend Engineer", remote=True)
    q = build_ats_query("jobs.lever.co", params)
    assert q == 'site:jobs.lever.co "Backend Engineer" "remote"'


def test_remote_false_query():
    params = SearchParams(job_title="Backend Engineer", remote=False)
    q = build_ats_query("jobs.lever.co", params)
    assert q == 'site:jobs.lever.co "Backend Engineer" -"remote"'


def test_single_word_location():
    params = SearchParams(job_title="Frontend Engineer", location="London")
    q = build_ats_query("jobs.ashbyhq.com", params)
    assert q == 'site:jobs.ashbyhq.com "Frontend Engineer" London'


def test_multi_word_location():
    params = SearchParams(job_title="Frontend Engineer", location="New York")
    q = build_ats_query("jobs.ashbyhq.com", params)
    assert q == 'site:jobs.ashbyhq.com "Frontend Engineer" "New York"'


def test_exclude_keywords():
    params = SearchParams(
        job_title="Software Engineer",
        exclude_keywords=["intern", "contract"],
    )
    q = build_ats_query("apply.workable.com", params)
    assert q == 'site:apply.workable.com "Software Engineer" -"intern" -"contract"'


def test_build_ats_queries_all():
    params = SearchParams(job_title="DevOps Engineer")
    queries = build_ats_queries(params)
    assert len(queries) == 18
    assert "greenhouse" in queries
    assert 'site:greenhouse.io "DevOps Engineer"' == queries["greenhouse"]


def test_build_ats_queries_filtered():
    params = SearchParams(job_title="DevOps Engineer")
    queries = build_ats_queries(params, platforms=["greenhouse", "lever"])
    assert len(queries) == 2
    assert "greenhouse" in queries
    assert "lever" in queries
