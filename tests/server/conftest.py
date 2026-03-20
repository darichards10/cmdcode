"""
Test DB setup for server tests.

Uses an in-memory SQLite database. Tables are created and seeded before each
test and dropped after, ensuring full isolation between tests.
"""
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import DBProblem
from main import app

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

_PROBLEMS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "server", "problems.json"
)


def _seed_test_problems(db):
    """Seed problems into the test database from the JSON file."""
    with open(_PROBLEMS_FILE) as f:
        problems = json.load(f)
    for p in problems:
        if not db.query(DBProblem).filter(DBProblem.id == p["id"]).first():
            db.add(DBProblem(**p))
    db.commit()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=test_engine)
    # Seed problems
    db = TestSessionLocal()
    try:
        _seed_test_problems(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=test_engine)
    # Clear in-memory registration rate-limit state between tests
    from main import _register_ip_counts
    _register_ip_counts.clear()


@pytest.fixture
def db_session():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
