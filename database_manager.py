import os, sys
from sqlalchemy import create_engine, Column, String, Float, Integer, Date, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# 1. DATABASE URL VALIDATION
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("FATAL: DATABASE_URL not found in environment variables.")
    sys.exit(1)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()
except Exception as e:
    print(f"FATAL: Failed to connect to database: {e}")
    sys.exit(1)

class ProScanResult(Base):
    __tablename__ = "pro_scans_v2"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    scan_date = Column(Date, default=datetime.utcnow().date)
    score = Column(Integer)
    setup_type = Column(String) # Breakout, VCP, Pullback, etc.
    market_regime = Column(String)
    sector_strength = Column(Float)
    entry = Column(Float)
    stop_loss = Column(Float)
    target_1 = Column(Float)
    target_2 = Column(Float)
    target_3 = Column(Float)
    risk_reward = Column(Float)
    explanation = Column(Text)

    # 8. PREVENT DUPLICATE SCANS PER DAY
    __table_args__ = (UniqueConstraint('symbol', 'scan_date', name='_symbol_date_uc'),)

def init_db():
    Base.metadata.create_all(bind=engine)