import pytest
from transformer.models import CanonicalRecord, SkillEntry, ExperienceEntry, EducationEntry, ProvenanceEntry
from transformer.projector import project


def _make_record(**kwargs) -> CanonicalRecord:
    defaults = dict(
        candidate_id="abc123",
        full_name="Jane Doe",
        emails=["jane@example.com"],
        phones=["+14155550199"],
        location={"city": "New York", "region": "NY", "country": "US"},
        links={"linkedin": "https://linkedin.com/in/janedoe", "github": None, "portfolio": None, "other": []},
        headline="Data Scientist",
        years_experience=5.0,
        skills=[SkillEntry(name="Python", confidence=0.9, sources=["csv"]),
                SkillEntry(name="SQL", confidence=0.8, sources=["ats_json"])],
        experience=[ExperienceEntry(company="Acme", title="Engineer", start="2020-01", end=None)],
        education=[EducationEntry(institution="MIT", degree="BS", field="CS", end_year=2020)],
        provenance=[ProvenanceEntry(field="full_name", source="csv", method="direct")],
        overall_confidence=0.85,
    )
    defaults.update(kwargs)
    return CanonicalRecord(**defaults)


class TestProjectFieldSelection:
    def test_selects_only_requested_fields(self):
        rec = _make_record()
        config = {"fields": [{"path": "full_name", "type": "string"}]}
        result, errs = project(rec, config)
        assert "full_name" in result
        assert "emails" not in result
        assert not errs

    def test_renames_field_via_from(self):
        rec = _make_record()
        config = {"fields": [{"path": "primary_email", "from": "emails[0]", "type": "string"}]}
        result, errs = project(rec, config)
        assert result["primary_email"] == "jane@example.com"
        assert "emails" not in result

    def test_array_flatten_skills_name(self):
        rec = _make_record()
        config = {"fields": [{"path": "top_skills", "from": "skills[].name", "type": "string[]"}]}
        result, errs = project(rec, config)
        assert result["top_skills"] == ["Python", "SQL"]

    def test_dot_notation_location_country(self):
        rec = _make_record()
        config = {"fields": [{"path": "country", "from": "location.country", "type": "string"}]}
        result, errs = project(rec, config)
        assert result["country"] == "US"

    def test_no_fields_returns_full_record(self):
        rec = _make_record()
        result, errs = project(rec, {})
        assert "full_name" in result
        assert "emails" in result
        assert "overall_confidence" in result


class TestProjectMissingPolicy:
    def test_on_missing_null(self):
        rec = _make_record(headline=None)
        config = {"fields": [{"path": "headline", "type": "string"}], "on_missing": "null"}
        result, errs = project(rec, config)
        assert result["headline"] is None
        assert not errs

    def test_on_missing_omit(self):
        rec = _make_record(headline=None)
        config = {"fields": [{"path": "headline", "type": "string"}], "on_missing": "omit"}
        result, errs = project(rec, config)
        assert "headline" not in result
        assert not errs

    def test_on_missing_error_returns_structured_error(self):
        """FLAG 9 fix: on_missing=error must NOT raise — returns structured error list."""
        rec = _make_record(full_name=None)
        config = {
            "fields": [{"path": "full_name", "type": "string", "required": True}],
            "on_missing": "error",
        }
        # Must not raise
        result, errs = project(rec, config)
        assert len(errs) == 1
        assert "full_name" in errs[0]
        # Field still present in output as null (so caller can see what failed)
        assert result["full_name"] is None

    def test_on_missing_error_does_not_raise(self):
        """Explicit: project() must never raise even with on_missing=error."""
        rec = _make_record(full_name=None, emails=[])
        config = {
            "fields": [
                {"path": "full_name", "type": "string", "required": True},
                {"path": "primary_email", "from": "emails[0]", "type": "string", "required": True},
            ],
            "on_missing": "error",
        }
        try:
            result, errs = project(rec, config)
            assert len(errs) == 2  # both fields missing
        except Exception as e:
            pytest.fail(f"project() raised unexpectedly: {e}")


class TestProjectConfidenceToggle:
    def test_include_confidence_true(self):
        rec = _make_record()
        config = {"fields": [{"path": "full_name", "type": "string"}], "include_confidence": True}
        result, _ = project(rec, config)
        assert "_confidence" in result
        assert "_provenance" in result

    def test_include_confidence_false(self):
        rec = _make_record()
        config = {"fields": [{"path": "full_name", "type": "string"}], "include_confidence": False}
        result, _ = project(rec, config)
        assert "_confidence" not in result
        assert "_provenance" not in result

    def test_include_confidence_false_full_schema(self):
        rec = _make_record()
        result, _ = project(rec, {"include_confidence": False})
        assert "overall_confidence" not in result
        assert "provenance" not in result


class TestProjectNormalization:
    def test_normalize_e164(self):
        rec = _make_record(phones=["(415) 555-0199"])
        config = {"fields": [{"path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164"}]}
        result, _ = project(rec, config)
        assert result["phone"] == "+14155550199"

    def test_normalize_canonical_skills(self):
        rec = _make_record(skills=[SkillEntry(name="python", confidence=0.9, sources=["csv"])])
        config = {"fields": [{"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"}]}
        result, _ = project(rec, config)
        assert "Python" in result["skills"]
