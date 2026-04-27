from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://freight:freight@postgres:5432/freight")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
