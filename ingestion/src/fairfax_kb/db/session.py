"""DB session helper."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fairfax_kb.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    return SessionLocal()
