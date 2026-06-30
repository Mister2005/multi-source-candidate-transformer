"""
Postgres storage layer for canonical candidate records.

Uses SQLAlchemy Core (no ORM models needed for this small surface area) against
a `candidates` table:

    id                  SERIAL PRIMARY KEY
    candidate_id        TEXT (the deterministic hash from merger.py), indexed
    canonical_record     JSONB  -- full canonical output
    overall_confidence  FLOAT
    created_at          TIMESTAMP DEFAULT now()
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    select,
    insert,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB

from transformer.merger import merge_canonical_dicts
from transformer import confidence as confidence_module

logger = logging.getLogger(__name__)

metadata = MetaData()

candidates_table = Table(
    "candidates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("candidate_id", String, index=True, nullable=False),
    Column("canonical_record", JSONB, nullable=False),
    Column("overall_confidence", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

_engine_cache: dict[str, "object"] = {}


def _get_engine(database_url: str):
    """Cache one engine per database_url to avoid reconnect overhead across calls."""
    if database_url not in _engine_cache:
        _engine_cache[database_url] = create_engine(database_url, future=True)
    return _engine_cache[database_url]


def init_schema(database_url: str) -> None:
    """Create the candidates table if it doesn't already exist. Idempotent."""
    engine = _get_engine(database_url)
    metadata.create_all(engine, tables=[candidates_table], checkfirst=True)


def save_candidate(record: dict, database_url: str) -> int:
    """
    Upsert a canonical candidate record by candidate_id.

    If no row exists yet for this candidate_id, inserts a new one. If a row
    already exists (e.g. the same person was submitted once via LinkedIn and
    again later via resume+GitHub), the two canonical snapshots are merged
    into a single profile instead of creating a duplicate row — same union/
    priority rules as the main pipeline merge, plus confidence is recomputed
    over the merged result.
    """
    engine = _get_engine(database_url)
    init_schema(database_url)

    candidate_id = record.get("candidate_id", "")

    with engine.begin() as conn:
        existing_row = conn.execute(
            select(candidates_table).where(candidates_table.c.candidate_id == candidate_id)
        ).mappings().first()

        if existing_row:
            merged_canonical = merge_canonical_dicts(dict(existing_row["canonical_record"]), record)
            merged_canonical = confidence_module.score(merged_canonical)
            merged_dict = merged_canonical.model_dump()

            conn.execute(
                update(candidates_table)
                .where(candidates_table.c.id == existing_row["id"])
                .values(canonical_record=merged_dict, overall_confidence=merged_dict.get("overall_confidence"))
            )
            logger.info("Merged new submission into existing candidate %s (row id=%s)", candidate_id, existing_row["id"])
            return existing_row["id"]

        result = conn.execute(
            insert(candidates_table).values(
                candidate_id=candidate_id,
                canonical_record=record,
                overall_confidence=record.get("overall_confidence"),
            )
        )
        new_id = result.inserted_primary_key[0]
    logger.info("Saved new candidate %s to Postgres (row id=%s)", candidate_id, new_id)
    return new_id


def get_candidate(candidate_id: str, database_url: str) -> dict | None:
    """
    Fetch the most recent stored record for a given candidate_id, or None.
    """
    engine = _get_engine(database_url)
    init_schema(database_url)

    with engine.connect() as conn:
        row = conn.execute(
            select(candidates_table)
            .where(candidates_table.c.candidate_id == candidate_id)
            .order_by(candidates_table.c.created_at.desc())
            .limit(1)
        ).mappings().first()

    if not row:
        return None
    return dict(row)


def list_candidates(database_url: str) -> list[dict]:
    """
    List all stored candidates (most recent first).
    """
    engine = _get_engine(database_url)
    init_schema(database_url)

    with engine.connect() as conn:
        rows = conn.execute(
            select(candidates_table).order_by(candidates_table.c.created_at.desc())
        ).mappings().all()

    return [dict(r) for r in rows]
