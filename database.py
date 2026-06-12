import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Get the URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Fix Neon/Heroku/Render prefix: SQLAlchemy requires 'postgresql://' not 'postgres://'
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Create the engine
# 'pool_pre_ping' is highly recommended for serverless DBs like Neon
engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ... rest of your SwingResult class remains the same ...