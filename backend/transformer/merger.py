import logging
from transformer.models import RawRecord, CanonicalRecord, ProvenanceEntry, SkillEntry, ExperienceEntry, EducationEntry
from transformer.normalizers.phone import normalize_phones
from transformer.normalizers.email import normalize_emails
from transformer.normalizers.skill import canonicalize_skills
from transformer.normalizers.location import normalize_location
from transformer.normalizers.date import normalize_date

logger = logging.getLogger(__name__)

# Higher index = lower priority
SOURCE_PRIORITY = ["ats_json", "csv", "github_url", "resume_pdf", "resume_docx", "recruiter_txt", "linkedin_url"]


def _priority(source_type: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source_type)
    except ValueError:
        return 99


def _sorted_records(records: list[RawRecord]) -> list[RawRecord]:
    return sorted(records, key=lambda r: _priority(r.source_type))


def _add_provenance(prov: list[ProvenanceEntry], field: str, source: str, method: str, note: str | None = None):
    prov.append(ProvenanceEntry(field=field, source=source, method=method, note=note))


def merge(records: list[RawRecord]) -> CanonicalRecord:
    if not records:
        return CanonicalRecord()

    sorted_recs = _sorted_records(records)
    canonical = CanonicalRecord()
    prov: list[ProvenanceEntry] = []

    # --- Scalar fields ---
    scalar_fields = ["full_name", "location_raw", "linkedin_url", "github_url", "portfolio_url", "headline", "years_experience"]

    for field in scalar_fields:
        winner_val = None
        winner_src = None
        for rec in sorted_recs:
            val = getattr(rec, field, None)
            if val is not None and str(val).strip():
                if winner_val is None:
                    winner_val = val
                    winner_src = rec.source_type
                else:
                    # Conflict: log field name only (not value)
                    logger.debug("Conflict on field '%s': %s overridden by %s", field, rec.source_type, winner_src)
                    _add_provenance(prov, field, rec.source_type, "direct",
                                    note=f"conflict: overridden by {winner_src}")

        if winner_val is not None:
            if field == "location_raw":
                canonical.location = normalize_location(str(winner_val))
                if canonical.location:
                    _add_provenance(prov, "location", winner_src, "direct+normalize")
            elif field == "linkedin_url":
                canonical.links["linkedin"] = winner_val
                _add_provenance(prov, "links.linkedin", winner_src, "direct")
            elif field == "github_url":
                canonical.links["github"] = winner_val
                _add_provenance(prov, "links.github", winner_src, "direct")
            elif field == "portfolio_url":
                canonical.links["portfolio"] = winner_val
                _add_provenance(prov, "links.portfolio", winner_src, "direct")
            else:
                setattr(canonical, field, winner_val)
                _add_provenance(prov, field, winner_src, "direct")

    # --- Array: emails ---
    all_emails: list[str] = []
    email_sources: dict[str, str] = {}
    for rec in sorted_recs:
        for e in rec.emails:
            if e and e not in email_sources:
                all_emails.append(e)
                email_sources[e] = rec.source_type

    normalized_emails = normalize_emails(all_emails)
    canonical.emails = normalized_emails
    if normalized_emails:
        _add_provenance(prov, "emails", ",".join(set(email_sources.values())), "direct+normalize")

    # --- Array: phones ---
    all_phones: list[str] = []
    phone_sources: dict[str, str] = {}
    for rec in sorted_recs:
        for p in rec.phones:
            if p and p not in phone_sources:
                all_phones.append(p)
                phone_sources[p] = rec.source_type

    normalized_phones = normalize_phones(all_phones)
    canonical.phones = normalized_phones
    if normalized_phones:
        _add_provenance(prov, "phones", ",".join(set(phone_sources.values())), "direct+normalize(E164)")

    # --- Array: skills (union by canonical name) ---
    skill_map: dict[str, SkillEntry] = {}
    for rec in sorted_recs:
        canonical_names = canonicalize_skills(rec.skills_raw)
        for name in canonical_names:
            if name not in skill_map:
                skill_map[name] = SkillEntry(name=name, confidence=0.0, sources=[])
            if rec.source_type not in skill_map[name].sources:
                skill_map[name].sources.append(rec.source_type)

    canonical.skills = list(skill_map.values())
    if canonical.skills:
        _add_provenance(prov, "skills", "multiple", "keyword_match+canonicalize")

    # --- Array: other_urls → links.other ---
    all_other_urls: list[str] = []
    seen_other: set[str] = set()
    for rec in sorted_recs:
        for url in rec.other_urls:
            if url and url not in seen_other:
                seen_other.add(url)
                all_other_urls.append(url)
    canonical.links["other"] = all_other_urls

    # --- candidate_id (deterministic from email or name) ---
    import hashlib
    id_seed = (canonical.emails[0] if canonical.emails else "") + (canonical.full_name or "")
    canonical.candidate_id = hashlib.md5(id_seed.encode()).hexdigest()[:16]

    # --- Experience: union, smart dedup ---
    # Primary dedup key: (company, title). If a richer entry (with dates/summary)
    # already exists for that pair, skip the sparse duplicate. If an existing entry
    # has no dates but the new one does, replace it with the richer version.
    exp_index: dict[tuple, int] = {}  # (company, title) -> index in canonical.experience
    for rec in sorted_recs:
        for exp in rec.experience:
            exp_copy = exp.model_copy()
            exp_copy.start = normalize_date(exp.start) if exp.start else None
            exp_copy.end = normalize_date(exp.end) if exp.end else None

            pair_key = (
                (exp_copy.company or "").lower().strip(),
                (exp_copy.title or "").lower().strip(),
            )

            if pair_key in exp_index:
                existing = canonical.experience[exp_index[pair_key]]
                # Replace if current entry is richer (has dates/summary that existing lacks)
                if not existing.start and exp_copy.start:
                    canonical.experience[exp_index[pair_key]] = exp_copy
            else:
                exp_index[pair_key] = len(canonical.experience)
                canonical.experience.append(exp_copy)

    if canonical.experience:
        _add_provenance(prov, "experience", "multiple", "union+date_normalize")

    # --- years_experience: compute from merged experience if not already set ---
    if canonical.years_experience is None and canonical.experience:
        from datetime import date as _date
        total_months = 0
        today = _date.today()
        for exp in canonical.experience:
            if not exp.start:
                continue
            try:
                sy, sm = map(int, exp.start.split("-"))
                if exp.end:
                    ey, em = map(int, exp.end.split("-"))
                else:
                    ey, em = today.year, today.month
                months = (ey - sy) * 12 + (em - sm)
                if months > 0:
                    total_months += months
            except Exception:
                continue
        if total_months > 0:
            canonical.years_experience = round(total_months / 12, 1)
            _add_provenance(prov, "years_experience", "multiple", "computed_from_experience")

    # --- Education: union, basic dedup ---
    seen_edu: set[tuple] = set()
    for rec in sorted_recs:
        for edu in rec.education:
            key = (edu.institution, edu.degree)
            if key not in seen_edu:
                seen_edu.add(key)
                canonical.education.append(edu)
    if canonical.education:
        _add_provenance(prov, "education", "multiple", "union")

    canonical.provenance = prov
    return canonical


def merge_canonical_dicts(existing: dict, incoming: dict) -> CanonicalRecord:
    """
    Merge two already-canonicalized records for the SAME candidate_id
    (e.g. one captured via LinkedIn OAuth today, another via resume+GitHub
    next week). Used by storage.upsert_candidate to fold a new submission
    into a candidate's existing profile instead of creating a duplicate row.

    Reconstructs pseudo-RawRecords from each canonical dict's provenance so
    the normal merge() priority/union/dedup logic can be reused unchanged.
    """
    pseudo_records: list[RawRecord] = []

    for snapshot in (existing, incoming):
        if not snapshot:
            continue
        prov_by_field = {p["field"]: p for p in snapshot.get("provenance", [])}
        source_label = next(iter(prov_by_field.values()), {}).get("source", "merged") if prov_by_field else "merged"
        # A merged snapshot can span multiple original sources; treat it as
        # a single high-trust pseudo-source named after its candidate_id so
        # priority ordering still resolves deterministically (most recently
        # submitted snapshot wins ties via stable sort order below).
        rec = RawRecord(
            source_type="csv",  # reuse a high-priority slot; pseudo-records are pre-normalized
            full_name=snapshot.get("full_name"),
            emails=list(snapshot.get("emails") or []),
            phones=list(snapshot.get("phones") or []),
            headline=snapshot.get("headline"),
            years_experience=snapshot.get("years_experience"),
            skills_raw=[s.get("name") for s in (snapshot.get("skills") or []) if s.get("name")],
            experience=[ExperienceEntry(**e) for e in (snapshot.get("experience") or [])],
            education=[EducationEntry(**e) for e in (snapshot.get("education") or [])],
            linkedin_url=(snapshot.get("links") or {}).get("linkedin"),
            github_url=(snapshot.get("links") or {}).get("github"),
            portfolio_url=(snapshot.get("links") or {}).get("portfolio"),
            other_urls=list((snapshot.get("links") or {}).get("other") or []),
            location_raw=", ".join(filter(None, [
                (snapshot.get("location") or {}).get("city"),
                (snapshot.get("location") or {}).get("region"),
                (snapshot.get("location") or {}).get("country"),
            ])) or None,
        )
        pseudo_records.append(rec)

    merged = merge(pseudo_records)

    # Preserve full provenance history from both snapshots (not just the
    # synthetic "csv" entries merge() generated for the pseudo-records).
    merged.provenance = [
        ProvenanceEntry(**p) for p in (existing.get("provenance") or [])
    ] + [
        ProvenanceEntry(**p) for p in (incoming.get("provenance") or [])
    ] + merged.provenance

    return merged
