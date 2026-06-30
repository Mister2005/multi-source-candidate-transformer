import pytest
from transformer.models import RawRecord, ExperienceEntry, EducationEntry
from transformer.merger import merge, _priority, SOURCE_PRIORITY


class TestPriority:
    def test_ats_highest(self):
        assert _priority("ats_json") < _priority("csv")

    def test_csv_above_github(self):
        assert _priority("csv") < _priority("github_url")

    def test_unknown_lowest(self):
        assert _priority("unknown_source") == 99


class TestMerge:
    def test_winner_is_highest_priority(self):
        records = [
            RawRecord(source_type="recruiter_txt", full_name="alex johnson"),
            RawRecord(source_type="ats_json", full_name="Alex Johnson"),
            RawRecord(source_type="csv", full_name="ALEX JOHNSON"),
        ]
        canonical = merge(records)
        assert canonical.full_name == "Alex Johnson"  # ats_json wins

    def test_emails_are_unioned(self):
        records = [
            RawRecord(source_type="csv", emails=["alex@example.com"]),
            RawRecord(source_type="ats_json", emails=["alex@work.com"]),
        ]
        canonical = merge(records)
        assert "alex@example.com" in canonical.emails
        assert "alex@work.com" in canonical.emails

    def test_emails_deduplicated(self):
        records = [
            RawRecord(source_type="csv", emails=["alex@example.com"]),
            RawRecord(source_type="ats_json", emails=["Alex@example.com"]),
        ]
        canonical = merge(records)
        assert canonical.emails.count("alex@example.com") == 1

    def test_skills_unioned_by_canonical_name(self):
        records = [
            RawRecord(source_type="csv", skills_raw=["python", "react"]),
            RawRecord(source_type="ats_json", skills_raw=["Python", "Docker"]),
        ]
        canonical = merge(records)
        skill_names = [s.name for s in canonical.skills]
        assert "Python" in skill_names
        assert "React" in skill_names
        assert "Docker" in skill_names
        assert skill_names.count("Python") == 1  # no duplicate

    def test_candidate_id_is_deterministic(self):
        records = [RawRecord(source_type="csv", emails=["alex@example.com"], full_name="Alex")]
        c1 = merge(records)
        c2 = merge(records)
        assert c1.candidate_id == c2.candidate_id

    def test_empty_records_returns_empty_canonical(self):
        canonical = merge([])
        assert canonical.candidate_id == ""
        assert canonical.emails == []

    def test_provenance_populated(self):
        records = [RawRecord(source_type="csv", full_name="Alex Johnson", emails=["alex@example.com"])]
        canonical = merge(records)
        assert len(canonical.provenance) > 0

    def test_experience_deduped(self):
        exp = ExperienceEntry(company="TechCorp", title="Engineer", start="2021-03")
        records = [
            RawRecord(source_type="csv", experience=[exp]),
            RawRecord(source_type="ats_json", experience=[exp]),
        ]
        canonical = merge(records)
        assert len(canonical.experience) == 1

    def test_experience_dedup_sparse_vs_rich(self):
        """FLAG 4: CSV has company+title but no dates; ATS has same role with dates.
        Should produce ONE entry, taking the richer (dated) version."""
        sparse = ExperienceEntry(company="TechCorp", title="Engineer", start=None, end=None)
        rich = ExperienceEntry(company="TechCorp", title="Engineer", start="2021-03", end=None,
                               summary="Led backend team")
        records = [
            RawRecord(source_type="ats_json", experience=[rich]),
            RawRecord(source_type="csv", experience=[sparse]),
        ]
        canonical = merge(records)
        assert len(canonical.experience) == 1, f"Expected 1 entry, got {len(canonical.experience)}: {canonical.experience}"
        assert canonical.experience[0].start == "2021-03"

    def test_experience_dedup_case_insensitive(self):
        """Dedup should be case-insensitive on company/title."""
        records = [
            RawRecord(source_type="ats_json", experience=[
                ExperienceEntry(company="TechCorp Inc.", title="Senior Engineer", start="2021-03")
            ]),
            RawRecord(source_type="csv", experience=[
                ExperienceEntry(company="techcorp inc.", title="senior engineer", start=None)
            ]),
        ]
        canonical = merge(records)
        assert len(canonical.experience) == 1

    def test_links_other_populated(self):
        """FLAG 5: other_urls from raw records should appear in links.other[]."""
        records = [
            RawRecord(source_type="csv", other_urls=["https://portfolio.example.com"]),
            RawRecord(source_type="ats_json", other_urls=["https://blog.example.com"]),
        ]
        canonical = merge(records)
        assert "other" in canonical.links
        assert isinstance(canonical.links["other"], list)
        assert "https://portfolio.example.com" in canonical.links["other"]
        assert "https://blog.example.com" in canonical.links["other"]

    def test_links_other_empty_when_no_urls(self):
        """links.other should always exist as a list, even if empty."""
        records = [RawRecord(source_type="csv", full_name="Jane")]
        canonical = merge(records)
        assert "other" in canonical.links
        assert canonical.links["other"] == []

    def test_years_experience_computed_from_experience(self):
        """FLAG 6: years_experience derived from experience date ranges when not directly provided."""
        records = [
            RawRecord(source_type="ats_json", experience=[
                ExperienceEntry(company="Acme", title="Engineer", start="2021-01", end="2023-01"),
                ExperienceEntry(company="Beta", title="Senior Engineer", start="2023-01", end=None),
            ])
        ]
        canonical = merge(records)
        assert canonical.years_experience is not None
        assert canonical.years_experience >= 2.0  # at least 2 years from Acme

    def test_years_experience_not_overwritten_if_set(self):
        """years_experience explicitly provided should not be overwritten."""
        records = [
            RawRecord(source_type="ats_json", years_experience=7.5, experience=[
                ExperienceEntry(company="Acme", title="Engineer", start="2022-01", end=None)
            ])
        ]
        canonical = merge(records)
        assert canonical.years_experience == 7.5
