import os
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# Neon/Postgres URL handling
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nse_swing.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# The Table definition
class SwingResult(Base):
    __tablename__ = "swing_results"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    score = Column(Integer)
    classification = Column(String)
    entry = Column(Float)
    stop_loss = Column(Float)
    target_1 = Column(Float)
    target_2 = Column(Float)
    risk_reward = Column(String)
    reasons = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# THIS IS THE MISSING FUNCTION THAT CAUSED YOUR ERROR
def init_db():
    Base.metadata.create_all(bind=engine)
