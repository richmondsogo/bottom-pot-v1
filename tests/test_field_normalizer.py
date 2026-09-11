"""
Direct unit tests for the canonical work-model resolver.

The canonical ``normalize_work_model`` is shared by every ATS provider, so a
regression here breaks everything at once. These tests cover all four input
shapes independently of any provider:
  1. explicit structured field present (each of remote/hybrid/in_person)
  2. no structured field but a keyword match (each keyword variant added)
  3. no structured field, no keyword, but a real location string (must default
     to in_person)
  4. no structured field, no keyword, no location at all (must be None)
"""

import pytest

from src.project_files.field_normalizer import normalize_job_type_from_text, normalize_work_model


class TestExplicitStructuredField:
    """A provider-published workplace-type field always wins and short-circuits."""

    @pytest.mark.parametrize(
        "value",
        [
            "remote", "Remote", "REMOTE", "Remote - US",
            "work from home", "Work From Home", "wfh",
            "telecommute", "Telecommute (US)", "TELECOMMUTE",
            "100% Remote", "Home Office", "distributed", "anywhere",
        ],
    )
    def test_structured_maps_to_remote(self, value):
        assert normalize_work_model(value) == "remote"

    @pytest.mark.parametrize("value", ["hybrid", "Hybrid", "HYBRID", "Hybrid (3 days)", "Flexible"])
    def test_structured_maps_to_hybrid(self, value):
        assert normalize_work_model(value) == "hybrid"

    @pytest.mark.parametrize(
        "value",
        ["onsite", "On-Site", "on_site", "ON-SITE", "in person", "In-Person", "Office", "office-based", "vor Ort"],
    )
    def test_structured_maps_to_in_person(self, value):
        assert normalize_work_model(value) == "in_person"

    def test_boolean_is_remote_short_circuits(self):
        assert normalize_work_model(None, True, location="San Francisco, CA", description="hybrid") == "remote"
        assert normalize_work_model(None, False, location="Remote", description="fully remote") == "in_person"

    def test_structured_short_circuits_free_text(self):
        assert normalize_work_model("onsite", description="100% remote team") == "in_person"
class TestKeywordScan:
    """No structured field, but a keyword appears in title/location/snippet/description."""

    @pytest.mark.parametrize(
        "desc",
        [
            "This role supports work from home",
            "Telecommute options available",
            "A WFH-first culture",
            "We are a distributed team",
            "Work from anywhere",
            "Home Office in Deutschland",
            "Télétravail possible",
            "100% remote role",
            "Fully remote work",
        ],
    )
    def test_remote_keywords_in_description(self, desc):
        assert normalize_work_model(None, description=desc) == "remote"

    def test_remote_keyword_in_title(self):
        assert normalize_work_model(None, title="Remote Software Engineer", location="London") == "remote"
        assert normalize_work_model(None, title="Backend Engineer (Virtual)") == "remote"

    def test_remote_keyword_in_location(self):
        assert normalize_work_model(None, location="Remote - United States") == "remote"
        assert normalize_work_model(None, location="Anywhere in the US") == "remote"

    def test_new_remote_patterns_in_description(self):
        assert normalize_work_model(None, description="Fully remote position") == "remote"
        assert normalize_work_model(None, description="Remote-first company") == "remote"
        assert normalize_work_model(None, description="Remote only role") == "remote"
        assert normalize_work_model(None, description="Remote friendly team") == "remote"
        assert normalize_work_model(None, description="Remote available worldwide") == "remote"

    @pytest.mark.parametrize(
        "desc",
        [
            "This is a hybrid role",
            "Work partially remote",
            "Some remote days per week",
            "Our flexible remote work model",
            "Remote / On-Site blend",
        ],
    )
    def test_hybrid_keywords_in_description(self, desc):
        assert normalize_work_model(None, description=desc) == "hybrid"

    def test_hybrid_keyword_in_title(self):
        assert normalize_work_model(None, title="Frontend Engineer (Hybrid)", location="Berlin, DE") == "hybrid"
        assert normalize_work_model(None, title="Designer — Flexible", location="Paris") == "hybrid"

    def test_hybrid_wins_over_remote_in_same_text(self):
        assert normalize_work_model(None, description="flexible hybrid work model that embraces remote work") == "hybrid"

    @pytest.mark.parametrize(
        "desc",
        [
            "Mix of remote and office work",
            "Mixture of home and office",
            "Combination of remote and on-site",
            "Split between office and home",
            "Remote and office hybrid model",
            "Office and remote work",
            "Partially on site position",
            "Three days in the office",
            "In the office 3 days per week",
            "Hybridised role",
        ],
    )
    def test_new_hybrid_patterns_in_description(self, desc):
        assert normalize_work_model(None, description=desc) == "hybrid"

    def test_hybrid_from_structured_value(self):
        assert normalize_work_model("Hybrid Work") == "hybrid"
        assert normalize_work_model("Hybrid (3 days in office)") == "hybrid"

    @pytest.mark.parametrize(
        "desc",
        [
            "Onsite or Remote",
            "Remote or Onsite",
            "Office or remote work",
            "Remote or office based",
            "In office or remote",
            "On site or remote position",
        ],
    )
    def test_hybrid_or_connector_patterns(self, desc):
        assert normalize_work_model(None, description=desc) == "hybrid"

    @pytest.mark.parametrize(
        "desc",
        [
            "Must work from the office",
            "This is an on-site role",
            "In-person collaboration required",
            "Office-based position",
            "Arbeit vor Ort",
            "Presencial in our office",
        ],
    )
    def test_in_person_keywords_in_description(self, desc):
        assert normalize_work_model(None, description=desc) == "in_person"

    def test_in_person_keyword_in_location(self):
        assert normalize_work_model(None, location="On Site - Austin, TX") == "in_person"

    def test_new_in_person_patterns_in_description(self):
        assert normalize_work_model(None, description="Face to face collaboration required") == "in_person"


class TestDefaultToInPerson:
    """No keyword anywhere, but a real physical location is present."""

    @pytest.mark.parametrize(
        "location",
        [
            "Phoenix, Arizona, United States",
            "Austin, TX",
            "London, UK",
            "Munich, Germany",
            "Tokyo, Japan",
            "New York, NY 10001",
            "Chicago, IL",
            "San Francisco, CA",
            "Berlin, Germany",
            "Paris, France",
        ],
    )
    def test_city_location_defaults_to_in_person(self, location):
        assert normalize_work_model(None, location=location) == "in_person"
        assert normalize_work_model(None, location=location, title="Data Engineer", description="Join our team") == "in_person"

    def test_remote_sounding_location_does_not_default_to_in_person(self):
        assert normalize_work_model(None, location="Remote / Anywhere") == "remote"
        assert normalize_work_model(None, location="Worldwide") == "remote"
        assert normalize_work_model(None, location="Virtual - US") == "remote"

    def test_hybrid_location_is_hybrid(self):
        assert normalize_work_model(None, location="Austin, TX (Hybrid)") == "hybrid"

    def test_default_can_be_disabled(self):
        want_none = normalize_work_model(None, location="Dallas, TX", default_in_person=False)
        assert want_none is None


class TestNoSignal:
    """No structured field, no keyword, no location -> None."""

    def test_all_empty(self):
        assert normalize_work_model(None) is None

    def test_only_title(self):
        assert normalize_work_model(None, title="Backend Engineer") is None

    def test_flexible_hours_in_description_does_not_flip_in_person(self):
        assert normalize_work_model(None, location="Cleveland, OH", description="Flexible working hours and benefits") == "in_person"


class TestJobTypeTextScan:
    def test_internship(self):
        assert normalize_job_type_from_text("Summer internship program for students") == "internship"

    def test_part_time(self):
        assert normalize_job_type_from_text("This is a part-time position") == "part_time"

    def test_contract(self):
        assert normalize_job_type_from_text("12-month contract role") == "contract"
        assert normalize_job_type_from_text("Contractor position") == "contract"

    def test_full_time(self):
        assert normalize_job_type_from_text("Full-time employment with benefits") == "full_time"

    def test_none_when_no_signal(self):
        assert normalize_job_type_from_text("Join our growing engineering team.") is None

    def test_html_tags_are_tolerated(self):
        assert normalize_job_type_from_text("<div>Full-time</div> role") == "full_time"

    def test_greenhouse_content_full_time(self):
        """Greenhouse boards API returns employment_type rarely; scan content body."""
        content = "<h1>Software Engineer</h1><p>We are looking for a full-time engineer to join our team.</p>"
        assert normalize_job_type_from_text(content) == "full_time"

    def test_greenhouse_content_contract(self):
        content = "<p>This is a 6-month contract role. The contractor will work on our platform.</p>"
        assert normalize_job_type_from_text(content) == "contract"

    def test_greenhouse_content_internship(self):
        content = "<p>Summer internship program for engineering students. Apply now!</p>"
        assert normalize_job_type_from_text(content) == "internship"

    def test_greenhouse_content_part_time(self):
        content = "<p>Part-time position: 20 hours per week. Flexible schedule.</p>"
        assert normalize_job_type_from_text(content) == "part_time"

    def test_lever_workplace_type_remote(self):
        """Lever exposes explicit workplaceType field with values like 'remote'."""
        assert normalize_work_model("remote", location="Taiwan, Taipei") == "remote"
        assert normalize_work_model("remote", location="Taiwan, Taipei", title="Affiliate BD") == "remote"

    def test_lever_workplace_type_hybrid(self):
        """Lever exposes explicit workplaceType field with values like 'hybrid'."""
        assert normalize_work_model("hybrid", location="Taiwan, Taipei") == "hybrid"
        assert normalize_work_model("hybrid", location="Asia", title="AI Agent Engineer") == "hybrid"

    def test_lever_workplace_type_onsite(self):
        """Lever exposes explicit workplaceType field with values like 'onsite'."""
        assert normalize_work_model("onsite", location="Singapore") == "in_person"
        assert normalize_work_model("on-site", location="Hong Kong") == "in_person"

    def test_lever_commitment_fallback(self):
        """Lever commitment field like 'Full-time Onsite or Remote' should match keyword."""
        assert normalize_work_model(None, snippet="Full-time Onsite or Remote", location="Taiwan, Taipei") == "hybrid"
        assert normalize_work_model(None, snippet="Full-time: Remote", location="Taiwan, Taipei") == "remote"
        assert normalize_work_model(None, snippet="Full-time Onsite", location="Taipei") == "in_person"

    def test_lever_location_only_defaults_in_person(self):
        """Lever with only a location (no workplaceType, no keyword) should default to in_person."""
        assert normalize_work_model(None, location="Taiwan, Taipei") == "in_person"
        assert normalize_work_model(None, location="Singapore") == "in_person"