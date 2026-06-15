"""
database_manager.py  —  SwingScanner v2
Schema and connection management.  Compatible with Neon (serverless Postgres).
"""

import logging
import os
import sys

from sqlalchemy import (
    Column, Date, Float, Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable is not set.")
    sys.exit(1)

# Heroku / Neon legacy URL scheme fix
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
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()
except Exception as exc:
    logger.critical("Failed to create database engine: %s", exc)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProScanResult(Base):
    __tablename__ = "pro_scans_v2"

    id             = Column(Integer, primary_key=True)
    symbol         = Column(String, index=True, nullable=False)
    scan_date      = Column(Date, index=True, nullable=False)
    score          = Column(Integer, nullable=False)
    setup_type     = Column(String)
    market_regime  = Column(String)
    sector_strength = Column(Float, nullable=True)   # optional; not always populated
    entry          = Column(Float)
    stop_loss      = Column(Float)
    target_1       = Column(Float)
    target_2       = Column(Float)
    target_3       = Column(Float)
    risk_reward    = Column(Float)
    explanation    = Column(Text)

    __table_args__ = (
        UniqueConstraint("symbol", "scan_date", name="_symbol_date_uc"),
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified / created.")
