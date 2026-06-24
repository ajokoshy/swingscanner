"""
database_manager.py  —  SwingScanner v2
Schema and connection management. Compatible with Neon (serverless Postgres).

Migrations (ALTER TABLE) are intentionally NOT run here — they run once
in scanner_cron.py at scan startup, not on every Streamlit page load.
"""

import logging
import os
import sys

from sqlalchemy import (
    Column, Date, Float, Integer, String, Text,
    UniqueConstraint, create_engine, text,
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable is not set.")
    sys.exit(1)

# Neon / legacy Heroku URL scheme fix
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,     # detect stale connections
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,       # recycle every 5 min (prevents Neon idle disconnects)
    )
    Base = declarative_base()
except Exception as exc:
    logger.critical("Failed to create database engine: %s", exc)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ProScanResult(Base):
    __tablename__ = "pro_scans_v2"

    id            = Column(Integer, primary_key=True)
    symbol        = Column(String,  index=True, nullable=False)
    scan_date     = Column(Date,    index=True, nullable=False)
    score         = Column(Integer, nullable=False)
    setup_type    = Column(String)
    market_regime = Column(String)
    entry         = Column(Float)
    stop_loss     = Column(Float)
    target_1      = Column(Float)
    target_2      = Column(Float)
    target_3      = Column(Float)
    risk_reward   = Column(Float)
    explanation   = Column(Text)
    entry_score   = Column(Integer, nullable=True)  # 0–5: entry conditions passed
    entry_label   = Column(String,  nullable=True)  # human-readable entry verdict

    __table_args__ = (
        UniqueConstraint("symbol", "scan_date", name="_symbol_date_uc"),
    )

# ---------------------------------------------------------------------------
# Init — creates tables; does NOT run migrations (that's scanner_cron's job)
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every Streamlit load."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")


def run_migrations() -> None:
    """
    Add new columns if they don't exist yet.
    Called once per day by scanner_cron.py at scan start — NOT by the UI.
    Uses IF NOT EXISTS so it's safe to re-run.
    """
    migrations = [
        "ALTER TABLE pro_scans_v2 ADD COLUMN IF NOT EXISTS entry_score INTEGER",
        "ALTER TABLE pro_scans_v2 ADD COLUMN IF NOT EXISTS entry_label VARCHAR",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception:
                pass
        conn.commit()
    logger.info("Migrations applied.")
