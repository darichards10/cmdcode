"""
Test DB setup for server tests.

Uses an in-memory SQLite database. Tables are created and seeded before each
test and dropped after, ensuring full isolation between tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app, SEED_PROBLEMS, _register_ip_counts
from models import DBProblem

TEST_DATABASE_URL = "sqlite:///:memory:"
# StaticPool makes all sessions share one connection so in-memory data is visible everywhere
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=test_engine)
    # Seed problems
    db = TestSessionLocal()
    try:
        if db.query(DBProblem).count() == 0:
            for p in SEED_PROBLEMS:
                db.add(DBProblem(**p))
            db.commit()
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=test_engine)
    _register_ip_counts.clear()


@pytest.fixture
def db_session():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
