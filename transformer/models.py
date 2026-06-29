from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    type: Literal["csv", "ats_json", "github_url", "resume_pdf", "resume_docx", "recruiter_txt"]
    raw_content: Any
    metadata: dict = Field(default_factory=dict)


class ProvenanceEntry(BaseModel):
    field: str
    source: str
    method: str
    note: str | None = None


class SkillEntry(BaseModel):
    name: str
    confidence: float = 0.8
    sources: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    company: str | None = None
    title: str | None = None
    start: str | None = None   # YYYY-MM
    end: str | None = None     # YYYY-MM or null
    summary: str | None = None


class EducationEntry(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    end_year: int | None = None


class CanonicalRecord(BaseModel):
    candidate_id: str = ""
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: dict | None = None
    links: dict = Field(default_factory=dict)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[SkillEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    overall_confidence: float = 0.0


# Intermediate raw record — loose, unvalidated, source-specific
class RawRecord(BaseModel):
    source_type: str = ""
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location_raw: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    other_urls: list[str] = Field(default_factory=list)
    headline: str | None = None
    years_experience: float | None = None
    skills_raw: list[str] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)
