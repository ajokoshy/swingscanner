import os
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class ProScanResult(Base):
    __tablename__ = "pro_scans"
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    score = Column(Integer)
    setup_type = Column(String)
    entry = Column(Float)
    stop_loss = Column(Float)
    target1 = Column(Float)
    regime = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)