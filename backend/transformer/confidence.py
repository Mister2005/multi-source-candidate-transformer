import logging
from transformer.models import CanonicalRecord, SkillEntry

logger = logging.getLogger(__name__)

# Base confidence by source type
SOURCE_BASE: dict[str, float] = {
    "ats_json": 0.95,
    "csv": 0.90,
    "github_url": 0.85,
    "resume_pdf": 0.75,
    "resume_docx": 0.75,
    "recruiter_txt": 0.60,
    "multiple": 0.80,
    "direct": 0.85,
    "direct+normalize": 0.85,
    "direct+normalize(E164)": 0.85,
    "keyword_match+canonicalize": 0.70,
    "nlp": 0.65,
    "regex": 0.80,
    "union+date_normalize": 0.70,
    "union": 0.70,
    "field_map": 0.90,
}

# Importance weights for overall_confidence calculation
FIELD_WEIGHTS: dict[str, float] = {
    "full_name": 2.0,
    "emails": 2.0,
    "phones": 1.5,
    "location": 1.0,
    "skills": 1.5,
    "experience": 1.5,
    "education": 1.0,
    "headline": 0.5,
    "years_experience": 0.5,
    "links": 0.5,
}


def _source_confidence(source_str: str, method: str) -> float:
    # source_str may be comma-joined for multi-source fields
    sources = [s.strip() for s in source_str.split(",")]
    base = max((SOURCE_BASE.get(s, 0.70) for s in sources), default=0.70)
    method_mod = SOURCE_BASE.get(method, 0.0) - 0.80  # delta from method baseline
    return min(1.0, max(0.0, base + method_mod * 0.1))


def score(record: CanonicalRecord) -> CanonicalRecord:
    # Build a source→method lookup from provenance
    field_prov: dict[str, tuple[str, str]] = {}
    for p in record.provenance:
        if p.field not in field_prov:
            field_prov[p.field] = (p.source, p.method)

    field_scores: dict[str, float] = {}

    # Score each canonical field
    def _score_field(field: str, has_value: bool, prov_key: str | None = None) -> float:
        if not has_value:
            return 0.0
        key = prov_key or field
        if key in field_prov:
            src, method = field_prov[key]
            # Bonus: appears in multiple sources
            multi_bonus = 0.05 if "," in src else 0.0
            return min(1.0, _source_confidence(src, method) + multi_bonus)
        return 0.70  # default if no provenance entry

    field_scores["full_name"] = _score_field("full_name", bool(record.full_name))
    field_scores["emails"] = _score_field("emails", bool(record.emails))
    field_scores["phones"] = _score_field("phones", bool(record.phones))
    field_scores["location"] = _score_field("location", bool(record.location))
    field_scores["skills"] = _score_field("skills", bool(record.skills))
    field_scores["experience"] = _score_field("experience", bool(record.experience))
    field_scores["education"] = _score_field("education", bool(record.education))
    field_scores["headline"] = _score_field("headline", bool(record.headline))
    field_scores["years_experience"] = _score_field("years_experience", record.years_experience is not None)
    field_scores["links"] = _score_field("links", bool(record.links))

    # Score skills individually
    for skill in record.skills:
        multi = len(skill.sources) > 1
        base = max((SOURCE_BASE.get(s, 0.70) for s in skill.sources), default=0.70) * 0.90  # keyword match penalty
        skill.confidence = min(1.0, base + (0.05 if multi else 0.0))

    # Overall = weighted mean
    total_weight = 0.0
    weighted_sum = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        score_val = field_scores.get(field, 0.0)
        weighted_sum += score_val * weight
        total_weight += weight

    record.overall_confidence = round(weighted_sum / total_weight, 3) if total_weight > 0 else 0.0
    return record
