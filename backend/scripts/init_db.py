#!/usr/bin/env python3
"""
Idempotent Postgres schema initializer for the candidates table.

Usage (from backend/):
    python scripts/init_db.py
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make `transformer` importable when run as a script from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# .env lives at the project root, one directory above backend/
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL is not set (checked project-root .env). Aborting.")
        sys.exit(1)

    from transformer.storage import init_schema

    init_schema(database_url)
    logger.info("candidates table ready (created if it did not already exist).")


if __name__ == "__main__":
    main()
